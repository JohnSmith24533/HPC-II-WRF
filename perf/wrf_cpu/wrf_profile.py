#!/usr/bin/env python3
"""Sample a full WRF trajectory only after its scaled reference has been sealed."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import traceback

import audit
import run
import verify
import hardware


def sample_ranks(ranks):
    return sorted({0, ranks // 4, ranks // 2, ranks - 1})


def reported_samples(report):
    match = re.search(r'#\s*Samples:\s*([\d.]+)\s*([KMG]?)\b', report)
    if not match:
        raise ValueError('perf report does not contain a sample count')
    return float(match[1]) * {'':1, 'K':1e3, 'M':1e6, 'G':1e9}[match[2]]


def wrapper_text(executable, directory, ranks, frequency):
    selected = '|'.join(str(r) for r in sample_ranks(ranks))
    output = shlex.quote(str(directory)) + '/perf-r"${rank}".data'
    target = shlex.quote(str(executable))
    return ('#!/usr/bin/env bash\nset -euo pipefail\n'
            'rank=${OMPI_COMM_WORLD_RANK:?missing MPI rank}\n'
            'case "$rank" in\n' + selected + ')\n'
            'exec /usr/bin/perf record -e cycles:u -F ' + str(frequency) +
            ' --call-graph dwarf,8192 -o ' + output + ' -- ' + target + '\n;;\n'
            '*) exec ' + target + '\n;;\nesac\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('--case', choices=run.CASES, required=True)
    parser.add_argument('--reference-name', default='scaled-golden')
    parser.add_argument('--executable', type=Path, help='optional candidate to re-profile; still requires strict numerical equivalence')
    parser.add_argument('--frequency', type=int, default=199)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.label) or not 1 <= args.frequency <= 999:
        parser.error('invalid experiment label or sample frequency')
    if not os.environ.get('SLURM_JOB_ID'):
        parser.error('profile WRF on a Slurm compute allocation')
    # This gate enforces the requested order: scaling/reference first, then profiling.
    manifest = audit.audit(run.ART, args.reference_name)
    reference = run.ART / args.reference_name / args.case / 'full'
    baseline = json.loads((reference / 'run.json').read_text())
    ranks = baseline['ranks']
    if ranks > int(os.environ.get('SLURM_NTASKS', '0')):
        parser.error('reference MPI ranks exceed this allocation')
    default_executable = run.ART / ('install-real' if args.case == 'conus12' else 'install-ideal') / 'bin/wrf'
    executable = (args.executable or default_executable).resolve()
    executable_sha256 = run.digest(executable)
    if not args.executable and executable_sha256 != baseline['executable_sha256']:
        raise RuntimeError('baseline executable changed since scaled reference publication')
    directory = run.ART / 'experiments' / args.label / args.case
    directory.mkdir(parents=True, exist_ok=False)
    install = directory / 'wrapper-install'
    (install / 'bin').mkdir(parents=True)
    wrapper = install / 'bin/wrf'
    wrapper.write_text(wrapper_text(executable, directory, ranks, args.frequency))
    wrapper.chmod(0o755)
    subprocess.run(['bash', '-n', str(wrapper)], check=True)
    meta = {'label': args.label, 'case': args.case, 'status': 'prepared',
            'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'job_id': os.environ['SLURM_JOB_ID'], 'host': os.uname().nodename,
            'reference_name': args.reference_name, 'reference_baseline_label': manifest['baseline_label'],
            'reference_manifest_sha256': run.digest(run.ART / args.reference_name / 'manifest.json'),
            'actual_executable': str(executable), 'actual_executable_sha256': executable_sha256,
            'ranks': ranks, 'sampled_ranks': sample_ranks(ranks), 'frequency_hz': args.frequency,
            'sample_event': 'cycles:u', 'call_graph': 'dwarf,8192',
            'mpi_options': baseline.get('mpi_options', []),
            'processor_grid': baseline.get('processor_grid'),
            'profile_only': True, 'timing_note': 'Profiler/wrapper overhead: never use this run to claim speedup.',
            'perf_version': subprocess.check_output(['perf', '--version'], text=True).strip()}
    shutil.copy2(__file__, directory / 'profile-harness.py')
    verify.save(directory / 'profile.json', meta)
    try:
        meta['status'] = 'running'
        verify.save(directory / 'profile.json', meta)
        hardware.audit_allocation(reference/'run.json',directory/'hardware')
        dest = run.run_case(args.case, 'full', args.label, ranks, install, install,
                            mpi_options=meta['mpi_options'],processor_grid=meta['processor_grid'])
        compared = verify.compare(dest, reference)
        compared = json.loads(json.dumps(compared, default=lambda x: x.item()))
        verify.save(dest / 'profile-compare.json', compared)
        if not compared['passed']:
            raise RuntimeError('profiled run differs from the sealed same-rank reference')
        meta['numerical_comparison_passed'] = True
        meta['reports'] = []
        meta['samples_by_rank'] = {}
        for rank in meta['sampled_ranks']:
            data = directory / f'perf-r{rank}.data'
            if not data.is_file() or data.stat().st_size == 0:
                raise RuntimeError(f'no profiling data for sampled rank {rank}')
            for kind, options in [('flat', ['--no-children', '--show-nr-samples', '--sort', 'dso,symbol']),
                                  ('callgraph', ['--children', '--call-graph', 'graph,0.5,caller'])]:
                output = directory / f'rank-{rank}-{kind}.txt'
                with output.open('w') as stream:
                    result = subprocess.run(['perf', 'report', '--stdio', '--percent-limit', '0.5',
                                             '-i', str(data), *options], stdout=stream, stderr=subprocess.STDOUT)
                if result.returncode:
                    raise RuntimeError(f'perf report failed: {output}')
                meta['reports'].append(str(output))
                if kind == 'flat':
                    count = reported_samples(output.read_text())
                    meta['samples_by_rank'][str(rank)] = count
                    if count < 100:
                        raise RuntimeError(f'insufficient sampling coverage for rank {rank}: {count}; increase frequency in a new experiment')
            header = subprocess.check_output(['perf', 'report', '--stdio', '--header-only', '-i', str(data)], text=True)
            (directory / f'rank-{rank}-header.txt').write_text(header)
        meta['status'] = 'completed'
    except BaseException:
        meta['status'] = 'failed'
        meta['error'] = traceback.format_exc()
        raise
    finally:
        meta['updated_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
        verify.save(directory / 'profile.json', meta)
    print(json.dumps(meta), flush=True)


if __name__ == '__main__':
    main()
