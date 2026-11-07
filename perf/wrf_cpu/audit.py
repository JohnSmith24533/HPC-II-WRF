#!/usr/bin/env python3
"""Verify the published reference and frozen inputs before candidate runs."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def reference_paths(artifacts, name='golden'):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', name):
        raise ValueError('reference name must be one safe directory component')
    artifacts = Path(artifacts)
    return artifacts/name, artifacts/(name+'-manifest.sha256')


def audit(artifacts, name='golden'):
    artifacts=Path(artifacts)
    golden,seal_path=reference_paths(artifacts,name)
    manifest_path=golden/'manifest.json'
    seal=seal_path.read_text().strip()
    if digest(manifest_path)!=seal:
        raise RuntimeError('golden manifest seal mismatch')
    manifest=json.loads(manifest_path.read_text())
    for relative,expected in manifest['files'].items():
        path=(golden/relative).resolve()
        if not path.is_relative_to(golden.resolve()) or digest(path)!=expected:
            raise RuntimeError(f'golden file changed: {relative}')
    for case,meta in manifest['inputs'].items():
        for filename,expected in meta['sha256'].items():
            path=artifacts/'inputs'/case/filename
            if digest(path)!=expected:
                raise RuntimeError(f'frozen input changed: {path}')
    for kind,meta in manifest['runtime'].items():
        for filename,expected in meta['sha256'].items():
            path=artifacts/'runtime'/kind/filename
            if digest(path)!=expected:
                raise RuntimeError(f'frozen runtime table changed: {path}')
    print(json.dumps({'passed':True,'reference':name,'golden_files':len(manifest['files']),'manifest_sha256':seal}),flush=True)
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--artifacts',type=Path,default=Path(__file__).resolve().parents[2]/'.wrf-cpu')
    p.add_argument('--name',default='golden')
    args=p.parse_args()
    audit(args.artifacts,args.name)
