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
    reference=Path(reference).resolve()
    raw=reference.read_bytes()
    expected=reference_signature(json.loads(raw),case)
    reference_sha256=hashlib.sha256(raw).hexdigest()
    nodelist=os.environ.get('SLURM_JOB_NODELIST',os.environ.get('SLURM_NODELIST'))
    if not nodelist:
        raise RuntimeError('allocated node list is required')
    allocated=subprocess.check_output(['scontrol','show','hostnames',nodelist],text=True).splitlines()
    if len(allocated)!=nodes or len(set(allocated))!=nodes:
        raise RuntimeError('allocated node list is incomplete or duplicated')
    command=['srun','--mpi=none','--nodes=1','--ntasks=1',
             '--ntasks-per-node=1','--cpus-per-task=1','--cpu-bind=cores',
             sys.executable,str(Path(__file__).resolve()),'--reference',str(reference),
             '--stdout']
    if case is not None:
        command.extend(['--case',case])
    reports=[]
    # Slurm can interleave long stdout records from simultaneous tasks. Probe
    # each allocated node in turn rather than inventing a framing protocol.
    for host in allocated:
        completed=subprocess.run([command[0],'--nodelist='+host,*command[1:]],stdout=subprocess.PIPE,text=True,check=True)
        try:
            report=json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError('unreadable hardware report from '+host) from exc
        if report.get('host')!=host:
            raise RuntimeError('hardware report does not identify the requested allocated node')
        reports.append(report)
    hosts=[report['host'] for report in reports]
    if (len(reports)!=nodes or len(set(hosts))!=nodes or
            any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*',host) for host in hosts)):
        raise RuntimeError('hardware reports must cover every distinct allocated node')
    for report in reports:
        actual=signature(report['lscpu'])
        if (report.get('job_id')!=os.environ['SLURM_JOB_ID'] or
                report.get('reference')!=str(reference) or
                report.get('reference_sha256')!=reference_sha256 or
                report.get('expected_signature')!=expected or
                report.get('hardware_signature')!=actual or
                report.get('passed') is not True or report.get('differences') or
                differences(actual,expected)):
            raise RuntimeError('hardware report provenance or CPU/NUMA signature differs')
    # Write from one client only. Tiny per-node files can otherwise reserve
    # substantial distributed filesystem quota before a model has even started.
    output_dir=Path(output_dir)
    output_dir.mkdir(parents=True,exist_ok=True)
    for report in reports:
        with (output_dir/(report['host']+'.json')).open('x') as stream:
            json.dump(report,stream,indent=2);stream.write('\n')
        print(json.dumps({'host':report['host'],
                          'NUMA nodes':report['hardware_signature']['NUMA node(s):'],
                          'passed':True,'differences':{}}),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, help='completed experiment results.json containing recorded lscpu')
    parser.add_argument('--case', help='case name when the reference is a selected baseline plan')
    output=parser.add_mutually_exclusive_group(required=True)
    output.add_argument('--output-dir', type=Path)
    output.add_argument('--stdout',action='store_true',help='return the complete report without writing on this node')
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
    if args.stdout:
        print(json.dumps(report),flush=True)
    else:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        with (args.output_dir / (report['host'] + '.json')).open('x') as stream:
            json.dump(report, stream, indent=2); stream.write('\n')
        print(json.dumps({'host': report['host'], 'NUMA nodes': actual['NUMA node(s):'],
                          'passed': report['passed'], 'differences': report['differences']}), flush=True)
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
