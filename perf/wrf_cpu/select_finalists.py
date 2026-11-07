#!/usr/bin/env python3
"""Select repeated-timing candidates from complete, verified full scaling sweeps."""
import argparse
import datetime as dt
import json
import math
from pathlib import Path
import shutil
import statistics

import run
import verify
import hardware


def validate_cross_rank(report):
    """Only numerical differences may be attributed to a changed decomposition."""
    if report.get('mode')!='bitwise' or not report.get('metrics'):
        raise ValueError('complete bitwise cross-rank evidence is required')
    allowed=set()
    for row in report['metrics']:
        if not row['passed']:
            allowed.update((f"{row['time']}: {row['variable']} differs",
                            f"{row['time']}: derived {row['variable']} differs"))
    if any(error not in allowed for error in report['errors']):
        raise ValueError('cross-rank comparison has structural, time, or nonnumeric differences')


def choose(rows, expected_cases, top, near_best_fraction=0.):
    if top<1:
        raise ValueError('top must be positive')
    if not math.isfinite(near_best_fraction) or near_best_fraction<0:
        raise ValueError('near-best fraction must be finite and nonnegative')
    groups={}
    for row in rows:
        if row.get('tier')!='full' or not row.get('execution_passed') or 'error' in row:
            raise ValueError('finalist inputs must be successful complete full runs')
        if not math.isfinite(row['wall_seconds_per_timestep']) or row['wall_seconds_per_timestep']<=0:
            raise ValueError('timing must be finite and positive')
        key=(row['case'],row['ranks'],tuple(row.get('processor_grid') or ()),tuple(row.get('mpi_options',())))
        groups.setdefault(key,[]).append(row)
    if {key[0] for key in groups}!=set(expected_cases):
        raise ValueError('all five requested cases need complete full-run evidence')
    candidates={case:[] for case in expected_cases}
    for (case,ranks,grid,mpi),values in groups.items():
        times=[r['wall_seconds_per_timestep'] for r in values]
        candidates[case].append({'ranks':ranks,'processor_grid':list(grid) if grid else None,
            'mpi_options':list(mpi),'measured_repetitions':len(values),
            'wall_seconds_per_timestep':statistics.median(times),
            'min_seconds_per_timestep':min(times),'max_seconds_per_timestep':max(times),
            'source_trials':[r['directory'] for r in values]})
    selected={}
    for case,values in candidates.items():
        ordered=sorted(values,key=lambda r:(r['wall_seconds_per_timestep'],r['ranks'],str(r['processor_grid'])))
        count=top
        if near_best_fraction>0:
            ceiling=ordered[0]['wall_seconds_per_timestep']*(1+near_best_fraction)
            count=max(top,sum(value['wall_seconds_per_timestep']<=ceiling for value in ordered))
        selected[case]=ordered[:count]
    return selected


