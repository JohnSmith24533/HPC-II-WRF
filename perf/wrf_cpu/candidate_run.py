#!/usr/bin/env python3
"""Measure and strictly verify a separate candidate against selected full-run medians."""
import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import shutil
import statistics
import traceback

import audit
import certify_scaled
import hardware
import retire_scaling_outputs
import run
import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('--cases', nargs='+', choices=run.CASES, required=True)
    parser.add_argument('--install', type=Path, required=True)
    parser.add_argument('--provenance', type=Path, required=True,
                        help='JSON with payload_sha256 mapping absolute file paths to hashes')
    parser.add_argument('--selection', type=Path, default=run.ART/'progress/S006-winners.json')
    parser.add_argument('--reference-name', default='scaled-golden')
    parser.add_argument('--repetitions', type=int, default=3)
    parser.add_argument('--retain-outputs', action='store_true',
                        help='keep all scientific outputs after verification')
    args = parser.parse_args()
    args.install = args.install.resolve()
    if not re.fullmatch(r'C\d{3}-[A-Za-z0-9_-]+', args.label) or args.repetitions < 3:
        parser.error('use a unique Cnnn-label and at least three independent full runs')
    if not os.environ.get('SLURM_JOB_ID') or len(set(args.cases)) != len(args.cases):
        parser.error('use a Slurm allocation and distinct cases')
    ideal = any(case != 'conus12' for case in args.cases)
    if ideal and ('conus12' in args.cases or int(os.environ.get('SLURM_JOB_NUM_NODES', '0')) != 1):
        parser.error('ideal cases need a separate single-node allocation')
    selection = json.loads(args.selection.read_text())
    configs = certify_scaled.selected_configurations(selection)
    if max(configs[c]['ranks'] for c in args.cases) > int(os.environ.get('SLURM_NTASKS', '0')):
        parser.error('selected ranks exceed allocated slots')
    provenance = json.loads(args.provenance.read_text())
    payload = provenance['payload_sha256']
    thread_map=provenance.get('threads_by_case',{})
    if any(type(thread_map.get(c,1)) is not int or thread_map.get(c,1)<1 or configs[c]['ranks']*thread_map.get(c,1)>int(os.environ['SLURM_NTASKS']) for c in args.cases):
        parser.error('declared MPI ranks times threads exceed the original allocation')
    executable = (args.install/'bin/wrf').resolve()
    if str(executable) not in payload or not payload:
        parser.error('candidate executable must be included in payload hashes')

    def check_payload():
        for path, expected in payload.items():
            if not Path(path).is_absolute() or run.digest(Path(path)) != expected:
                raise RuntimeError('candidate payload changed: '+path)

    check_payload()
    directory = run.ART/'experiments'/args.label/('ideal' if ideal else 'real')
    directory.mkdir(parents=True, exist_ok=False)
    shutil.copy2(args.provenance, directory/'candidate.json')
    shutil.copy2(args.selection, directory/'selection.json')
    snapshot = directory/'harness'; snapshot.mkdir()
    for path in Path(__file__).parent.iterdir():
        if path.is_file(): shutil.copy2(path, snapshot/path.name)
    meta = {'label': args.label, 'status': 'initializing', 'cases': args.cases,
            'job_id': os.environ['SLURM_JOB_ID'], 'host': os.uname().nodename,
            'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'reference_name': args.reference_name, 'candidate_provenance': provenance,
            'selection_sha256': run.digest(args.selection), 'repetitions': args.repetitions,
            'outputs_retained': args.retain_outputs,
            'primary_metric': 'complete WRF wall-clock seconds / verified completed timesteps'}
    rows, scores = [], {}

    def save():
        meta['updated_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
        verify.save(directory/'results.json', {'experiment': meta, 'runs': rows, 'scores': scores})

    save()
    try:
        audit.audit(run.ART, args.reference_name)
        meta['reference_manifest_sha256'] = run.digest(run.ART/args.reference_name/'manifest.json')
        signatures = [hardware.reference_signature(selection, c) for c in args.cases]
        if any(hardware.differences(s, signatures[0]) for s in signatures[1:]):
            raise RuntimeError('candidate group mixes incompatible hardware')
        hardware.audit_allocation(args.selection, directory/'hardware', case=args.cases[0])
        meta['status'] = 'running'; save()
        for case in args.cases:
            config = configs[case]
            reference = run.ART/args.reference_name/case
            baseline = json.loads((reference/'full/run.json').read_text())
            for key in ('ranks', 'processor_grid', 'mpi_options'):
                if baseline.get(key) != config[key]:
                    raise RuntimeError('sealed reference differs from selected '+key)
            threads=thread_map.get(case,1)
            mpi_options=provenance.get('mpi_options_by_case',{}).get(case,config['mpi_options'])
            omp_tiles=[1,threads] if threads>1 else None
            times = []
            for repeat in range(1, args.repetitions+1):
                label = f'{args.label}-r{repeat:02d}-p{config["ranks"]:03d}'
                full = None
                tiers = ('single', 'short', 'full', 'restart') if repeat == 1 else ('full',)
                for tier in tiers:
                    check_payload()
                    dest = run.run_case(case, tier, label, config['ranks'], args.install, args.install,
                                        mpi_options=mpi_options, processor_grid=config['processor_grid'],threads=threads,omp_tiles=omp_tiles)
                    if tier != 'restart':
                        compared = verify.compare(dest, reference/tier)
                        verify.save(dest/'candidate-compare.json', json.loads(json.dumps(compared, default=lambda x:x.item())))
                        if not compared['passed'] or compared['mode'] != 'bitwise':
                            raise RuntimeError('candidate differs from sealed reference: '+str(dest))
                    trial = json.loads((dest/'run.json').read_text())
                    checked = json.loads((dest/'check.json').read_text())
                    seconds = trial['wall_seconds']/checked['steps']
                    if not math.isfinite(seconds) or seconds <= 0:
                        raise RuntimeError('invalid candidate timing')
                    row = {'case': case, 'tier': tier, 'repeat': repeat, 'label': label,
                           'directory': str(dest), 'execution_passed': True,
                           'bitwise_passed': True, 'wall_seconds': trial['wall_seconds'],
                           'timesteps': checked['steps'], 'wall_seconds_per_timestep': seconds,
                           'mean_step_wall_seconds': trial['step_timing_seconds']['mean'],
                           'median_step_wall_seconds': trial['step_timing_seconds']['median'],
                           'threads':threads,'omp_tiles':omp_tiles,'mpi_options':mpi_options}
                    prefix = provenance.get('compression_report_prefix')
                    if prefix:
                        reports = sorted(dest.glob(prefix+'-r*.json'))
                        fast_calls = sum(json.loads(p.read_text())['fast_calls'] for p in reports)
                        if not reports or fast_calls <= 0:
                            raise RuntimeError('no proof that the requested compression backend ran')
                        row['compression_fast_calls'] = fast_calls
                        row['compression_reports_sha256'] = {str(p): run.digest(p) for p in reports}
                    rows.append(row); save()
                    if tier == 'full':
                        full = dest; times.append(seconds)
                    elif tier == 'short' and not args.retain_outputs:
                        row['retired_output_bytes'] = retire_scaling_outputs.retire(dest); save()
                # First full checkpoints must survive until its restart has passed.
                if not args.retain_outputs:
                    rows[-1]['retired_full_output_bytes'] = retire_scaling_outputs.retire(full); save()
            median = statistics.median(times)
            scores[case] = {'repetitions': len(times), 'wall_seconds_per_timestep': times,
                            'median_wall_seconds_per_timestep': median,
                            'baseline_wall_seconds_per_timestep': config['wall_seconds_per_timestep'],
                            'speedup': config['wall_seconds_per_timestep']/median}
            save()
        check_payload()
        meta['status'] = 'completed'
    except BaseException:
        meta.update(status='failed', error=traceback.format_exc()); raise
    finally: save()
    print(json.dumps({'label': args.label, 'cases': args.cases, 'scores': scores}), flush=True)


if __name__ == '__main__':
    main()
