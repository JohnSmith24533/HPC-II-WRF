#!/usr/bin/env python3
"""Measure the unchanged WRF build across MPI ranks without changing the cases."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import traceback

import audit
import retire_scaling_outputs
import run
import verify


def processor_mesh(ranks):
    """Match RSL_LITE MPASPECT's first closest-to-square factor pair."""
    return min(((x, ranks // x) for x in range(1, ranks + 1) if ranks % x == 0),
               key=lambda xy: abs(xy[0] - xy[1]))


def fits(case, ranks, grid=None):
    nx, ny = grid or processor_mesh(ranks)
    ex, ey, _ = run.CASES[case]['grid']
    return nx>0 and ny>0 and nx*ny==ranks and ex // nx >= 10 and ey // ny >= 10


def configurations(matrix, cases):
    result={}
    for case in cases:
        entries=[]
        for entry in matrix.get(case,[]):
            config={'ranks':entry} if type(entry) is int else dict(entry)
            if set(config)-{'ranks','processor_grid'} or type(config.get('ranks')) is not int or config['ranks']<1:
                raise ValueError('matrix entries require positive ranks and optional processor_grid')
            grid=config.get('processor_grid')
            if grid is not None and (len(grid)!=2 or any(type(n) is not int or n<1 for n in grid) or grid[0]*grid[1]!=config['ranks']):
                raise ValueError('processor_grid must contain two positive factors of ranks')
            entries.append(config)
        if not entries or len({c['ranks'] for c in entries})!=len(entries):
            raise ValueError('matrix requires distinct rank counts for every selected case; use separate labels for layout variants')
        if not any(fits(case,c['ranks'],c.get('processor_grid')) for c in entries):
            raise ValueError('matrix has no valid decomposition for '+case)
        result[case]=entries
    return result


def summaries(rows):
    groups = {}
    for row in rows:
        if row.get('execution_passed') and 'error' not in row and row.get('wall_seconds') is not None:
            groups.setdefault((row['case'], row['tier'], row['ranks']), []).append(row)
    result = []
    for (case, tier, ranks), values in sorted(groups.items()):
        walls = [v['wall_seconds'] for v in values]
        result.append({'case': case, 'tier': tier, 'ranks': ranks,
                       'repetitions': len(walls), 'wall_median_seconds': statistics.median(walls),
                       'wall_min_seconds': min(walls), 'wall_max_seconds': max(walls),
                       'wall_seconds_per_timestep': statistics.median(v['wall_seconds_per_timestep'] for v in values),
                       'mean_step_wall_seconds': statistics.median(v['mean_step_wall_seconds'] for v in values),
                       'step_median_seconds': statistics.median(v['step_median_seconds'] for v in values),
                       'all_cross_rank_bitwise': all(v.get('cross_rank_bitwise') is True for v in values)})
    return result


def write_results(directory, meta, rows):
    data = {'experiment': meta, 'runs': rows, 'summary': summaries(rows)}
    temporary = directory / 'results.tmp'
    verify.save(temporary, data)
    temporary.replace(directory / 'results.json')
    lines = ['# ' + meta['label'], '',
             'Status: ' + meta['status'] + '. These are scaling measurements, not a certified optimized baseline.', '',
             'Wall time includes mpirun startup, WRF initialization, integration, history and restart I/O; verification is outside the timer.',
             'Cases, grids, time steps, physics, inputs, output cadence and checkpoint schedule follow the original verification harness.',
             'Cross-rank differences are reported, never converted to a tolerance pass. A selected new rank count needs independent repeat/restart certification.', '',
             'Primary metric: total WRF wall-clock seconds / verified completed timesteps. Also report the mean and median Timing-for-main step timers separately.', '',
             '| Case | Tier | Ranks | Repeats | Median wall s | Wall s/timestep | Mean main-step s | Median main-step s | Cross-rank bitwise |',
             '|---|---|---|---|---|---|---|---|---|']
    for row in data['summary']:
        lines.append('| {case} | {tier} | {ranks} | {repetitions} | {wall_median_seconds:.6f} | '
                     '{wall_seconds_per_timestep:.6f} | {mean_step_wall_seconds:.6f} | {step_median_seconds:.6f} | '
                     '{all_cross_rank_bitwise} |'.format(**row))
    for row in rows:
        if not row.get('execution_passed') or 'error' in row:
            lines.extend(['', 'Failed trial (evidence retained): ' + json.dumps(row, ensure_ascii=False)])
    (directory / 'RESULTS.md').write_text('\n'.join(lines) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('--cases', nargs='+', choices=run.CASES, default=list(run.CASES))
    parser.add_argument('--ranks', nargs='+', type=int, default=[1, 2, 4, 8, 16, 28, 32, 56, 64, 100, 112])
    parser.add_argument('--tiers', nargs='+', choices=['short', 'full'], default=['short'])
    parser.add_argument('--repetitions', type=int, default=1)
    parser.add_argument('--matrix', help='JSON object mapping each selected case to its rank list')
    parser.add_argument('--compare-repeats', action='store_true', help='strictly compare repeats to the first run at the same rank')
    parser.add_argument('--discard-verified-output', action='store_true', help='journal output hashes then retire reproducible arrays after comparisons; retain first-repeat history until its final repeat')
    parser.add_argument('--mpi-map-by', choices=['core','package:SPAN'], default='core', help='core packing or spreading across packages; always bind each rank to one core')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.label) or args.repetitions < 1 or min(args.ranks) < 1:
        parser.error('invalid label, repetitions or rank count')
    if not os.environ.get('SLURM_JOB_ID'):
        parser.error('run scaling on a Slurm compute allocation')
    matrix = json.loads(Path(args.matrix).read_text()) if args.matrix else {case: args.ranks for case in args.cases}
    try:
        matrix=configurations(matrix,args.cases)
    except (TypeError,ValueError) as exc:
        parser.error(str(exc))
    if max(c['ranks'] for case in args.cases for c in matrix[case]) > int(os.environ.get('SLURM_NTASKS', '0')):
        parser.error('requested MPI ranks exceed allocation')
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=run.ROOT, text=True).strip()
    if branch != 'perf/wrf-cpu':
        raise RuntimeError('branch must remain perf/wrf-cpu')
    directory = run.ART / 'experiments' / args.label
    directory.mkdir(parents=True, exist_ok=False)
    # Command-line directives work across OpenMPI/PRRTE parameter namespaces.
    mpi_options = ['--bind-to', 'core', '--map-by', args.mpi_map_by, '--report-bindings']
    meta = {'label': args.label, 'status': 'initializing', 'arguments': vars(args),
            'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=run.ROOT, text=True).strip(),
            'official_model_commit': (run.ART / 'baseline/source-commit.txt').read_text().strip(),
            'job_id': os.environ['SLURM_JOB_ID'], 'host': os.uname().nodename,
            'omp_num_threads': os.environ.get('OMP_NUM_THREADS'),
            'primary_metric': 'complete WRF wall-clock seconds / verified completed timesteps',
            'verification_workers': int(os.environ.get('WRF_VERIFY_WORKERS','1')),
            'verification_equivalence_report': str(run.ART/'progress'/f'verify-parallel-{os.environ["SLURM_JOB_ID"]}.json'),
            'mpi_binding': 'core', 'mpi_mapping': args.mpi_map_by, 'mpi_options': mpi_options, 'matrix': matrix,
            'lscpu': json.loads(subprocess.check_output(['lscpu', '-J'], text=True)),
            'executable_sha256': {kind: run.digest(run.ART / ('install-' + kind) / 'bin/wrf')
                                  for kind in ('ideal', 'real')},
            'skipped_invalid_decompositions': [{'case':case,'ranks':c['ranks'],'mesh':c.get('processor_grid') or processor_mesh(c['ranks'])}
                                              for case in args.cases for c in matrix[case] if not fits(case,c['ranks'],c.get('processor_grid'))]}
    snapshot = directory / 'harness'
    snapshot.mkdir()
    for source in Path(__file__).parent.iterdir():
        if source.is_file():
            shutil.copy2(source, snapshot / source.name)
    (directory / 'working-tree.patch').write_bytes(subprocess.check_output(['git', 'diff', 'HEAD'], cwd=run.ROOT))
    (directory / 'slurm-job.txt').write_bytes(subprocess.check_output(['scontrol', 'show', 'job', os.environ['SLURM_JOB_ID']]))
    meta['profiler_permissions'] = {}
    for event in ('cycles:u', 'cpu-clock:u'):
        probe = subprocess.run(['perf', 'stat', '-e', event, '--', '/bin/true'],
                               text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        meta['profiler_permissions'][event] = {'exit_code': probe.returncode, 'output': probe.stdout}
    rows = []
    write_results(directory, meta, rows)
    try:
        # Integrity checks precede measurements and are never charged to WRF.
        audit.audit(run.ART)
        expected = {line.split()[1]: line.split()[0] for line in
                    (run.ART / 'baseline/executables.sha256').read_text().splitlines()}
        for kind in ('ideal', 'real'):
            executable = run.ART / ('install-' + kind) / 'bin/wrf'
            if run.digest(executable) != expected[str(executable)]:
                raise RuntimeError('scaling baseline executable differs from archived official build')
        meta['status'] = 'running'
        write_results(directory, meta, rows)
        for repeat in range(1, args.repetitions + 1):
            # Alternate sweep direction to reduce systematic rank/order effects.
            for case in args.cases:
                ranks_order = sorted(matrix[case],key=lambda c:c['ranks'],reverse=repeat % 2 == 0)
                for config in ranks_order:
                    ranks=config['ranks']
                    grid=config.get('processor_grid')
                    if not fits(case, ranks, grid):
                        continue
                    label = f'{args.label}-r{repeat:02d}-p{ranks:03d}'
                    for tier in args.tiers:
                        row = {'case': case, 'tier': tier, 'ranks': ranks, 'repeat': repeat,
                               'label': label, 'processor_grid':grid, 'execution_passed': False}
                        try:
                            dest = run.run_case(case, tier, label, ranks, mpi_options=mpi_options,processor_grid=grid)
                            trial = json.loads((dest / 'run.json').read_text())
                            logs = (dest / 'rsl.out.0000').read_text()
                            io = [float(v) for v in re.findall(r'Timing for Writing.*?:\s+([\d.Ee+-]+)\s+elapsed seconds', logs)]
                            steps = trial['step_timing_seconds']
                            checked = json.loads((dest / 'check.json').read_text())
                            if not checked['steps'] or steps['count'] != checked['steps']:
                                raise RuntimeError('cannot normalize wall time with missing per-step timing coverage')
                            row.update(execution_passed=True, directory=str(dest), wall_seconds=trial['wall_seconds'],
                                       timesteps=checked['steps'],
                                       wall_seconds_per_timestep=trial['wall_seconds'] / checked['steps'],
                                       mean_step_wall_seconds=sum(steps['values']) / checked['steps'],
                                       step_median_seconds=steps['median'], step_sum_seconds=sum(steps['values']),
                                       io_write_seconds=sum(io))
                            comparison = verify.compare(dest, run.ART / 'golden' / case / tier)
                            comparison = json.loads(json.dumps(comparison, default=lambda x: x.item()))
                            verify.save(dest / 'cross-rank-compare.json', comparison)
                            row.update(cross_rank_bitwise=comparison['passed'],
                                       differing_metric_rows=sum(not m['passed'] for m in comparison['metrics']),
                                       compared_metric_rows=len(comparison['metrics']))
                            if args.compare_repeats and repeat > 1:
                                reference = run.ART / 'runs' / f'{args.label}-r01-p{ranks:03d}' / case / tier
                                repeated = verify.compare(dest, reference)
                                repeated = json.loads(json.dumps(repeated, default=lambda x: x.item()))
                                verify.save(dest / 'repeat-compare.json', repeated)
                                row['same_rank_repeat_bitwise'] = repeated['passed']
                                if not repeated['passed']:
                                    raise RuntimeError('independent same-rank repeat differs bitwise')
                        except Exception:
                            row['error'] = traceback.format_exc()
                        rows.append(row)
                        write_results(directory, meta, rows)
                        print(json.dumps(row), flush=True)
                        if 'error' in row:
                            raise RuntimeError('scaling trial failed; stop before launching another configuration: ' + label)
                        if args.discard_verified_output:
                            keep = args.compare_repeats and repeat == 1 and args.repetitions > 1
                            row['retired_output_bytes'] = retire_scaling_outputs.retire(dest, keep_history=keep)
                            if args.compare_repeats and repeat == args.repetitions and repeat > 1:
                                row['retired_first_repeat_bytes'] = retire_scaling_outputs.retire(reference)
                            write_results(directory, meta, rows)
        meta['status'] = 'completed' if all(r['execution_passed'] and 'error' not in r for r in rows) else 'completed_with_failures'
    except BaseException:
        meta['status'] = 'interrupted_or_failed'
        meta['error'] = traceback.format_exc()
        raise
    finally:
        meta['updated_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
        write_results(directory, meta, rows)
    if meta['status'] != 'completed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