def repeat_family(case, config):
    options=config['mpi_options']
    mapping=options[3] if len(options)==5 else None
    if mapping not in ('core','package:SPAN') or options!=['--bind-to','core','--map-by',mapping,'--report-bindings']:
        raise ValueError('repeat selection requires a supported explicit core binding/mapping')
    base='ideal' if case!='conus12' else ('real-explicit' if config['processor_grid'] else 'real-auto')
    return base+('-core' if mapping=='core' else '-spread'),mapping


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiments',nargs='+',default=['S003q-ideal-core-matched','S003p-ideal-spread','S004a-verified-prefix','S004c-conus-full-recovery','S004b-conus-full'])
    parser.add_argument('--top',type=int,default=3)
    parser.add_argument('--near-best-fraction',type=float,default=0.,help='also retain preliminary candidates within this fraction of the fastest median; leave zero for final winner selection')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():
        parser.error('finalist plan already exists; preserve prior selection evidence')
    rows=[]
    evidence={}
    hardware_by_case={}
    expected_hashes={line.split()[1]:line.split()[0] for line in
                     (run.ART/'baseline/executables.sha256').read_text().splitlines()}
    for label in args.experiments:
        path=run.ART/'experiments'/label/'results.json'
        data=json.loads(path.read_text())
        if data['experiment']['status']!='completed':
            raise RuntimeError(f'full scaling experiment is not complete: {label}')
        evidence[label]={'path':str(path),'sha256':run.digest(path)}
        signature=hardware.signature(data['experiment']['lscpu'])
        for row in data['runs']:
            case=row['case']; cfg=run.CASES[case]; directory=Path(row['directory'])
            if case in hardware_by_case and hardware.differences(signature,hardware_by_case[case]):
                raise RuntimeError(f'CPU/NUMA topology differs between scaling configurations: {case}/{label}')
            hardware_by_case[case]=signature
            meta=json.loads((directory/'run.json').read_text())
            if meta.get('hardware_signature') is not None and hardware.differences(meta['hardware_signature'],signature):
                raise RuntimeError(f'run and experiment CPU/NUMA signatures differ: {directory}')
            checked=json.loads((directory/'check.json').read_text())
            validate_cross_rank(json.loads((directory/'cross-rank-compare.json').read_text()))
            expected_steps=cfg['full_seconds']//cfg['dt']
            elapsed=(dt.datetime.strptime(meta['end'],verify.STAMP)-dt.datetime.strptime(meta['start'],verify.STAMP)).total_seconds()
            executable=run.ART/('install-real' if case=='conus12' else 'install-ideal')/'bin/wrf'
            if (meta['tier']!='full' or row['tier']!='full' or elapsed!=cfg['full_seconds']
                or meta['dt']!=cfg['dt'] or meta['grid']!=cfg['grid'] or meta['expected_physics']!=cfg['physics'] or meta['exit_code']!=0
                or not checked['passed'] or checked['steps']!=expected_steps
                or meta['step_timing_seconds']['count']!=expected_steps):
                raise RuntimeError(f'incomplete/full-case mismatch: {directory}')
            if (meta['executable_sha256']!=expected_hashes[str(executable)]
                or meta['frozen_inputs_sha256']!=run.digest(run.ART/'inputs'/case/'inputs.json')
                or meta['namelist_sha256']!=run.digest(directory/'namelist.input')
                or meta['ranks']!=row['ranks'] or meta.get('processor_grid')!=row.get('processor_grid')):
                raise RuntimeError(f'provenance mismatch: {directory}')
            normalized=meta['wall_seconds']/checked['steps']
            if normalized!=row['wall_seconds_per_timestep']:
                raise RuntimeError(f'wall-time normalization differs from actual completed steps: {directory}')
            rows.append({**row,'mpi_options':meta.get('mpi_options',[])})
    finalists=choose(rows,list(run.CASES),args.top,args.near_best_fraction)
    matrices={}
    placements={}
    for case,values in finalists.items():
        for value in values:
            family,mapping=repeat_family(case,value)
            placements[family]=mapping
            entry={'ranks':value['ranks']}
            if value['processor_grid']:
                entry['processor_grid']=value['processor_grid']
            bucket=matrices.setdefault(family,{}).setdefault(case,[])
            if any(c['ranks']==entry['ranks'] for c in bucket):
                raise RuntimeError('multiple explicit layouts at the same rank need separate repeat experiment labels')
            bucket.append(entry)
    matrix_paths={family:str(args.output.with_name(args.output.stem+'-'+family+'-matrix.json')) for family in matrices}
    snapshot=args.output.with_suffix('.selector.py')
    for path in [snapshot,*map(Path,matrix_paths.values())]:
        if path.exists():
            raise RuntimeError('selection artifact already exists: '+str(path))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    for family,matrix in matrices.items():
        verify.save(matrix_paths[family],matrix)
    shutil.copy2(__file__,snapshot)
    result={'scope':'preliminary finalists for independent timing repeats; not a certified baseline',
            'created_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'experiments':evidence,
            'primary_metric':'complete WRF wall-clock seconds / verified completed timesteps',
            'required_case_count':len(run.CASES),'top_per_case':args.top,
            'near_best_fraction':args.near_best_fraction,'cases':finalists,'repeat_matrices':matrix_paths,
            'hardware_by_case':hardware_by_case,
            'selector_sha256':run.digest(snapshot),'repeat_mapping_by_family':placements}
    verify.save(args.output,result)
    print(json.dumps(result),flush=True)


if __name__=='__main__':
    main()
