#!/usr/bin/env python3
"""Fail-closed WRF execution, numerical and physical-regression checks."""
import argparse
from contextlib import ExitStack
import datetime as dt
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import re
import sys

import netCDF4 as nc
import numpy as np

CORE = {'U', 'V', 'W', 'T', 'P', 'PB', 'PH', 'PHB', 'MU', 'MUB', 'PSFC', 'TSK'}
SPECIES = ['QVAPOR', 'QCLOUD', 'QRAIN', 'QICE', 'QSNOW', 'QGRAUP']
STAMP = '%Y-%m-%d_%H:%M:%S'


def save(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')


def index(directory, stack):
    records, schema = {}, None
    for path in sorted(Path(directory).glob('wrfout_d01_*')):
        ds = stack.enter_context(nc.Dataset(path))
        current = {k: (v.dimensions, str(v.dtype), tuple(v.shape[i] for i, d in enumerate(v.dimensions) if d != 'Time'), getattr(v,'units','')) for k, v in ds.variables.items()}
        if schema is not None and current != schema:
            raise ValueError(f'inconsistent output schema: {path}')
        schema = current
        times = nc.chartostring(ds['Times'][:]).tolist()
        for i, time in enumerate(times):
            if time in records:
                raise ValueError(f'duplicate output time: {time}')
            records[time] = (ds, i)
    if not records:
        raise ValueError(f'no WRF history output in {directory}')
    return records, schema


def field(ds, name, i):
    var = ds[name]
    key = tuple(i if dim == 'Time' else slice(None) for dim in var.dimensions)
    return np.ma.asarray(var[key])


def derived(ds, i):
    p = field(ds, 'P', i).astype('f8') + field(ds, 'PB', i)
    theta = field(ds, 'T', i).astype('f8') + 300.0
    return {'pressure_pa': p, 'theta_k': theta,
            'temperature_k': theta * (p / 100000.0)**(287.0/1004.5),
            'geopotential_height_m': (field(ds, 'PH', i).astype('f8') + field(ds, 'PHB', i))/9.81}


def diagnostics(ds, i):
    """Budget proxies, not a claim of closed budgets in an open regional domain."""
    d = {}
    mass = field(ds, 'MU', i).astype('f8') + field(ds, 'MUB', i)
    area = float(ds.DX)*float(ds.DY)
    # Modern WRF uses separate x/y factors; MAPFAC_M can remain zero in ideal cases.
    if 'MAPFAC_MX' in ds.variables and 'MAPFAC_MY' in ds.variables:
        factors = field(ds,'MAPFAC_MX',i).astype('f8')*field(ds,'MAPFAC_MY',i)
        if np.ma.getmaskarray(factors).any() or np.any(factors<=0):
            raise ValueError('invalid x/y map factors for budget diagnostics')
        area = area/factors
    elif 'MAPFAC_M' in ds.variables:
        factors = field(ds,'MAPFAC_M',i).astype('f8')
        if np.ma.getmaskarray(factors).any() or np.any(factors<=0):
            raise ValueError('invalid map factor for budget diagnostics')
        area = area/factors**2
    column_mass = mass * area / 9.81
    d['dry_mass_kg'] = float(np.ma.sum(column_mass))
    d['theta_mean_k'] = float(np.ma.mean(derived(ds, i)['theta_k']))
    # DNW is negative in WRF. Hybrid coordinates require C1H/C2H.
    if 'DNW' in ds.variables:
        dn = -field(ds, 'DNW', i).astype('f8')[:, None, None]
        if 'C1H' in ds.variables and 'C2H' in ds.variables:
            layer_mass = (field(ds, 'C1H', i)[:,None,None]*mass + field(ds, 'C2H', i)[:,None,None])*dn*area/9.81
        else:
            layer_mass = dn*column_mass
        water = np.zeros_like(layer_mass)
        for name in SPECIES:
            if name in ds.variables:
                q = field(ds, name, i).astype('f8')
                water += q
                d[name + '_min_kgkg'] = float(np.ma.min(q))
                d[name + '_negative_fraction'] = float(np.ma.mean(q < -1e-12))
        d['atmospheric_water_kg'] = float(np.ma.sum(water*layer_mass))
        physical = derived(ds,i)
        z = physical['geopotential_height_m']
        u,v,w = (field(ds,name,i).astype('f8') for name in ('U','V','W'))
        target = physical['temperature_k'].shape
        if z.shape[0] == target[0]+1 and u.shape[-1] == target[-1]+1 and v.shape[-2] == target[-2]+1 and w.shape[0] == target[0]+1:
            z = 0.5*(z[:-1]+z[1:])
            u = 0.5*(u[:,:,:-1]+u[:,:,1:])
            v = 0.5*(v[:,:-1,:]+v[:,1:,:])
            w = 0.5*(w[:-1]+w[1:])
            energy = 717.5*physical['temperature_k'] + 9.81*z + 0.5*(u*u+v*v+w*w)
            d['dry_energy_inventory_proxy_j'] = float(np.ma.sum(energy*layer_mass))
    rain = None
    for name in ('RAINC','RAINNC','RAINSH'):
        if name in ds.variables:
            value = field(ds, name, i).astype('f8')
            count_name = 'I_' + name
            if count_name in ds.variables and getattr(ds,'BUCKET_MM',-1) > 0:
                value = value + ds.BUCKET_MM*field(ds,count_name,i)
            rain = value if rain is None else rain + value
    if rain is not None:
        d['rain_max_mm'] = float(np.ma.max(rain))
        d['rain_area_ge_0.1mm_fraction'] = float(np.ma.mean(rain >= 0.1))
        d['rain_volume_m3'] = float(np.ma.sum(rain*area/1000))
        total = float(np.ma.sum(rain))
        if total > 0:
            y,x = np.indices(rain.shape)
            d['rain_centroid_x_grid'] = float(np.ma.sum(x*rain)/total)
            d['rain_centroid_y_grid'] = float(np.ma.sum(y*rain)/total)
    for name in ('TKE','TKE_PBL','HFX','LH','SWDOWN','GLW','PBLH'):
        if name in ds.variables:
            v = field(ds,name,i).astype('f8')
            d[name + '_available_fraction'] = float(v.count()/v.size)
            d[name + '_mean'] = float(np.ma.mean(v)) if v.count() else None
            d[name + '_max'] = float(np.ma.max(v)) if v.count() else None
    return d


def execution(directory):
    directory = Path(directory)
    meta = json.loads((directory/'run.json').read_text())
    errors = []
    if 'namelist_sha256' in meta and hashlib.sha256((directory/'namelist.input').read_bytes()).hexdigest()!=meta['namelist_sha256']:
        errors.append('namelist changed after execution')
    if meta.get('exit_code') != 0:
        errors.append('missing or unsuccessful WRF exit code')
    logs = '\n'.join(p.read_text(errors='replace') for p in directory.glob('rsl.*.*'))
    if 'SUCCESS COMPLETE WRF' not in logs:
        errors.append('missing SUCCESS COMPLETE WRF')
    if re.search(r'\b(?:nan|infinity|inf|SIGSEGV|SIGFPE|FATAL)\b|segmentation fault|forrtl: severe', logs, re.I):
        errors.append('nonfinite value or fatal runtime error in logs')
    if re.search(r'\bopen_hist_w\s*:\s*error opening.*for writing',logs,re.I):
        errors.append('WRF history output could not be opened for writing')
    start = dt.datetime.strptime(meta['start'], STAMP)
    end = dt.datetime.strptime(meta['end'], STAMP)
    steps = sorted(set(re.findall(r'Timing for main:\s*time\s+(\d{4}-\d\d-\d\d_\d\d:\d\d:\d\d)\s+on domain\s+1', logs)))
    expected_steps = [(start+dt.timedelta(seconds=s)).strftime(STAMP) for s in range(meta['dt'], int((end-start).total_seconds())+1,meta['dt'])]
    if steps != expected_steps:
        errors.append(f'timestep coverage mismatch: observed {len(steps)}, expected {len(expected_steps)}')
    physical = {}
    with ExitStack() as stack:
        frames, schema = index(directory, stack)
        expected = [(start+dt.timedelta(seconds=s)).strftime(STAMP) for s in range(0 if meta.get('history_at_start',True) else meta['history_seconds'],int((end-start).total_seconds())+1,meta['history_seconds'])]
        if sorted(frames) != expected:
            errors.append('history times differ from the complete expected schedule')
        for time,(ds,i) in sorted(frames.items()):
            if 'ranks' in meta and getattr(ds,'NTASKS_TOTAL',None) != meta['ranks']:
                errors.append(f'{time}: output MPI task count differs from launch configuration')
            for key,value in meta.get('expected_physics',{}).items():
                if getattr(ds,key.upper(),None) != value:
                    errors.append(f'{time}: physics mismatch {key}: expected {value}, got {getattr(ds,key.upper(),None)}')
            required = CORE | set(meta['required'])
            missing = required-set(ds.variables)
            if missing:
                errors.append(f'{time}: missing fields {sorted(missing)}')
            actual = [len(ds.dimensions[d]) for d in ('west_east_stag','south_north_stag','bottom_top_stag')]
            if any(want is not None and want != got for want,got in zip(meta['grid'],actual)):
                errors.append(f'{time}: grid mismatch {actual}')
            for name,var in ds.variables.items():
                if var.dtype.kind not in 'iuf':
                    continue
                v = field(ds,name,i)
                if not np.isfinite(np.asarray(v)).all():
                    errors.append(f'{time}: {name} contains NaN/Inf')
                if name in required and np.ma.getmaskarray(v).any():
                    errors.append(f'{time}: {name} contains missing data')
            d = diagnostics(ds,i)
            for name in SPECIES:
                if d.get(name+'_min_kgkg',0) < -1e-8:
                    errors.append(f'{time}: anomalous negative {name}')
            physical[time] = d
    return {'passed':not errors,'errors':errors,'steps':len(steps),'frames':len(physical),'physical':physical}


def metrics(candidate, reference, atol=0., rtol=0., bitwise=True):
    if candidate.shape != reference.shape:
        raise ValueError('field shape mismatch')
    am,bm = np.ma.getmaskarray(candidate),np.ma.getmaskarray(reference)
    if not np.array_equal(am,bm):
        raise ValueError('missing-data masks differ')
    valid = ~am
    a,b = np.asarray(candidate)[valid],np.asarray(reference)[valid]
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError('nonfinite comparison data')
    if not a.size:
        return {'passed':True,'count':0,'all_missing':True}
    delta = a.astype('f8')-b.astype('f8')
    diff = np.abs(delta)
    flat = np.flatnonzero(valid)[int(np.argmax(diff))]
    mismatch = diff > (atol + rtol*np.abs(b.astype('f8')))
    exact = a.dtype == b.dtype and a.tobytes() == b.tobytes()
    return {'passed':exact if bitwise else not bool(np.any(mismatch)), 'bitwise_equal':exact,
            'count':int(a.size),'rmse':float(np.sqrt(np.mean(delta*delta))),
            'max_abs':float(diff.max()),'max_location':list(np.unravel_index(int(flat),candidate.shape)),
            'bias':float(delta.mean()),'exceed_fraction':float(mismatch.mean()),'atol':atol,'rtol':rtol}


def compare_frame(time, candidate, ci, reference, ri, policy):
    errors, rows = [], []
    with nc.Dataset(candidate) as cd, nc.Dataset(reference) as rd:
        for name in sorted(set(cd.variables)&set(rd.variables)):
            cv,rv = cd[name],rd[name]
            if cv.dtype.kind not in 'iuf':
                if not np.array_equal(field(cd,name,ci),field(rd,name,ri)):
                    errors.append(f'{time}: nonnumeric field differs: {name}')
                continue
            tol = (policy or {}).get(name, {'atol':0,'rtol':0})
            m = metrics(field(cd,name,ci),field(rd,name,ri),**tol,bitwise=policy is None)
            rows.append({'time':time,'variable':name,'units':getattr(rv,'units',''),**m})
            if not m['passed']:
                errors.append(f'{time}: {name} differs')
        cderived,rderived = derived(cd,ci),derived(rd,ri)
        for name in cderived:
            tol = (policy or {}).get(name, {'atol':0,'rtol':0})
            m = metrics(cderived[name],rderived[name],**tol,bitwise=policy is None)
            rows.append({'time':time,'variable':name,**m})
            if not m['passed']:
                errors.append(f'{time}: derived {name} differs')
        cphys,rphys = diagnostics(cd,ci),diagnostics(rd,ri)
        physical = {'candidate':cphys,'reference':rphys,
                    'delta':{k:cphys[k]-rphys[k] if cphys[k] is not None and rphys[k] is not None else None for k in cphys.keys()&rphys.keys()}}
    return time, errors, rows, physical


def compare(candidate, reference, policy=None, overlap=False, workers=None):
    errors, rows, physical = [], [], {}
    automatic_workers = workers is None
    workers = int(os.environ.get('WRF_VERIFY_WORKERS','1')) if workers is None else workers
    if type(workers) is not int or workers < 1:
        raise ValueError('comparison workers must be a positive integer')
    jobs = []
    with ExitStack() as stack:
        ca,cs = index(candidate, stack)
        ra,rs = index(reference, stack)
        if cs != rs:
            errors.append('variable names, dimensions, shape or dtype differ')
        if (not overlap and set(ca)!=set(ra)) or not set(ca)<=set(ra):
            errors.append('output time coverage differs')
        for time,(cd,ci) in sorted(ca.items()):
            if time not in ra:
                continue
            rd,ri = ra[time]
            jobs.append((time,cd.filepath(),ci,rd.filepath(),ri,policy))
    # Close parent HDF5 handles before workers open their own files. Never fork
    # live NetCDF/HDF5 state or split any array reduction across processes.
    paths = {job[pos] for job in jobs for pos in (1,3)}
    if automatic_workers and sum(Path(path).stat().st_size for path in paths) < 256*1024**2:
        workers = 1  # Avoid process startup cost for tiny ideal-case reports.
    if workers > 1 and len(jobs) > 1:
        with multiprocessing.get_context('spawn').Pool(min(workers,len(jobs))) as pool:
            compared = pool.starmap(compare_frame,jobs)
    else:
        compared = [compare_frame(*job) for job in jobs]
    for time, frame_errors, frame_rows, frame_physical in compared:
        errors.extend(frame_errors)
        rows.extend(frame_rows)
        physical[time] = frame_physical
    return {'passed':not errors,'errors':errors,'metrics':rows,'physical':physical,
            'mode':'bitwise' if policy is None else 'per-variable tolerance',
            'budget_note':'Mass/water/heat diagnostics are regression proxies; regional boundary fluxes and sources/sinks preclude unconditional conservation assertions.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    check = sub.add_parser('check')
    check.add_argument('directory')
    comp = sub.add_parser('compare')
    comp.add_argument('candidate')
    comp.add_argument('reference')
    comp.add_argument('--policy',help='JSON per field {atol,rtol}; absent fields stay strict')
    comp.add_argument('--overlap',action='store_true',help='restart tail must be a subset of continuous output times')
    for p in (check,comp):
        p.add_argument('--report',required=True)
    args = parser.parse_args()
    try:
        if args.command == 'check':
            result = execution(args.directory)
        else:
            policy = json.loads(Path(args.policy).read_text()) if args.policy else None
            if policy is not None:
                for name,tol in policy.items():
                    if set(tol) != {'atol','rtol'} or any(not np.isfinite(v) or v<0 for v in tol.values()):
                        raise ValueError(f'invalid tolerance for {name}')
            result = compare(args.candidate,args.reference,policy,args.overlap)
    except Exception as exc:
        result = {'passed':False,'errors':[f'{type(exc).__name__}: {exc}']}
    # NumPy integer positions are converted explicitly for portable JSON.
    result = json.loads(json.dumps(result,default=lambda v:v.item(),allow_nan=False))
    save(args.report,result)
    print(json.dumps({'passed':result['passed'],'report':args.report,'errors':result['errors'][:12]}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
