#!/usr/bin/env python3
"""Compare frozen, current-serial and parallel verifiers on real completed output."""
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import time
import traceback

import run
import verify


def canonical(report):
    return json.dumps(report,sort_keys=True,allow_nan=False,default=lambda x:x.item())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers',type=int,default=8)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    if not os.environ.get('SLURM_JOB_ID') or args.workers<1:
        parser.error('run on a compute allocation with positive workers')
    if args.report.exists():
        parser.error('verification preflight report already exists; preserve prior evidence')
    candidate=run.ART/'runs/S001-scaling-screen-r01-p112/conus12/short'
    if not candidate.is_dir():
        candidate=run.ART/'runs/baseline/conus12/short'
    reference=run.ART/'golden/conus12/short'
    frozen_path=run.ART/'baseline/harness/verify.py'
    manifest=json.loads((run.ART/'golden/manifest.json').read_text())
    if run.digest(run.ART/'golden/manifest.json')!=(run.ART/'golden-manifest.sha256').read_text().strip():
        raise RuntimeError('original golden manifest seal mismatch')
    if run.digest(frozen_path)!=manifest['harness']['verify.py']:
        raise RuntimeError('frozen verifier no longer matches original golden provenance')
    spec=importlib.util.spec_from_file_location('frozen_baseline_verify',frozen_path)
    frozen=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(frozen)
    meta={'purpose':'V001: verifier equivalence/turnaround only; no WRF execution or model speedup claim',
          'status':'running','job_id':os.environ['SLURM_JOB_ID'],'host':os.uname().nodename,
          'created_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'workers_requested':args.workers,
          'candidate':str(candidate),'reference':str(reference),'frozen_verifier_sha256':run.digest(frozen_path),
          'current_verifier_sha256':run.digest(Path(verify.__file__)),
          'input_sha256':{str(p):run.digest(p) for d in (candidate,reference) for p in sorted(d.glob('wrfout_d01_*'))},
          'results':{}}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(__file__,args.report.with_suffix('.harness.py'))
    verify.save(args.report,meta)
    try:
        canonical_values=[]
        for kind,function,options in [('frozen_serial',frozen.compare,{}),
                                      ('current_serial',verify.compare,{'workers':1}),
                                      ('current_parallel',verify.compare,{'workers':args.workers})]:
            start=time.monotonic()
            compared=function(candidate,reference,**options)
            elapsed=time.monotonic()-start
            value=canonical(compared)
            canonical_values.append(value)
            args.report.with_suffix('.'+kind+'.json').write_text(value+'\n')
            meta['results'][kind]={'verifier_wall_seconds':elapsed,
                'canonical_report_sha256':hashlib.sha256(value.encode()).hexdigest(),
                'metric_rows':len(compared['metrics']),
                'differing_metric_rows':sum(not r['passed'] for r in compared['metrics'])}
            verify.save(args.report,meta)
        if len(set(canonical_values))!=1:
            raise RuntimeError('parallel/current reports differ from original sealed verifier')
        if run.digest(Path(verify.__file__))!=meta['current_verifier_sha256']:
            raise RuntimeError('current verifier changed during equivalence check')
        meta.update(status='completed',reports_identical=True)
    except BaseException:
        meta['status']='failed'
        meta['error']=traceback.format_exc()
        raise
    finally:
        meta['updated_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
        verify.save(args.report,meta)
    print(json.dumps(meta),flush=True)


if __name__=='__main__':
    main()
