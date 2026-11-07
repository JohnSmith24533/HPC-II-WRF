#!/usr/bin/env python3
"""Submit measured scaling stages serially, preserving live job handles on errors."""
import argparse
import datetime as dt
import json
import math
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
TERMINAL = {'COMPLETED', 'FAILED', 'CANCELLED', 'TIMEOUT', 'OUT_OF_MEMORY',
            'NODE_FAIL', 'PREEMPTED', 'BOOT_FAIL', 'DEADLINE', 'REVOKED'}


def evidence_complete(evidence, profile=False):
    if not profile:
        return evidence.get('experiment',{}).get('status')=='completed' and bool(evidence.get('runs'))
    samples=evidence.get('samples_by_rank',{})
    ranks=evidence.get('sampled_ranks',[])
    reports=evidence.get('reports',[])
    return (evidence.get('status')=='completed' and evidence.get('profile_only') is True
            and evidence.get('numerical_comparison_passed') is True and bool(ranks)
            and set(samples)=={str(rank) for rank in ranks}
            and all(isinstance(count,(int,float)) and math.isfinite(count) and count>=100 for count in samples.values())
            and len(reports)==2*len(ranks) and all(Path(path).is_file() for path in reports))


def job_state(job):
    """An absent accounting row or query timeout is not evidence of completion."""
    result = subprocess.run(['sacct', '-X', '-j', job, '-n', '-P',
                             '--format=JobIDRaw,State,ExitCode'],
                            cwd=ROOT, capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    for line in result.stdout.splitlines():
        fields = line.split('|')
        if len(fields) >= 3 and fields[0] == job:
            return fields[1].split()[0].rstrip('+'), fields[2]
    return None, None


def persist(path, data):
    data['updated_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2) + '\n')
    tmp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=Path(__file__).with_name('scaling-campaign.json'))
    parser.add_argument('--state', type=Path, default=ROOT / '.wrf-cpu/scaling-campaign-state.json')
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    if args.state.exists():
        state = json.loads(args.state.read_text())
        if state['plan'] != plan:
            raise RuntimeError('campaign plan changed; keep the old state and use a new state path')
        if state.get('status') == 'ambiguous_submission':
            raise RuntimeError('previous submission is ambiguous; recover its actual Slurm job before resuming')
    else:
        state = {'plan': plan, 'status': 'running', 'stages': {}}
        persist(args.state, state)
    # Only one controller may own this campaign's submission state.
    import fcntl
    with args.state.with_suffix('.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for stage in plan:
            record = state['stages'].setdefault(stage['name'], {})
            if record.get('status') == 'verified_complete':
                continue
            if 'job' not in record:
                if 'existing_job' in stage:
                    record['job'] = stage['existing_job']
                else:
                    command = ['sbatch', '--parsable', *stage['sbatch']]
                    submitted = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
                    record['submission'] = {'command': command, 'exit_code': submitted.returncode,
                                            'stdout': submitted.stdout, 'stderr': submitted.stderr}
                    if submitted.returncode:
                        state['status'] = 'submission_failed'
                        persist(args.state, state)
                        raise RuntimeError('submission failed; no job handle discarded: ' + submitted.stderr)
                    job = submitted.stdout.strip().split(';')[0]
                    if not job.isdigit():
                        state['status'] = 'ambiguous_submission'
                        persist(args.state, state)
                        raise RuntimeError('cannot parse job handle; inspect scheduler before retrying')
                    record['job'] = job
                record['status'] = 'submitted'
                persist(args.state, state)
                print(json.dumps({'stage': stage['name'], **record}), flush=True)
            previous = None
            while True:
                try:
                    observed, code = job_state(record['job'])
                except (RuntimeError, subprocess.TimeoutExpired) as exc:
                    record['last_query_error'] = str(exc)
                    persist(args.state, state)
                    time.sleep(20)
                    continue
                record.update(observed_state=observed, observed_exit_code=code)
                persist(args.state, state)
                if observed != previous:
                    print(json.dumps({'stage': stage['name'], 'job': record['job'], 'state': observed, 'exit_code': code}), flush=True)
                    previous = observed
                if observed in TERMINAL:
                    if observed != 'COMPLETED' or code != '0:0':
                        record['status'] = 'failed'
                        state['status'] = 'stage_failed'
                        persist(args.state, state)
                        raise RuntimeError('stage failed; inspect preserved job ' + record['job'])
                    evidence = json.loads((ROOT / '.wrf-cpu' / stage['result']).read_text())
                    if not evidence_complete(evidence,stage.get('profile_evidence',False)):
                        record['status'] = 'evidence_failed'
                        state['status'] = 'stage_failed'
                        persist(args.state, state)
                        raise RuntimeError('successful job lacks completed experiment evidence')
                    record['status'] = 'verified_complete'
                    persist(args.state, state)
                    break
                time.sleep(20)
        state['status'] = 'campaign_complete'
        persist(args.state, state)
        print(json.dumps({'status': 'campaign_complete', 'scope': [stage['name'] for stage in plan],
                          'overall_optimization_goal': 'not evaluated by this controller'}), flush=True)


if __name__ == '__main__':
    main()
