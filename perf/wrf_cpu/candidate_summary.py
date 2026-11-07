#!/usr/bin/env python3
"""Recompute all-five-case speedups from completed, strictly verified candidate groups."""
import argparse
import json
import math
from pathlib import Path
import statistics
import subprocess

import audit
import certify_scaled
import run
import verify


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--groups',nargs='+',type=Path,required=True)
    parser.add_argument('--selection',type=Path,default=run.ART/'progress/S006-winners.json')
    parser.add_argument('--reference-name',default='scaled-golden')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('preserve existing summary; choose a new output')
    selection=json.loads(args.selection.read_text())
    configs=certify_scaled.selected_configurations(selection)
    audit.audit(run.ART,args.reference_name)
    reference_sha=run.digest(run.ART/args.reference_name/'manifest.json')
    scores={};payload=None;provenance=None;jobs=[];hardware_counts={}
    for path in args.groups:
        data=json.loads(path.read_text());meta=data['experiment'];jobs.append(meta['job_id'])
        if meta['status']!='completed' or meta.get('error') or meta['reference_manifest_sha256']!=reference_sha or meta['selection_sha256']!=run.digest(args.selection):
            raise RuntimeError('incomplete or different candidate group: '+str(path))
        if provenance is not None and provenance!=meta['candidate_provenance']:raise RuntimeError('groups use different runtime policies')
        provenance=meta['candidate_provenance']
        candidate_payload=provenance['payload_sha256']
        if payload is not None and payload!=candidate_payload:raise RuntimeError('groups use different candidate payloads')
        payload=candidate_payload
        hardware_reports=list((path.parent/'hardware').glob('*.json'))
        if not hardware_reports or not all(json.loads(p.read_text()).get('passed') is True for p in hardware_reports):
            raise RuntimeError('missing or failed hardware audits')
        hardware_counts[meta['job_id']]=len(hardware_reports)
        for case in meta['cases']:
            if case in scores:raise RuntimeError('duplicate case group')
            rows=[r for r in data['runs'] if r['case']==case]
            tiers={tier:[r for r in rows if r['tier']==tier] for tier in ['single','short','full','restart']}
            if any(len(tiers[t])!=1 for t in ['single','short','restart']) or len(tiers['full'])!=meta['repetitions'] or meta['repetitions']<3:
                raise RuntimeError('incomplete candidate tier/repetition coverage')
            if (len({r['directory'] for r in tiers['full']})!=meta['repetitions']
                    or {r['repeat'] for r in tiers['full']}!=set(range(1,meta['repetitions']+1))):
                raise RuntimeError('duplicate or missing full repeats')
            threads=provenance.get('threads_by_case',{}).get(case,1)
            mpi_options=provenance.get('mpi_options_by_case',{}).get(case,configs[case]['mpi_options'])
            omp_tiles=[1,threads] if threads>1 else None
            times=[]
            for row in rows:
                directory=Path(row['directory']);trial=json.loads((directory/'run.json').read_text())
                checked=json.loads((directory/'check.json').read_text())
                if trial['case']!=case or trial['tier']!=row['tier'] or trial['label']!=row['label']:
                    raise RuntimeError('candidate row identifies a different run')
                if trial['exit_code']!=0 or not checked['passed'] or row.get('execution_passed') is not True or row.get('bitwise_passed') is not True:
                    raise RuntimeError('failed candidate execution')
                if trial['executable_sha256']!=payload[str(Path(trial['executable']).resolve())]:
                    raise RuntimeError('candidate executable provenance differs')
                for key in ['ranks','processor_grid']:
                    if trial.get(key)!=configs[case][key]:raise RuntimeError('candidate configuration differs: '+key)
                if trial.get('mpi_options')!=mpi_options or trial.get('threads',1)!=threads or trial.get('omp_tiles')!=omp_tiles:
                    raise RuntimeError('candidate parallel configuration differs from its declared policy')
                compared=json.loads((directory/('restart-compare.json' if row['tier']=='restart' else 'candidate-compare.json')).read_text())
                if compared['passed'] is not True or compared['mode']!='bitwise' or compared['errors'] or not compared['metrics'] or not all(m['passed'] for m in compared['metrics']):
                    raise RuntimeError('candidate numerical gate did not pass')
                if meta['candidate_provenance'].get('compression_report_prefix'):
                    reports=row.get('compression_reports_sha256',{})
                    if not reports or row.get('compression_fast_calls',0)<=0:
                        raise RuntimeError('missing proof of compression backend use')
                    for file,expected in reports.items():
                        if run.digest(Path(file))!=expected:raise RuntimeError('compression-use evidence changed')
                journal=directory/'retired-outputs.json'
                if journal.exists():
                    for name,expected in json.loads(journal.read_text())['retained_evidence_sha256'].items():
                        if run.digest(directory/name)!=expected:raise RuntimeError('retained numerical evidence changed')
                if row['tier']=='full':
                    steps=run.CASES[case]['full_seconds']//run.CASES[case]['dt']
                    if checked['steps']!=steps or trial['step_timing_seconds']['count']!=steps:
                        raise RuntimeError('incomplete timestep coverage')
                    value=trial['wall_seconds']/steps
                    if not math.isfinite(value) or value<=0 or value!=row['wall_seconds_per_timestep']:
                        raise RuntimeError('invalid candidate wall time')
                    times.append(value)
            median=statistics.median(times);baseline=configs[case]['wall_seconds_per_timestep']
            if median!=data['scores'][case]['median_wall_seconds_per_timestep']:
                raise RuntimeError('reported candidate median differs from actual trials')
            scores[case]={'repetitions':len(times),'baseline_wall_seconds_per_timestep':baseline,
                          'candidate_wall_seconds_per_timestep':median,'speedup':baseline/median,'ranks':configs[case]['ranks'],'threads':threads,
                          'omp_tiles':omp_tiles,'mpi_options':mpi_options,
                          'group':str(path),'group_sha256':run.digest(path)}
    if set(scores)!=set(run.CASES):raise RuntimeError('all five original cases are required')
    for file,expected in payload.items():
        if run.digest(Path(file))!=expected:raise RuntimeError('candidate payload changed')
    accounting=subprocess.check_output(['sacct','-X','-j',','.join(jobs),'-n','-P','--format=JobIDRaw,State,ExitCode,NNodes'],text=True)
    observed={r.split('|')[0]:r.split('|')[1:4] for r in accounting.splitlines()}
    if any(observed.get(job)!=['COMPLETED','0:0',str(hardware_counts[job])] for job in jobs):
        raise RuntimeError('candidate jobs lack successful terminal accounting')
    geometric=math.exp(sum(math.log(v['speedup']) for v in scores.values())/len(scores))
    result={'all_five_cases_verified':True,'reference_manifest_sha256':reference_sha,
            'selection_sha256':run.digest(args.selection),'payload_sha256':payload,'scores':scores,
            'geometric_mean_speedup':geometric,'target':5,'meets_numeric_target':geometric>=5,
            'primary_metric':'median full WRF wall-clock seconds / verified completed timesteps'}
    verify.save(args.output,result)
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
