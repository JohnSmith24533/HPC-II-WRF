#!/usr/bin/env python3
"""Record each allocated node and optionally enforce an exact CPU/NUMA signature."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys


REQUIRED = ('Architecture:', 'Byte Order:', 'Model name:', 'CPU(s):',
            'Thread(s) per core:', 'Core(s) per socket:', 'Socket(s):',
            'NUMA node(s):', 'CPU max MHz:', 'L3 cache:')


def signature(cpu):
    fields = {row['field']: ' '.join(str(row['data']).split()) for row in cpu['lscpu']}
    if any(key not in fields for key in REQUIRED):
        raise ValueError('incomplete CPU/NUMA hardware report')
    keys = set(REQUIRED) | {key for key in fields if re.fullmatch(r'NUMA node\d+ CPU\(s\):', key)}
    return {key: fields[key] for key in sorted(keys)}


def differences(actual, expected):
    return {key: {'actual': actual.get(key), 'expected': expected.get(key)}
            for key in sorted(actual.keys() | expected.keys()) if actual.get(key) != expected.get(key)}


def reference_signature(document, case=None):
    if 'hardware_by_case' in document:
        if case not in document['hardware_by_case']:
            raise ValueError('selected hardware reference requires a known case')
        expected=document['hardware_by_case'][case]
    elif 'hardware_signature' in document:
        expected=document['hardware_signature']
    else:
        return signature(document['experiment']['lscpu'])
    if any(key not in expected for key in REQUIRED):
        raise ValueError('incomplete reference hardware signature')
    return expected


def audit_allocation(reference, output_dir, case=None):
    nodes=int(os.environ.get('SLURM_JOB_NUM_NODES','0'))
    if not os.environ.get('SLURM_JOB_ID') or nodes<1:
        raise RuntimeError('hardware audit requires an actual Slurm allocation')
    command=['srun','--mpi=none',f'--nodes={nodes}',f'--ntasks={nodes}',
             '--ntasks-per-node=1','--cpus-per-task=1','--cpu-bind=cores',
             sys.executable,str(Path(__file__).resolve()),'--reference',str(Path(reference).resolve()),
             '--output-dir',str(Path(output_dir).resolve())]
    if case is not None:
        command.extend(['--case',case])
    subprocess.run(command,check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, help='completed experiment results.json containing recorded lscpu')
    parser.add_argument('--case', help='case name when the reference is a selected baseline plan')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    cpu = json.loads(subprocess.check_output(['lscpu', '-J'], text=True, env={**os.environ, 'LC_ALL': 'C'}))
    actual = signature(cpu)
    report = {'host': socket.gethostname(), 'job_id': os.environ.get('SLURM_JOB_ID'),
              'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'lscpu': cpu, 'hardware_signature': actual, 'differences': {}, 'passed': True}
    if args.reference:
        raw = args.reference.read_bytes()
        document = json.loads(raw)
        expected = reference_signature(document,args.case)
        report.update(reference=str(args.reference), reference_sha256=hashlib.sha256(raw).hexdigest(),
                      expected_signature=expected, differences=differences(actual, expected))
        report['passed'] = not report['differences']
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / (report['host'] + '.json')).open('x') as stream:
        json.dump(report, stream, indent=2); stream.write('\n')
    print(json.dumps({'host': report['host'], 'NUMA nodes': actual['NUMA node(s):'],
                      'passed': report['passed'], 'differences': report['differences']}), flush=True)
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
