#!/usr/bin/env python3
"""Continue completed matched repeats through strict certification and baseline profiles."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

import certify_scaled
from matched_repeats import preserve
import run


def allocation(config, selection):
    trial=Path(config['source_trials'][0])
    meta=json.loads((trial/'run.json').read_text())
    source=re.sub(r'-r\d+-p\d+$','',meta['label'])
    path=Path(selection['experiments'][source]['path']).parent/'slurm-job.txt'
    descriptor=path.read_text()
    nodes=re.search(r'\bNumNodes=(\d+)\b',descriptor)
    hosts=re.search(r'(?:^|\s)NodeList=(\S+)',descriptor)
    if not nodes or not hosts:
        raise RuntimeError('measured allocation descriptor is incomplete: '+str(path))
    nodes=int(nodes[1])
    if not 1<=nodes<=10 or config['ranks']>nodes*112:
        raise RuntimeError('measured allocation exceeds the original resource budget')
    return {'nodes':nodes,'nodelist':hosts[1],
            'source_descriptor':str(path),'source_descriptor_sha256':run.digest(path)}


def batch_options(name, resources):
    return [f'--job-name=wrf-{name}',f'--nodes={resources["nodes"]}',
            f'--ntasks={resources["nodes"]*112}','--ntasks-per-node=112',
            f'--nodelist={resources["nodelist"]}','--time=03:00:00',
            f'--output=.wrf-cpu/logs/{name}-%j.log']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--after-job',required=True)
    parser.add_argument('--source-prefix',default='S005m')
    parser.add_argument('--label',default='S006-scaled')
    parser.add_argument('--profile-label',default='P001-baseline')
    args=parser.parse_args()
    if not args.after_job.isdigit() or any(not re.fullmatch(r'[A-Za-z0-9_-]+',v)
                                          for v in (args.source_prefix,args.label,args.profile_label)):
        parser.error('use actual job handle and unique safe labels')
    root=Path(__file__).parent
    families=['ideal-spread','ideal-core','real-auto-core','real-explicit-core']
    sources=[args.source_prefix+'-'+family for family in families]
    watch=run.ART/'progress'/f'{args.label}-preceding-job.json'
    preserve(watch,[{'name':sources[-1],'existing_job':args.after_job,
                     'result':f'experiments/{sources[-1]}/results.json'}])
    subprocess.run([sys.executable,str(root/'campaign.py'),'--plan',str(watch),
                    '--state',str(run.ART/f'{args.label}-preceding-state.json')],check=True)
    winners=run.ART/'progress/S006-winners.json'
    if not winners.exists():
        subprocess.run([sys.executable,str(root/'select_finalists.py'),'--experiments',*sources,
                        '--top','1','--near-best-fraction','0','--output',str(winners)],
                       stdout=subprocess.DEVNULL,check=True)
    selection=json.loads(winners.read_text())
    if set(selection['experiments'])!=set(sources) or selection.get('near_best_fraction')!=0:
        raise RuntimeError('winner selection has different source experiments or protocol')
    configs=certify_scaled.selected_configurations(selection)
    resources={case:allocation(config,selection) for case,config in configs.items()}
    ideals=[case for case in run.CASES if case!='conus12']
    ideal=resources[ideals[0]]
    if ideal['nodes']!=1 or any(resources[c]['nodes']!=1 or resources[c]['nodelist']!=ideal['nodelist'] for c in ideals):
        raise RuntimeError('ideal certification requires the same measured single-node hardware')
    certification=[]
    for group,cases,res in [('ideal',ideals,ideal),('real',['conus12'],resources['conus12'])]:
        name=args.label+'-'+group
        command=[*batch_options(name,res),'perf/wrf_cpu/certify_scaled.slurm',
                 '--selection',str(winners),'--label',args.label,'--cases',*cases]
        if group=='real':command.append('--publish')
        certification.append({'name':name,'result':f'experiments/{args.label}/{group}/results.json',
                              'sbatch':command,'measured_allocation':res,
                              'selection_sha256':run.digest(winners),'builder_sha256':run.digest(Path(__file__))})
    cert_plan=run.ART/'progress'/f'{args.label}-campaign.json'
    preserve(cert_plan,certification)
    print(json.dumps({'winners':str(winners),'certification_plan':str(cert_plan),
                      'configs':{case:{k:value[k] for k in ('ranks','processor_grid','mpi_options','wall_seconds_per_timestep')}
                                 for case,value in configs.items()}}),flush=True)
    subprocess.run([sys.executable,str(root/'campaign.py'),'--plan',str(cert_plan),
                    '--state',str(run.ART/f'{args.label}-campaign-state.json')],check=True)
    # Publication/audit in the final certification stage must finish first.
    profiles=[]
    for case in run.CASES:
        reference=run.ART/'scaled-golden'/case/'full/run.json'
        baseline=json.loads(reference.read_text())
        if baseline['ranks']!=configs[case]['ranks'] or baseline.get('processor_grid')!=configs[case]['processor_grid']:
            raise RuntimeError('published reference differs from selected configuration')
        name=args.profile_label+'-'+case
        profiles.append({'name':name,'result':f'experiments/{args.profile_label}/{case}/profile.json',
                         'profile_evidence':True,
                         'sbatch':[*batch_options(name,resources[case]),'perf/wrf_cpu/profile.slurm',
                                   '--label',args.profile_label,'--case',case,'--reference-name','scaled-golden'],
                         'measured_allocation':resources[case],'reference_metadata_sha256':run.digest(reference)})
    profile_plan=run.ART/'progress'/f'{args.profile_label}-campaign.json'
    preserve(profile_plan,profiles)
    subprocess.run([sys.executable,str(root/'campaign.py'),'--plan',str(profile_plan),
                    '--state',str(run.ART/f'{args.profile_label}-campaign-state.json')],check=True)
    print(json.dumps({'certification_and_profiles_complete':True,
                      'optimization_speedup':'not measured by this pipeline'}),flush=True)


if __name__=='__main__':
    main()
