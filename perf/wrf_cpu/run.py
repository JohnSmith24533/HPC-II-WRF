#!/usr/bin/env python3
"""Run the five original-grid WRF cases against frozen initial conditions."""
import argparse
import datetime as dt
import hashlib
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import time

import f90nml
import netCDF4 as nc

import verify

ROOT = Path(__file__).resolve().parents[2]
ART = Path(os.environ.get('WRF_CPU_ARTIFACTS',ROOT/'.wrf-cpu')).resolve()
CASES = json.loads((Path(__file__).with_name('cases.json')).read_text())['cases']


def digest(path):
    h = hashlib.sha256()
    with open(path,'rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def first(v):
    return v[0] if isinstance(v,list) else v


def start_date(nml):
    t = nml['time_control']
    return dt.datetime(*(first(t['start_'+k]) for k in ('year','month','day','hour','minute','second')))


def duration(nml):
    t = nml['time_control']
    return sum(first(t.get('run_'+k,0))*scale for k,scale in [('days',86400),('hours',3600),('minutes',60),('seconds',1)])


def set_times(nml,start,seconds,history,restart=False,checkpoint=None):
    tc = nml['time_control']
    for key in list(tc):
        if key.startswith(('history_interval','restart_interval')):
            del tc[key]
    for k in ('days','hours','minutes'):
        tc['run_'+k] = 0
    tc['run_seconds'] = seconds
    for prefix,date in [('start',start),('end',start+dt.timedelta(seconds=seconds))]:
        for key in ('year','month','day','hour','minute','second'):
            tc[prefix+'_'+key] = getattr(date,key)
    tc.update(history_interval_s=history,frames_per_outfile=1,restart=restart,
              restart_interval_s=checkpoint or seconds+3600,
              write_hist_at_0h_rst=True,io_form_history=2,io_form_restart=2)
    nml['domains']['nproc_x'] = -1
    nml['domains']['nproc_y'] = -1


@lru_cache(maxsize=2)
def frozen_runtime(real=False):
    kind = 'real' if real else 'ideal'
    directory = ART/'runtime'/kind
    manifest = directory/'runtime.json'
    if manifest.exists():
        data = json.loads(manifest.read_text())
        for name,sha in data['sha256'].items():
            if digest(directory/name) != sha:
                raise RuntimeError(f'frozen runtime table changed: {directory/name}')
        return directory
    directory.mkdir(parents=True,exist_ok=False)
    excluded = {'namelist.input','namelist.output','ideal','real','ndown','tc','registry','diffwrf_int','diffwrf_nc'}
    for path in (ART/('install-'+kind)/'run').iterdir():
        if path.is_file() and path.name not in excluded and not path.name.startswith(('wrf','rsl.')) and path.suffix!='.exe':
            shutil.copy2(path.resolve(),directory/path.name)
    verify.save(manifest,{'kind':kind,'sha256':{p.name:digest(p) for p in directory.iterdir() if p.is_file()}})
    return directory


def stage_runtime(directory,real=False):
    for path in frozen_runtime(real).iterdir():
        if path.is_file() and path.name!='runtime.json':
            (directory/path.name).symlink_to(path.resolve())


def initialize(case):
    cfg = CASES[case]
    dest = ART/'inputs'/case
    if (dest/'inputs.json').exists():
        meta = json.loads((dest/'inputs.json').read_text())
        for name,sha in meta['sha256'].items():
            if digest(dest/name) != sha:
                raise RuntimeError(f'frozen input changed: {dest/name}')
        return dest
    if dest.exists():
        raise RuntimeError(f'incomplete input directory: {dest}; inspect before resuming')
    dest.mkdir(parents=True)
    install = ART/('install-real' if case=='conus12' else 'install-ideal')
    stage_runtime(dest,case=='conus12')
    if case=='conus12':
        source = ART/'data/v4.4_bench_conus12km'
        for name in ('wrfinput_d01','wrfbdy_d01','namelist.input'):
            shutil.copy2(source/name,dest/name)
        for path in source.glob('*.dat'):
            if (dest/path.name).exists():
                (dest/path.name).unlink()
            shutil.copy2(path,dest/path.name)
    else:
        source = ROOT/'test'/cfg['source']
        for name in ('namelist.input','input_sounding','input_jet'):
            if (source/name).is_file():
                shutil.copy2(source/name,dest/name)
        nml = f90nml.read(dest/'namelist.input')
        set_times(nml,start_date(nml),cfg['full_seconds'],cfg['history_seconds'])
        nml.write(dest/'namelist.input',force=True)
        with (dest/'ideal-launcher.log').open('w') as log:
            code = subprocess.call(['mpirun','-np','1',str(install/'bin/ideal')],cwd=dest,stdout=log,stderr=subprocess.STDOUT)
        if code or not (dest/'wrfinput_d01').is_file():
            raise RuntimeError(f'ideal failed for {case}: exit {code}; inspect {dest}')
    files = [p for p in dest.iterdir() if p.is_file() and not p.is_symlink() and not p.name.startswith('rsl.')]
    verify.save(dest/'inputs.json',{'case':case,'initialization_ranks':1,
                'note':'Freeze once: LES/convrad contain random perturbations. Candidates reuse these exact bytes.',
                'sha256':{p.name:digest(p) for p in files}})
    return dest


def run_case(case,tier,label,ranks,install_ideal=None,install_real=None):
    cfg = CASES[case]
    frozen = initialize(case)
    dest = ART/'runs'/label/case/tier
    install = (install_real or ART/'install-real') if case=='conus12' else (install_ideal or ART/'install-ideal')
    if dest.exists():
        # Resume only a verified completed run, never overwrite a failed or live run.
        if (dest/'check.json').exists() and json.loads((dest/'check.json').read_text())['passed']:
            previous = json.loads((dest/'run.json').read_text())
            if previous['ranks'] != ranks or previous['executable_sha256'] != digest(install/'bin/wrf') or previous['frozen_inputs_sha256'] != digest(frozen/'inputs.json'):
                raise RuntimeError(f'provenance changed for completed run: {dest}; use a new label')
            checked = verify.execution(dest)
            if not checked['passed']:
                raise RuntimeError(f'completed run no longer verifies: {dest}: {checked["errors"][:3]}')
            verify.save(dest/'check.json',checked)
            if tier=='restart':
                compared=verify.compare(dest,dest.parent/'full',overlap=True)
                verify.save(dest/'restart-compare.json',json.loads(json.dumps(compared,default=lambda x:x.item())))
                if not compared['passed']:
                    raise RuntimeError(f'restart no longer verifies: {dest}')
            return dest
        raise RuntimeError(f'existing incomplete run {dest}; inspect it, then choose a new label')
    dest.mkdir(parents=True)
    stage_runtime(dest,case=='conus12')
    for path in frozen.iterdir():
        if path.name.startswith(('wrfinput','wrfbdy')) or path.suffix=='.dat':
            if (dest/path.name).is_symlink():
                (dest/path.name).unlink()
            (dest/path.name).symlink_to(path.resolve())
    nml = f90nml.read(frozen/'namelist.input')
    start = start_date(nml)
    full_seconds = cfg['full_seconds'] or duration(nml)
    seconds = {'single':cfg['dt'],'short':cfg['short_seconds'],'full':full_seconds,'restart':full_seconds//2}[tier]
    history = cfg['dt'] if tier=='single' else (seconds if tier=='short' else cfg['history_seconds'])
    if tier=='restart':
        continuous = ART/'runs'/label/case/'full'
        start += dt.timedelta(seconds=full_seconds//2)
        name = 'wrfrst_d01_'+start.strftime(verify.STAMP)
        if not (continuous/name).is_file():
            raise RuntimeError(f'missing checkpoint {continuous/name}')
        (dest/name).symlink_to((continuous/name).resolve())
    set_times(nml,start,seconds,history,tier=='restart',full_seconds//2 if tier=='full' else None)
    history_at_start = tier!='restart' or cfg.get('restart_initial_history',True)
    nml['time_control']['write_hist_at_0h_rst'] = history_at_start
    if case in ('les','quarter_ss'):
        (dest/'iofields.txt').write_text('+:h:0:TKE\n'+''.join('-:h:0:'+name+'\n' for name in cfg.get('omitted_inactive_history',[])))
        nml['time_control']['iofields_filename'] = 'iofields.txt'
        nml['time_control']['ignore_iofields_warning'] = False
    nml.write(dest/'namelist.input')
    physics = nml['physics']
    required = ['RAINC','RAINNC']
    mp = 8 if case=='conus12' else first(physics.get('mp_physics',0))
    if mp:
        required += ['QVAPOR','QCLOUD','QRAIN']
    if mp in (6,8):
        required += ['QICE','QSNOW','QGRAUP']
    if case in ('les','quarter_ss'):
        required += ['TKE']
    if case=='convrad':
        required += ['SWDOWN','GLW','HFX','PBLH']
    executable = install/'bin/wrf'
    meta = {'case':case,'tier':tier,'label':label,'ranks':ranks,'threads':1,'grid':cfg['grid'],
            'omitted_inactive_history':cfg.get('omitted_inactive_history',[]),'expected_physics':cfg['physics'],'history_at_start':history_at_start,'dt':cfg['dt'],'history_seconds':history,'start':start.strftime(verify.STAMP),
            'end':(start+dt.timedelta(seconds=seconds)).strftime(verify.STAMP),'required':required,
            'executable':str(executable),'executable_sha256':digest(executable),
            'namelist_sha256':digest(dest/'namelist.input'),
            'frozen_inputs_sha256':digest(frozen/'inputs.json'),
            'job_id':os.environ.get('SLURM_JOB_ID'),'host':os.uname().nodename,'exit_code':None}
    verify.save(dest/'run.json',meta)
    before = time.monotonic()
    with (dest/'launcher.log').open('w') as log:
        code = subprocess.call(['mpirun','-np',str(ranks),str(executable)],cwd=dest,stdout=log,stderr=subprocess.STDOUT)
    meta.update(exit_code=code,wall_seconds=time.monotonic()-before)
    logs = '\n'.join(p.read_text(errors='replace') for p in dest.glob('rsl.out.0000'))
    timing = [float(v) for v in re.findall(r'Timing for main:.*?:\s+([\d.Ee+-]+)\s+elapsed seconds',logs)]
    meta['step_timing_seconds'] = {'count':len(timing),'mean':statistics.mean(timing) if timing else None,
                                    'median':statistics.median(timing) if timing else None,'values':timing}
    verify.save(dest/'run.json',meta)
    try:
        report = verify.execution(dest)
    except Exception as exc:
        report = {'passed':False,'errors':[f'{type(exc).__name__}: {exc}']}
    verify.save(dest/'check.json',report)
    print(json.dumps({'case':case,'tier':tier,'label':label,'passed':report['passed'],'wall_seconds':meta['wall_seconds'],'errors':report['errors'][:6]}),flush=True)
    if not report['passed']:
        raise RuntimeError(f'execution verification failed: {dest}/check.json')
    if tier=='restart':
        report = verify.compare(dest,ART/'runs'/label/case/'full',overlap=True)
        verify.save(dest/'restart-compare.json',json.loads(json.dumps(report,default=lambda x:x.item())))
        if not report['passed']:
            raise RuntimeError(f'restart differs: {dest}/restart-compare.json')
    return dest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--label',required=True)
    p.add_argument('--cases',nargs='+',choices=CASES,default=list(CASES))
    p.add_argument('--tiers',nargs='+',choices=['single','short','full','restart'],default=['single','short','full','restart'])
    p.add_argument('--ranks',type=int,default=4)
    p.add_argument('--conus-ranks',type=int,default=16)
    p.add_argument('--against',help='label to compare against, e.g. baseline; use golden after publication')
    p.add_argument('--install-ideal',type=Path)
    p.add_argument('--install-real',type=Path)
    args = p.parse_args()
    branch = subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()
    if branch != 'perf/wrf-cpu':
        raise RuntimeError('branch must remain perf/wrf-cpu')
    if not re.fullmatch(r'[A-Za-z0-9_-]+',args.label):
        raise ValueError('label must contain only letters, numbers, underscores or hyphens')
    if args.against=='golden':
        from audit import audit
        audit(ART)
    for case in args.cases:
        for tier in args.tiers:
            directory = run_case(case,tier,args.label,args.conus_ranks if case=='conus12' else args.ranks,args.install_ideal,args.install_real)
            if args.against and tier!='restart':
                ref = ART/'golden'/case/tier if args.against=='golden' else ART/'runs'/args.against/case/tier
                result = verify.compare(directory,ref)
                verify.save(directory/'compare.json',json.loads(json.dumps(result,default=lambda x:x.item())))
                print(json.dumps({'case':case,'tier':tier,'comparison':args.against,'passed':result['passed']}),flush=True)
                if not result['passed']:
                    raise RuntimeError(f'comparison failed: {directory}/compare.json')


if __name__=='__main__':
    main()
