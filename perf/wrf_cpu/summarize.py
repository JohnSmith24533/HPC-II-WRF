#!/usr/bin/env python3
"""Summarize measured run evidence; missing evidence remains incomplete."""
import argparse
import json
import re
from pathlib import Path

import run


def summarize(labels):
    text=['# WRF CPU measured status','',
          'Branch: `perf/wrf-cpu`. Numeric reports and large files live in `.wrf-cpu/`.', '',
          '| Label | Case | Tier | Check | Comparison | Ranks | Wall s | Median step s | IO write s |',
          '|---|---|---|---|---|---|---|---|---|']
    for label in labels:
        for case in run.CASES:
            for tier in ('single','short','full','restart'):
                directory=run.ART/'runs'/label/case/tier
                def read(name):
                    p=directory/name
                    return json.loads(p.read_text()) if p.exists() else {}
                meta=read('run.json'); check=read('check.json')
                comparison=read('restart-compare.json' if tier=='restart' else 'compare.json')
                def flag(value):
                    return {True:'PASS',False:'FAIL',None:'pending'}[value.get('passed')]
                comparison_status='reference' if label=='baseline' and tier!='restart' else flag(comparison)
                wall=meta.get('wall_seconds'); median=meta.get('step_timing_seconds',{}).get('median')
                log=directory/'rsl.out.0000'
                io=[float(v) for v in re.findall(r'Timing for Writing.*?:\s+([\d.Ee+-]+)\s+elapsed seconds',log.read_text())] if log.exists() else []
                text.append(f'| {label} | {case} | {tier} | {flag(check)} | {comparison_status} | {meta.get("ranks","—")} | {f"{wall:.3f}" if wall is not None else "—"} | {f"{median:.6f}" if median is not None else "—"} | {f"{sum(io):.3f}" if io else "—"} |')
    text.extend(['','## Baseline physical diagnostics','',
                 'Budget changes below are measured inventories, not conservation assertions for domains with boundary fluxes or physical sources/sinks.', '',
                 '| Case | Final max rain mm | Wet area >=0.1 mm % | Final max TKE | Dry mass relative change | Atmospheric water change kg | Dry energy proxy relative change |',
                 '|---|---|---|---|---|---|---|'])
    def number(value):
        return f'{value:.6g}' if value is not None else '—'
    for case in run.CASES:
        path=run.ART/'runs'/'baseline'/case/'full/check.json'
        if not path.exists():
            continue
        check=json.loads(path.read_text())
        if not check.get('passed') or not check.get('physical'):
            continue
        times=sorted(check['physical'])
        first,last=check['physical'][times[0]],check['physical'][times[-1]]
        def delta(key,relative=False):
            if key not in first or key not in last or first[key] is None or last[key] is None:
                return None
            change=last[key]-first[key]
            return change/abs(first[key]) if relative and first[key] else change
        area=last.get('rain_area_ge_0.1mm_fraction')
        tke=last.get('TKE_max',last.get('TKE_PBL_max'))
        text.append(f'| {case} | {number(last.get("rain_max_mm"))} | {number(area*100 if area is not None else None)} | {number(tke)} | {number(delta("dry_mass_kg",True))} | {number(delta("atmospheric_water_kg"))} | {number(delta("dry_energy_inventory_proxy_j",True))} |')
    golden=run.ART/'golden/manifest.json'
    text.extend(['','Golden reference: '+('published' if golden.exists() else '**not published**')+'.',
                 '', 'PASS in this summary reflects saved reports. `publish.py` rereads current NetCDF files before accepting a golden reference.'])
    return '\n'.join(text)+'\n'


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--labels',nargs='+',default=['baseline','replay'])
    p.add_argument('--output',type=Path,default=Path(__file__).with_name('RESULTS.md'))
    args=p.parse_args()
    args.output.write_text(summarize(args.labels))
    print(args.output)
