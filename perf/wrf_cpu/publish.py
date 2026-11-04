#!/usr/bin/env python3
"""Publish golden files only after independent replay and restart checks pass."""
import argparse
import json
from pathlib import Path
import shutil

import run
import verify


def publish(baseline,replay):
    if baseline==replay:
        raise ValueError('baseline and replay labels must be distinct')
    built_hashes={line.split(maxsplit=1)[1].strip():line.split()[0] for line in (run.ART/'baseline/executables.sha256').read_text().splitlines()}
    for case in run.CASES:
        if not (run.ART/'inputs'/case/'inputs.json').is_file():
            raise RuntimeError(f'missing frozen inputs for {case}')
        run.initialize(case)
    run.frozen_runtime(False)
    run.frozen_runtime(True)
    dest=run.ART/'golden'
    if dest.exists():
        raise RuntimeError('golden already exists; publication never overwrites a reference')
    records=[]
    for case in run.CASES:
        for label in (baseline,replay):
            for tier in ('single','short','full','restart'):
                directory=run.ART/'runs'/label/case/tier
                result=verify.execution(directory)
                if not result['passed']:
                    raise RuntimeError(f'execution gate failed: {directory}: {result["errors"][:3]}')
                if tier=='restart':
                    result=verify.compare(directory,directory.parent/'full',overlap=True)
                    if not result['passed']:
                        raise RuntimeError(f'restart gate failed: {directory}: {result["errors"][:3]}')
        for tier in ('single','short','full'):
            b=run.ART/'runs'/baseline/case/tier
            r=run.ART/'runs'/replay/case/tier
            result=verify.compare(r,b)
            if not result['passed']:
                raise RuntimeError(f'independent replay differs: {case}/{tier}')
            bm=json.loads((b/'run.json').read_text()); rm=json.loads((r/'run.json').read_text())
            expected_exe=run.ART/('install-real' if case=='conus12' else 'install-ideal')/'bin/wrf'
            if bm['label']!=baseline or rm['label']!=replay or bm['executable_sha256']!=built_hashes[str(expected_exe)] or run.digest(expected_exe)!=built_hashes[str(expected_exe)]:
                raise RuntimeError(f'baseline/replay do not identify the archived official build: {case}/{tier}')
            for key in ('executable_sha256','frozen_inputs_sha256','namelist_sha256','ranks','threads','dt','grid'):
                if bm[key]!=rm[key]:
                    raise RuntimeError(f'baseline/replay provenance differs: {case}/{tier}: {key}')
            records.append((case,tier,b))
    # All gates checked current NetCDF values. Publish via a staging directory.
    staging=run.ART/'golden-staging'
    staging.mkdir()
    manifest={'schema':1,'case_spec':run.CASES,'baseline_label':baseline,'replay_label':replay,
              'source_commit':(run.ART/'baseline/source-commit.txt').read_text().strip(),
              'comparison':'bitwise, all numeric history fields and reconstructed physical fields',
              'scope':'all five cases, single/short/full, independent rerun and restart',
              'files':{},'inputs':{},'harness':{},'runtime':{}}
    for case,tier,source in records:
        target=staging/case/tier; target.mkdir(parents=True)
        for path in list(source.glob('wrfout_d01_*'))+[source/'run.json',source/'namelist.input',source/'check.json']:
            shutil.copy2(path,target/path.name)
            manifest['files'][str((target/path.name).relative_to(staging))]=run.digest(target/path.name)
    for case in run.CASES:
        path=run.ART/'inputs'/case/'inputs.json'
        manifest['inputs'][case]=json.loads(path.read_text())
    for kind in ('ideal','real'):
        manifest['runtime'][kind]=json.loads((run.ART/'runtime'/kind/'runtime.json').read_text())
    for path in Path(__file__).parent.iterdir():
        if path.is_file() and path.name!='RESULTS.md':
            manifest['harness'][path.name]=run.digest(path)
    verify.save(staging/'manifest.json',manifest)
    for path in staging.rglob('*'):
        if path.is_file():
            path.chmod(0o444)
    for case,meta in manifest['inputs'].items():
        for name in meta['sha256']:
            (run.ART/'inputs'/case/name).chmod(0o444)
    for kind,meta in manifest['runtime'].items():
        for name in meta['sha256']:
            (run.ART/'runtime'/kind/name).chmod(0o444)
    staging.rename(dest)
    seal=run.ART/'golden-manifest.sha256'
    seal.write_text(run.digest(dest/'manifest.json')+'\n')
    seal.chmod(0o444)
    print(f'Published {dest}; {len(records)} case/tier references')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline',default='baseline')
    p.add_argument('--replay',default='replay')
    a=p.parse_args()
    publish(a.baseline,a.replay)
