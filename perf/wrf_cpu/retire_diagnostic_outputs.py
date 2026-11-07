#!/usr/bin/env python3
"""Retire only a terminal, fully bitwise-verified diagnostic's scratch arrays."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import subprocess

import retire_scaling_outputs
import run


def retire_group(group_path):
    group_path = Path(group_path).resolve()
    if not group_path.is_relative_to((run.ART / 'experiments').resolve()):
        raise ValueError('diagnostic evidence must be inside the experiment tree')
    data = json.loads(group_path.read_text())
    if (data.get('status') != 'completed' or data.get('error')
            or data.get('diagnostic_only') is not True
            or data.get('timings_excluded') is not True
            or data.get('all_executed_checks_passed') is not True):
        raise ValueError('retain incomplete or failed diagnostic evidence')
    match = re.fullmatch(r'(D\d{3})-[A-Za-z0-9_-]+', data.get('label', ''))
    if not match or not data.get('runs'):
        raise ValueError('a complete named diagnostic group is required')
    for key in ('payload_sha256', 'harness_sha256'):
        if not data.get(key):
            raise ValueError('missing diagnostic '+key)
        for file, expected in data[key].items():
            if not Path(file).is_absolute() or run.digest(Path(file)) != expected:
                raise ValueError('diagnostic payload or harness changed')
    job = str(data['job_id'])
    accounting = subprocess.check_output(
        ['sacct', '-X', '-j', job, '-n', '-P', '--format=JobIDRaw,State,ExitCode'], text=True)
    observed = [line.split('|')[1:3] for line in accounting.splitlines()
                if line.split('|')[0] == job]
    if observed != [['COMPLETED', '0:0']]:
        raise ValueError('diagnostic job must have successful terminal accounting')
    policies, prepared, seen = defaultdict(list), [], set()
    for row in data['runs']:
        directory = Path(row['directory']).resolve()
        meta = json.loads((directory / 'run.json').read_text())
        expected = (run.ART / 'runs' / meta['label'] / meta['case'] / meta['tier']).resolve()
        if (directory != expected or directory in seen
                or not meta['label'].startswith(match[1]+'-')
                or not re.fullmatch(r'D\d{3}-[A-Za-z0-9_-]+', meta['label'])
                or meta['case'] != row['case'] or meta['tier'] != row['tier']
                or meta.get('job_id') != job or row.get('passed') is not True
                or meta.get('exit_code') != 0):
            raise ValueError('diagnostic row/configuration is incomplete or non-scratch')
        seen.add(directory)
        if not json.loads((directory / 'check.json').read_text()).get('passed'):
            raise ValueError('retain failed execution evidence')
        name = 'restart-compare.json' if meta['tier'] == 'restart' else 'diagnostic-compare.json'
        report = json.loads((directory / name).read_text())
        if (report.get('mode') != 'bitwise' or report.get('passed') is not True
                or report.get('errors') or not report.get('metrics')
                or not all(metric.get('passed') is True for metric in report['metrics'])):
            raise ValueError('retain failed scientific comparison evidence')
        files = list(directory.glob('wrfout_d01_*'))
        # Restart's wrfrst symlink is an input, retained as provenance.
        if meta['tier'] != 'restart':
            files += list(directory.glob('wrfrst_d01_*'))
        if any(file.is_symlink() or not file.is_file() for file in files):
            raise ValueError('refuse non-regular diagnostic output')
        policies[(meta['case'], meta['label'])].append(meta['tier'])
        prepared.append((directory, name, meta['tier'] != 'restart'))
    required = {'single', 'short', 'full', 'restart'}
    if any(len(tiers) != 4 or set(tiers) != required for tiers in policies.values()):
        raise ValueError('all four scientific tiers and their restart are required')
    provenance = {'group': str(group_path), 'group_sha256': run.digest(group_path),
                  'job_id': job, 'accounting': accounting,
                  'payload_sha256': data['payload_sha256'],
                  'harness_sha256': data['harness_sha256']}
    # Validate the whole group before removing any output. The shared helper
    # durably journals exact file hashes before unlinking each directory's data.
    return sum(retire_scaling_outputs._retire_arrays(
        directory, name, include_checkpoints=checkpoints, provenance=provenance)
        for directory, name, checkpoints in prepared)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({'group': str(args.group), 'bytes_retired': retire_group(args.group)}))


if __name__ == '__main__':
    main()
