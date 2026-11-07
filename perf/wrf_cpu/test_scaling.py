"""Protect scaling feasibility and the aggregation used to choose trial candidates."""
import unittest
import json
from pathlib import Path
import tempfile
from unittest import mock

import scaling


class ScalingTests(unittest.TestCase):
    def test_mesh_and_minimum_patch(self):
        self.assertEqual(scaling.processor_mesh(32), (4, 8))
        self.assertEqual(scaling.processor_mesh(112), (8, 14))
        self.assertTrue(scaling.fits('les', 16))
        self.assertFalse(scaling.fits('les', 28))
        self.assertTrue(scaling.fits('b_wave', 32))
        self.assertTrue(scaling.fits('conus12', 112))
        self.assertFalse(scaling.fits('conus12',1120))
        self.assertTrue(scaling.fits('conus12',1120,[40,28]))

    def test_layout_matrix_cannot_silently_overwrite_a_trial(self):
        valid=scaling.configurations({'conus12':[{'ranks':1120,'processor_grid':[40,28]}]},['conus12'])
        self.assertEqual(valid['conus12'][0]['processor_grid'],[40,28])
        with self.assertRaisesRegex(ValueError,'distinct rank'):
            scaling.configurations({'conus12':[112,{'ranks':112,'processor_grid':[14,8]}]},['conus12'])
        with self.assertRaisesRegex(ValueError,'factors'):
            scaling.configurations({'conus12':[{'ranks':112,'processor_grid':[14,7]}]},['conus12'])

    def test_invalid_processor_grid_is_rejected_before_creating_run(self):
        with mock.patch.object(scaling.run,'initialize') as initialize:
            with self.assertRaisesRegex(ValueError,'10-cell'):
                scaling.run.run_case('conus12','short','invalid',1120,processor_grid=[28,40])
            initialize.assert_not_called()

    def test_summary_excludes_failed_runs_and_uses_median(self):
        rows = [dict(case='les', tier='short', ranks=4, execution_passed=True,
                     wall_seconds=w, wall_seconds_per_timestep=w/60, mean_step_wall_seconds=0.1,
                     step_median_seconds=0.1, cross_rank_bitwise=True)
                for w in [3., 100., 4.]]
        rows.append(dict(case='les', tier='short', ranks=8, execution_passed=False, wall_seconds=1.))
        rows.append(dict(case='les', tier='full', ranks=4, execution_passed=True,
                         wall_seconds=20., wall_seconds_per_timestep=20./3600, mean_step_wall_seconds=0.1,
                         step_median_seconds=0.1, cross_rank_bitwise=False))
        result = scaling.summaries(rows)
        short = next(r for r in result if r['tier'] == 'short')
        self.assertEqual(len(result), 2)
        self.assertEqual(short['wall_median_seconds'], 4.)
        self.assertEqual(short['repetitions'], 3)
        self.assertAlmostEqual(short['wall_seconds_per_timestep'], 4./60)
        self.assertFalse(next(r for r in result if r['tier'] == 'full')['all_cross_rank_bitwise'])

    def test_completed_trial_cannot_be_reused_with_different_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frozen = root / 'inputs'
            frozen.mkdir()
            (frozen / 'inputs.json').write_text('{}')
            executable = root / 'install-ideal/bin/wrf'
            executable.parent.mkdir(parents=True)
            executable.write_text('test executable')
            dest = root / 'runs/trial/les/short'
            dest.mkdir(parents=True)
            (dest / 'check.json').write_text('{"passed":true}')
            (dest / 'run.json').write_text(json.dumps({
                'ranks': 4, 'executable_sha256': scaling.run.digest(executable),
                'frozen_inputs_sha256': scaling.run.digest(frozen / 'inputs.json')}))
            with mock.patch.object(scaling.run, 'ART', root), mock.patch.object(scaling.run, 'initialize', return_value=frozen):
                with self.assertRaisesRegex(RuntimeError, 'provenance changed'):
                    scaling.run.run_case('les', 'short', 'trial', 4, mpi_options=['--bind-to', 'core'])


if __name__ == '__main__':
    unittest.main()
