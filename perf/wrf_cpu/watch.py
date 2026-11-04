#!/usr/bin/env python3
"""Watch an existing baseline job; submit finalize only after scheduler success."""
import argparse
from pathlib import Path
import subprocess
import time
import sys

ROOT=Path(__file__).resolve().parents[2]


def watch(job):
    phase='baseline'
    while True:
        q=subprocess.run(['squeue','-h','-j',job,'-o','%T|%M|%R'],capture_output=True,text=True)
        if q.returncode:
            print('Scheduler query failed transiently; retaining job '+job,flush=True)
            time.sleep(20)
            continue
        if q.stdout.strip():
            line=phase+' '+job+' '+q.stdout.strip()
            label='baseline' if phase=='baseline' else 'replay'
            active=[p for p in (ROOT/'.wrf-cpu/runs'/label).glob('*/*/run.json') if not (p.parent/'check.json').exists()]
            if active:
                current=max(active,key=lambda p:p.stat().st_mtime).parent
                log=current/'rsl.out.0000'
                if log.exists():
                    with log.open('rb') as f:
                        f.seek(max(0,log.stat().st_size-700))
                        lines=f.read().decode(errors='replace').splitlines()
                    timing=[v for v in lines if 'Timing for main:' in v]
                    line+=' '+str(current.relative_to(ROOT/'.wrf-cpu/runs'))+' '+(timing[-1] if timing else '')
            print(line,flush=True)
            time.sleep(20)
            continue
        a=subprocess.run(['sacct','-n','-X','-j',job,'--format=State,ExitCode','-P'],capture_output=True,text=True)
        if a.returncode or not a.stdout.strip():
            print('Accounting not ready; retaining job '+job,flush=True)
            time.sleep(20)
            continue
        terminal=a.stdout.strip().splitlines()[0]
        print(phase+' '+job+' terminal '+terminal,flush=True)
        if not terminal.startswith('COMPLETED|0:0'):
            return 1
        if phase=='finalize':
            print('Jobs completed. Inspect published artifacts for the final completion audit.',flush=True)
            return 0
        s=subprocess.run(['sbatch','--parsable','--output=.wrf-cpu/logs/finalize-%j.log','perf/wrf_cpu/finalize.slurm'],cwd=ROOT,capture_output=True,text=True)
        if s.returncode:
            print(s.stderr,flush=True)
            return s.returncode
        job=s.stdout.strip().split(';')[0]
        (ROOT/'.wrf-cpu/logs/finalize-job-id.txt').write_text(job+'\n')
        phase='finalize'
        print('Submitted independent replay/publication job '+job,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline_job')
    args=parser.parse_args()
    if not args.baseline_job.isdigit():
        parser.error('baseline_job must be numeric')
    sys.exit(watch(args.baseline_job))
