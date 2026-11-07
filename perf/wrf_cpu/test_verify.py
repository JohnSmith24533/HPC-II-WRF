"""Adversarial tests: a successful log or matching file list must not hide errors."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest

import netCDF4 as nc
import numpy as np

import verify


class VerificationTests(unittest.TestCase):
    def test_metrics_and_position(self):
        r=np.ma.array(np.zeros((2,3),dtype='f4'))
        a=r.copy(); a[1,2]=2
        m=verify.metrics(a,r)
        self.assertFalse(m['passed'])
        self.assertEqual(m['max_abs'],2)
        self.assertEqual(m['max_location'],[1,2])
        self.assertAlmostEqual(m['rmse'],np.sqrt(4/6))
        self.assertAlmostEqual(m['exceed_fraction'],1/6)

    def test_near_zero_and_variable_tolerance(self):
        a=np.ma.array([1e-8],dtype='f8'); r=np.ma.array([0.],dtype='f8')
        self.assertFalse(verify.metrics(a,r,rtol=1e-3,bitwise=False)['passed'])
        self.assertTrue(verify.metrics(a,r,atol=1e-7,bitwise=False)['passed'])

    def test_bitwise_signed_zero(self):
        self.assertFalse(verify.metrics(np.ma.array([-0.],dtype='f4'),np.ma.array([0.],dtype='f4'))['passed'])

    def test_nan_and_mask_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            verify.metrics(np.ma.array([np.nan]),np.ma.array([np.nan]))
        with self.assertRaises(ValueError):
            verify.metrics(np.ma.array([1.],mask=[True]),np.ma.array([1.]))

    def fixture(self,directory):
        times=['0001-01-01_00:00:00','0001-01-01_00:00:12','0001-01-01_00:00:24']
        path=directory/('wrfout_d01_'+times[0])
        with nc.Dataset(path,'w') as ds:
            for name,size in [('Time',None),('DateStrLen',19),('west_east_stag',3),('south_north_stag',3),('bottom_top_stag',3),('west_east',2),('south_north',2),('bottom_top',2)]:
                ds.createDimension(name,size)
            ds.DX=100.; ds.DY=100.
            t=ds.createVariable('Times','S1',('Time','DateStrLen'))
            for i,s in enumerate(times):
                t[i,:]=np.array(list(s),dtype='S1')
            for name in verify.CORE:
                v=ds.createVariable(name,'f4',('Time','bottom_top','south_north','west_east'))
                v[:]=np.zeros((3,2,2,2),dtype='f4')
                if name=='PB': v[:]=100000.
                if name=='MUB': v[:]=90000.
        meta={'exit_code':0,'start':times[0],'end':times[-1],'dt':12,'history_seconds':12,'grid':[3,3,3],'required':[]}
        (directory/'run.json').write_text(json.dumps(meta))
        (directory/'rsl.out.0000').write_text('\n'.join('Timing for main: time '+s+' on domain 1: 0.1 elapsed seconds' for s in times[1:])+'\nSUCCESS COMPLETE WRF\n')
        return path

    def test_missing_step_is_failure_even_when_model_says_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp); self.fixture(d)
            self.assertTrue(verify.execution(d)['passed'])
            log=d/'rsl.out.0000'; log.write_text(log.read_text().replace('0001-01-01_00:00:12','0001-01-01_00:00:24'))
            self.assertFalse(verify.execution(d)['passed'])

    def test_history_open_error_rejects_success_and_complete_arrays(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);self.fixture(d)
            self.assertTrue(verify.execution(d)['passed'])
            (d/'rsl.error.0001').write_text('open_hist_w : error opening wrfout_d01_0001-01-01_00:00:24 for writing. -1021\n')
            result=verify.execution(d)
            self.assertFalse(result['passed'])
            self.assertIn('WRF history output could not be opened for writing',result['errors'])

    def test_restart_without_initial_history_requires_every_computed_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp); path=self.fixture(d)
            times=['0001-01-01_00:00:12','0001-01-01_00:00:24','0001-01-01_00:00:36']
            with nc.Dataset(path,'a') as ds:
                for i,value in enumerate(times):
                    ds['Times'][i,:]=np.array(list(value),dtype='S1')
            meta=json.loads((d/'run.json').read_text())
            meta.update(end=times[-1],history_at_start=False)
            (d/'run.json').write_text(json.dumps(meta))
            (d/'rsl.out.0000').write_text('\n'.join('Timing for main: time '+value+' on domain 1: 0.1 elapsed seconds' for value in times)+'\nSUCCESS COMPLETE WRF\n')
            self.assertTrue(verify.execution(d)['passed'])
            meta['history_at_start']=True
            (d/'run.json').write_text(json.dumps(meta))
            self.assertFalse(verify.execution(d)['passed'])

    def test_missing_field_and_nonfinite_are_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp); path=self.fixture(d)
            with nc.Dataset(path,'a') as ds:
                ds['U'][1,0,0,0]=np.inf
            self.assertFalse(verify.execution(d)['passed'])
            with nc.Dataset(path,'a') as ds:
                ds['U'][1,0,0,0]=0.
                ds.renameVariable('W','removed_W')
            self.assertFalse(verify.execution(d)['passed'])

    def test_finite_float32_diagnostic_aggregation_uses_float64(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp); path=self.fixture(d)
            with nc.Dataset(path,'a') as ds:
                v=ds.createVariable('LH','f4',('Time','south_north','west_east'))
                v[:]=1e38
            result=verify.execution(d)
            self.assertTrue(all(np.isfinite(v['LH_mean']) for v in result['physical'].values()))
            json.dumps(result,allow_nan=False)

    def test_inactive_flux_missing_data_is_explicitly_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp); path=self.fixture(d)
            with nc.Dataset(path,'a') as ds:
                ds.createVariable('LH','f4',('Time','south_north','west_east'),fill_value=-999.)
            result=verify.execution(d)
            self.assertTrue(result['passed'])
            for frame in result['physical'].values():
                self.assertIsNone(frame['LH_mean'])
                self.assertEqual(frame['LH_available_fraction'],0.)
            json.dumps(result,allow_nan=False)
            self.assertTrue(verify.compare(d,d)['passed'])

    def test_ideal_directional_map_factors_and_physics_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp); path=self.fixture(d)
            with nc.Dataset(path,'a') as ds:
                for name,value in [('MAPFAC_M',0.),('MAPFAC_MX',1.),('MAPFAC_MY',1.)]:
                    v=ds.createVariable(name,'f4',('Time','south_north','west_east'))
                    v[:]=value
                ds.MP_PHYSICS=1
            result=verify.execution(d)
            self.assertTrue(result['passed'])
            self.assertTrue(all(np.isfinite(v['dry_mass_kg']) for v in result['physical'].values()))
            meta=json.loads((d/'run.json').read_text())
            meta['expected_physics']={'mp_physics':6}
            (d/'run.json').write_text(json.dumps(meta))
            self.assertFalse(verify.execution(d)['passed'])

    def test_compare_detects_late_error_and_missing_output_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=Path(tmp)/'c'; r=Path(tmp)/'r'; c.mkdir(); r.mkdir()
            cp=self.fixture(c); self.fixture(r)
            self.assertTrue(verify.compare(c,r)['passed'])
            with nc.Dataset(cp,'a') as ds: ds['U'][2,1,1,1]=1.
            result=verify.compare(c,r)
            self.assertFalse(result['passed'])
            self.assertEqual(next(m for m in result['metrics'] if m['variable']=='U' and m['time'].endswith('24'))['max_abs'],1.)
            with nc.Dataset(cp,'a') as ds:
                ds['U'][2,1,1,1]=0.
                ds['Times'][2,:]=np.array(list('0001-01-01_00:00:36'),dtype='S1')
            self.assertFalse(verify.compare(c,r)['passed'])

    def test_parallel_comparison_preserves_late_failure_and_every_metric(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=Path(tmp)/'c'; r=Path(tmp)/'r'; c.mkdir(); r.mkdir()
            cp=self.fixture(c); self.fixture(r)
            with nc.Dataset(cp,'a') as ds:
                ds['U'][2,1,1,1]=1.
            serial=verify.compare(c,r,workers=1)
            parallel=verify.compare(c,r,workers=2)
            self.assertFalse(parallel['passed'])
            self.assertEqual(serial,parallel)
            with nc.Dataset(cp,'a') as ds:
                ds['U'][2,1,1,1]=0.
            self.assertEqual(verify.compare(c,r,workers=1),verify.compare(c,r,workers=2))

    def test_parallel_worker_nonfinite_failure_propagates(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=Path(tmp)/'c'; r=Path(tmp)/'r'; c.mkdir(); r.mkdir()
            cp=self.fixture(c); self.fixture(r)
            with nc.Dataset(cp,'a') as ds:
                ds['U'][2,1,1,1]=np.inf
            with self.assertRaisesRegex(ValueError,'nonfinite'):
                verify.compare(c,r,workers=2)


if __name__=='__main__':
    unittest.main()
