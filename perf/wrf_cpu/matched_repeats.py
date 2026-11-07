#!/usr/bin/env python3
"""Continue a verified matched-hardware sweep into pinned independent repeats."""
import argparse
import json
import math
from pathlib import Path
import re
import subprocess
import sys

import hardware
import run


def preserve(path, data):
    if path.exists():
        if json.loads(path.read_text()) != data:
            raise RuntimeError('existing plan differs; preserve it and use a new output path')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(data, stream, indent=2); stream.write('\n')


def prepare(selection, selection_path, prefix, ideal_node):
    if set(selection['cases']) != set(run.CASES) or set(selection.get('hardware_by_case',{})) != set(run.CASES):
        raise ValueError('all five cases and matched hardware evidence are required')
    plan=[]
    for family, matrix_path in selection['repeat_matrices'].items():
        matrix=json.loads(Path(matrix_path).read_text())
        ideal=family.startswith('ideal-')
        if family not in ('ideal-core','ideal-spread','real-auto-core','real-explicit-core'):
            raise ValueError('unsupported repeat family')
        if any((case!='conus12') != ideal for case in matrix):
            raise ValueError('mixed ideal/real repeat hardware')
        reference=run.ART/'experiments'/('S003p-ideal-spread' if ideal else 'S004b-conus-full')/'results.json'
        expected=hardware.reference_signature(json.loads(reference.read_text()))
        if any(hardware.differences(selection['hardware_by_case'][case],expected) for case in matrix):
            raise ValueError('repeat hardware reference differs from measured selection')
        ranks=[row['ranks'] for rows in matrix.values() for row in rows]
        nodes=1 if ideal else math.ceil(max(ranks)/112)
        if nodes>10 or max(ranks)>nodes*112:
            raise ValueError('repeat exceeds the original resource budget')
        nodelist=ideal_node if ideal else ('icpnp325' if nodes==1 else f'icpnp[325-{324+nodes}]')
        label=prefix+'-'+family
        command=[f'--job-name=wrf-{label}',f'--nodes={nodes}',f'--ntasks={nodes*112}',
                 '--ntasks-per-node=112',f'--nodelist={nodelist}',
                 '--time='+('02:00:00' if ideal else '03:00:00'),
                 '--export=ALL,WRF_HARDWARE_REFERENCE='+str(reference),
                 f'--output=.wrf-cpu/logs/{label}-%j.log','perf/wrf_cpu/scaling.slurm',
                 '--label',label,'--cases',*matrix.keys(),'--matrix',matrix_path,
                 '--mpi-map-by',selection['repeat_mapping_by_family'][family],
                 '--tiers','full','--repetitions','3','--compare-repeats','--discard-verified-output']
        plan.append({'name':label,'result':f'experiments/{label}/results.json','sbatch':command,
                     'selection_sha256':run.digest(selection_path),'matrix_sha256':run.digest(Path(matrix_path)),
                     'hardware_reference_sha256':run.digest(reference),'builder_sha256':run.digest(Path(__file__))})
    return plan


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--after-job',required=True)
    parser.add_argument('--after-experiment',default='S003q-ideal-core-matched')
    parser.add_argument('--prefix',default='S005m')
    parser.add_argument('--ideal-node',default='icpnp341')
    args=parser.parse_args()
    if not args.after_job.isdigit() or not re.fullmatch(r'S\d{3}[a-z]?',args.prefix):
        parser.error('use the actual Slurm job handle and a unique safe experiment prefix')
    root=Path(__file__).parent
    watch=run.ART/'progress'/f'{args.prefix}-preceding-job.json'
    preserve(watch,[{'name':args.after_experiment,'existing_job':args.after_job,
                     'result':f'experiments/{args.after_experiment}/results.json'}])
    subprocess.run([sys.executable,str(root/'campaign.py'),'--plan',str(watch),
                    '--state',str(run.ART/f'{args.prefix}-preceding-state.json')],check=True)
    selection_path=run.ART/'progress/S005-matched-finalists.json'
    if not selection_path.exists():
        subprocess.run([sys.executable,str(root/'select_finalists.py'),'--top','3','--near-best-fraction','0.03',
                        '--output',str(selection_path)],stdout=subprocess.DEVNULL,check=True)
    selection=json.loads(selection_path.read_text())
    if selection['top_per_case']!=3 or selection.get('near_best_fraction')!=.03:
        raise RuntimeError('selection protocol changed; preserve prior evidence')
    for source in selection['experiments'].values():
        if run.digest(Path(source['path'])) != source['sha256']:
            raise RuntimeError('source results changed since selection')
    plan=prepare(selection,selection_path,args.prefix,args.ideal_node)
    plan_path=run.ART/'progress'/f'{args.prefix}-campaign.json'
    preserve(plan_path,plan)
    print(json.dumps({'selection':str(selection_path),'plan':str(plan_path),
                      'repeat_configurations':sum(len(v) for v in selection['cases'].values()),
                      'stages':[stage['name'] for stage in plan]}),flush=True)
    subprocess.run([sys.executable,str(root/'campaign.py'),'--plan',str(plan_path),
                    '--state',str(run.ART/f'{args.prefix}-campaign-state.json')],check=True)


if __name__=='__main__':
    main()
