#!/usr/bin/env python3
"""Verify the published reference and frozen inputs before candidate runs."""
import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def audit(artifacts):
    artifacts=Path(artifacts)
    golden=artifacts/'golden'
    manifest_path=golden/'manifest.json'
    seal=(artifacts/'golden-manifest.sha256').read_text().strip()
    if digest(manifest_path)!=seal:
        raise RuntimeError('golden manifest seal mismatch')
    manifest=json.loads(manifest_path.read_text())
    for relative,expected in manifest['files'].items():
        path=(golden/relative).resolve()
        if not path.is_relative_to(golden.resolve()) or digest(path)!=expected:
            raise RuntimeError(f'golden file changed: {relative}')
    for case,meta in manifest['inputs'].items():
        for name,expected in meta['sha256'].items():
            path=artifacts/'inputs'/case/name
            if digest(path)!=expected:
                raise RuntimeError(f'frozen input changed: {path}')
    for kind,meta in manifest['runtime'].items():
        for name,expected in meta['sha256'].items():
            path=artifacts/'runtime'/kind/name
            if digest(path)!=expected:
                raise RuntimeError(f'frozen runtime table changed: {path}')
    print(json.dumps({'passed':True,'golden_files':len(manifest['files']),'manifest_sha256':seal}),flush=True)
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--artifacts',type=Path,default=Path(__file__).resolve().parents[2]/'.wrf-cpu')
    args=p.parse_args()
    audit(args.artifacts)
