#!/usr/bin/env python3
"""Certify the original build at configurations selected by independent repeats."""
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
import publish
import run
import verify
import hardware


def selected_configurations(selection):
    if set(selection['cases']) != set(run.CASES) or selection['top_per_case'] != 1:
        raise ValueError('certification requires one independently selected configuration for all five cases')
    for evidence in selection['experiments'].values():
        if run.digest(Path(evidence['path'])) != evidence['sha256']:
            raise ValueError('repeat experiment changed after winner selection')
        experiment = json.loads(Path(evidence['path']).read_text())
        if experiment['experiment']['status'] != 'completed':
            raise ValueError('repeat experiment did not complete successfully')
    configurations = {}
    for case, values in selection['cases'].items():
        config, = values
        trials = [Path(path) for path in config['source_trials']]
        if len(set(trials)) < 3 or len(trials) != config['measured_repetitions']:
            raise ValueError('at least three distinct independent full runs are required')
        expected_steps = run.CASES[case]['full_seconds'] // run.CASES[case]['dt']
        times = []
        first_repeats = 0
        for trial in trials:
            meta = json.loads((trial / 'run.json').read_text())
            check = json.loads((trial / 'check.json').read_text())
            if (meta['case'] != case or meta['tier'] != 'full' or meta['exit_code'] != 0
                    or not check['passed'] or check['steps'] != expected_steps
                    or meta['step_timing_seconds']['count'] != expected_steps
                    or meta['ranks'] != config['ranks']
                    or meta.get('processor_grid') != config['processor_grid']
                    or meta.get('mpi_options', []) != config['mpi_options']):
                raise ValueError('repeat trial configuration or completion differs from selection')
            comparison = trial / 'repeat-compare.json'
            if comparison.exists():
                compared = json.loads(comparison.read_text())
                if not compared['passed'] or compared['mode'] != 'bitwise':
                    raise ValueError('independent repeat did not pass bitwise comparison')
            else:
                first_repeats += 1
                if not re.search(r'-r01-p\d+$', meta['label']):
                    raise ValueError('missing independent repeat comparison')
            times.append(meta['wall_seconds'] / expected_steps)
        if first_repeats != 1 or statistics.median(times) != config['wall_seconds_per_timestep']:
            raise ValueError('selected score differs from the independent-repeat median')
        configurations[case] = config
    return configurations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--label', required=True)
    parser.add_argument('--cases', nargs='+', choices=run.CASES, required=True)
    parser.add_argument('--publish', action='store_true', help='publish scaled-golden after all five cases are certified')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.label) or not os.environ.get('SLURM_JOB_ID'):
        parser.error('use a unique safe label inside a Slurm allocation')
    if len(args.cases) != len(set(args.cases)):
        parser.error('duplicate cases')
    ideal = any(case != 'conus12' for case in args.cases)
    if ideal and ('conus12' in args.cases or int(os.environ.get('SLURM_JOB_NUM_NODES', '0')) != 1):
        parser.error('certify ideal cases in a separate single-node allocation to retain socket placement')
    selection = json.loads(args.selection.read_text())
    configurations = selected_configurations(selection)
    if max(configurations[c]['ranks'] for c in args.cases) > int(os.environ.get('SLURM_NTASKS', '0')):
        parser.error('selected ranks exceed this allocation')
    directory = run.ART / 'experiments' / args.label / ('ideal' if ideal else 'real')
    directory.mkdir(parents=True, exist_ok=False)
    shutil.copy2(args.selection, directory / 'selection.json')
    shutil.copy2(__file__, directory / 'certify-harness.py')
    meta = {'label': args.label, 'status': 'initializing', 'cases': args.cases,
            'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'job_id': os.environ['SLURM_JOB_ID'], 'host': os.uname().nodename,
            'selection_sha256': run.digest(args.selection), 'configurations': configurations,
            'lscpu': json.loads(subprocess.check_output(['lscpu', '-J'], text=True)),
            'note': 'certification timings do not replace the independently selected repeat medians'}
    rows = []

    def save():
        meta['updated_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
        verify.save(directory / 'results.json', {'experiment': meta, 'runs': rows})

    save()
    try:
        signatures=[hardware.reference_signature(selection,case) for case in args.cases]
        if any(hardware.differences(value,signatures[0]) for value in signatures[1:]):
            raise RuntimeError('certification allocation mixes incompatible case hardware groups')
        hardware.audit_allocation(args.selection,directory/'hardware',case=args.cases[0])
        audit.audit(run.ART)
        expected = {line.split()[1]: line.split()[0] for line in
                    (run.ART / 'baseline/executables.sha256').read_text().splitlines()}
        for kind in ('ideal', 'real'):
            executable = run.ART / ('install-' + kind) / 'bin/wrf'
            if run.digest(executable) != expected[str(executable)]:
                raise RuntimeError('certification requires the archived original executable')
        meta['status'] = 'running'
        save()
        for case in args.cases:
            config = configurations[case]
            baseline_label = args.label + '-baseline'
            for label in (baseline_label, args.label + '-replay'):
                for tier in ('single', 'short', 'full', 'restart'):
                    dest = run.run_case(case, tier, label, config['ranks'],
                                        mpi_options=config['mpi_options'], processor_grid=config['processor_grid'])
                    if label != baseline_label and tier != 'restart':
                        compared = verify.compare(dest, run.ART / 'runs' / baseline_label / case / tier)
                        verify.save(dest / 'replay-compare.json', json.loads(json.dumps(compared, default=lambda v: v.item())))
                        if not compared['passed']:
                            raise RuntimeError('independent certification replay differs bitwise')
                    rows.append({'case': case, 'tier': tier, 'label': label,
                                 'directory': str(dest), 'execution_passed': True})
                    save()
        if args.publish:
            publish.publish(args.label + '-baseline', args.label + '-replay', 'scaled-golden')
            audit.audit(run.ART, 'scaled-golden')
            meta['published_reference'] = 'scaled-golden'
        meta['status'] = 'completed'
    except BaseException:
        meta['status'] = 'interrupted_or_failed'
        meta['error'] = traceback.format_exc()
        raise
    finally:
        save()
    print(json.dumps({'label': args.label, 'cases': args.cases, 'status': meta['status']}), flush=True)


if __name__ == '__main__':
    main()
