#!/usr/bin/env python3
"""Retire verified scaling/candidate scratch arrays with durable hash journals."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess

import run


def retire(directory, keep_history=False):
    directory = Path(directory).resolve()
    meta = json.loads((directory / 'run.json').read_text())
    expected = (run.ART / 'runs' / meta['label'] / meta['case'] / meta['tier']).resolve()
    candidate = bool(re.fullmatch(r'C\d{3}-[A-Za-z0-9_-]+-r\d+-p\d+', meta['label']))
    scratch = candidate or re.fullmatch(r'S\d{3}[a-z]?-[A-Za-z0-9_-]+-r\d+-p\d+', meta['label'])
    if (directory != expected or not scratch
            or meta['tier'] not in ('short', 'full') or meta['exit_code'] != 0):
        raise ValueError('only completed scaling or candidate scratch runs may be retired')
    if not json.loads((directory / 'check.json').read_text())['passed']:
        raise ValueError('retain failed execution evidence')
    comparison_name = 'candidate-compare.json' if candidate else 'cross-rank-compare.json'
    compared = json.loads((directory / comparison_name).read_text())
    if compared['mode'] != 'bitwise' or not compared['metrics']:
        raise ValueError('complete numerical comparison evidence is required')
    if candidate and (compared.get('passed') is not True or compared.get('errors')
                      or not all(row.get('passed') is True for row in compared['metrics'])):
        raise ValueError('retain failed candidate comparison evidence')
    return _retire_arrays(directory, comparison_name, keep_history=keep_history)


def _retire_arrays(directory, comparison_name, keep_history=False, include_checkpoints=True, provenance=None,
                   history_before=None):
    if history_before is not None:
        dt.datetime.strptime(history_before, '%Y-%m-%d_%H:%M:%S')
        if keep_history or include_checkpoints:
            raise ValueError('prefix retirement must retain all checkpoints and the later history')
    journal_path = directory / 'retired-outputs.json'
    journal = json.loads(journal_path.read_text()) if journal_path.exists() else {
        'purpose': 'bounded verified scratch storage; raw arrays are reproducible from retained inputs/build/namelist',
        'directory': str(directory), 'files': {},
        'retained_evidence_sha256': {name: run.digest(directory / name) for name in
                                   ('run.json', 'check.json', comparison_name, 'namelist.input')}}
    if provenance:
        journal['diagnostic_provenance'] = provenance
    paths = sorted(directory.glob('wrfrst_d01_*')) if include_checkpoints else []
    if not keep_history:
        histories = sorted(directory.glob('wrfout_d01_*'))
        if history_before is not None:
            selected = []
            for path in histories:
                if path.is_symlink() or not path.is_file():
                    raise ValueError('refuse non-regular output: '+str(path))
                with run.nc.Dataset(path) as data:
                    times = run.nc.chartostring(data['Times'][:]).tolist()
                if not times:
                    raise ValueError('history has no timestamps: '+str(path))
                for stamp in times:
                    dt.datetime.strptime(stamp, '%Y-%m-%d_%H:%M:%S')
                if all(stamp < history_before for stamp in times):
                    selected.append(path)
            histories = selected
            journal['history_prefix_retirement_before'] = history_before
        paths += histories
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError('refuse non-regular output: ' + str(path))
        entry = {'bytes': path.stat().st_size, 'sha256': run.digest(path), 'removed': False}
        previous = journal['files'].get(path.name)
        if previous and (previous['sha256'] != entry['sha256'] or previous['bytes'] != entry['bytes']):
            raise ValueError('output changed since retirement journal was created')
        journal['files'][path.name] = entry

    def save():
        journal['updated_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
        temporary = journal_path.with_suffix('.tmp')
        with temporary.open('w') as stream:
            json.dump(journal, stream, indent=2); stream.write('\n')
            stream.flush(); os.fsync(stream.fileno())
        temporary.replace(journal_path)
        descriptor = os.open(journal_path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    # A durable exact-content journal precedes any deletion. It remains recoverable
    # if interrupted between unlinking an output and updating its removed flag.
    save()
    freed = 0
    for path in paths:
        path.unlink()
        journal['files'][path.name]['removed'] = True
        freed += journal['files'][path.name]['bytes']
    save()
    return freed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', required=True)
    args = parser.parse_args()
    data = json.loads((run.ART / 'experiments' / args.experiment / 'results.json').read_text())
    job = data['experiment']['job_id']
    accounting = subprocess.check_output(['sacct', '-X', '-j', job, '-n', '-P',
                                         '--format=JobIDRaw,State'], text=True)
    states = [row.split('|')[1].split()[0].rstrip('+') for row in accounting.splitlines()
              if row.split('|')[0] == job]
    if len(states) != 1 or states[0] not in ('COMPLETED', 'FAILED', 'CANCELLED', 'TIMEOUT', 'OUT_OF_MEMORY'):
        raise RuntimeError('manual retirement requires an authoritative terminal Slurm job')
    freed = 0
    for row in data['runs']:
        if row.get('execution_passed') and 'error' not in row:
            # Preserve the fixed real-data verifier equivalence fixture.
            if row['label'] == 'S001-scaling-screen-r01-p112' and row['case'] == 'conus12':
                continue
            freed += retire(row['directory'])
    print(json.dumps({'experiment': args.experiment, 'bytes_retired': freed, 'source_job_state': states[0]}))


if __name__ == '__main__':
    main()
