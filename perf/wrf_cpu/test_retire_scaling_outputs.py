"""Protect canonical data and first-repeat references when bounding scratch storage."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import retire_scaling_outputs
import run


class RetirementTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.art = Path(temporary.name)
        patched = patch.object(run, 'ART', self.art)
        patched.start(); self.addCleanup(patched.stop)

    def fixture(self, label='S005-test-r01-p004', passed=True):
        root = self.art / 'runs' / label / 'les/full'
        root.mkdir(parents=True)
        for name, data in {
            'run.json': {'label': label, 'case': 'les', 'tier': 'full', 'exit_code': 0},
            'check.json': {'passed': passed},
            'cross-rank-compare.json': {'mode': 'bitwise', 'metrics': [{'passed': False}]} }.items():
            (root / name).write_text(json.dumps(data))
        (root / 'namelist.input').write_text('original settings')
        (root / 'wrfout_d01_test').write_bytes(b'history')
        (root / 'wrfrst_d01_test').write_bytes(b'checkpoint')
        return root

    def test_retains_repeat_reference_until_final_comparison(self):
        root = self.fixture()
        self.assertEqual(retire_scaling_outputs.retire(root, keep_history=True), 10)
        self.assertTrue((root / 'wrfout_d01_test').exists())
        self.assertEqual(retire_scaling_outputs.retire(root), 7)
        journal = json.loads((root / 'retired-outputs.json').read_text())
        self.assertEqual(set(journal['files']), {'wrfout_d01_test', 'wrfrst_d01_test'})
        self.assertTrue(all(row['removed'] for row in journal['files'].values()))

    def test_history_prefix_preserves_restart_window_and_checkpoints(self):
        root = self.fixture()
        (root / 'wrfout_d01_test').unlink()
        frames = [('early', ['2019-11-26_12:00:00']),
                  ('boundary', ['2019-11-26_18:00:00']),
                  ('mixed', ['2019-11-26_17:00:00', '2019-11-26_19:00:00'])]
        import numpy as np
        for name, times in frames:
            with run.nc.Dataset(root / ('wrfout_d01_'+name), 'w') as data:
                data.createDimension('Time', len(times)); data.createDimension('DateStrLen', 19)
                var = data.createVariable('Times', 'S1', ('Time', 'DateStrLen'))
                var[:] = np.array([list(stamp) for stamp in times], dtype='S1')
        early = root / 'wrfout_d01_early'
        expected = early.stat().st_size
        freed = retire_scaling_outputs._retire_arrays(root, 'cross-rank-compare.json',
            include_checkpoints=False, history_before='2019-11-26_18:00:00')
        self.assertEqual(freed, expected)
        self.assertFalse(early.exists())
        for name in ['wrfout_d01_boundary', 'wrfout_d01_mixed', 'wrfrst_d01_test']:
            self.assertTrue((root / name).exists())
        journal = json.loads((root / 'retired-outputs.json').read_text())
        self.assertEqual(set(journal['files']), {'wrfout_d01_early'})

    def test_prefix_retirement_rejects_checkpoint_removal_or_bad_history(self):
        root = self.fixture()
        with self.assertRaises(ValueError):
            retire_scaling_outputs._retire_arrays(root, 'cross-rank-compare.json',
                history_before='2019-11-26_18:00:00')
        with self.assertRaises(OSError):
            retire_scaling_outputs._retire_arrays(root, 'cross-rank-compare.json',
                include_checkpoints=False, history_before='2019-11-26_18:00:00')
        self.assertTrue((root / 'wrfout_d01_test').exists())
        self.assertTrue((root / 'wrfrst_d01_test').exists())
        self.assertTrue((root / 'cross-rank-compare.json').exists())

    def test_protects_canonical_and_failed_runs(self):
        for label, passed in [('baseline', True), ('S005-failed-r01-p004', False)]:
            root = self.fixture(label, passed)
            with self.subTest(label=label), self.assertRaises(ValueError):
                retire_scaling_outputs.retire(root)
            self.assertTrue((root / 'wrfout_d01_test').exists())

    def test_candidate_requires_complete_bitwise_pass(self):
        root = self.fixture('C001-lossless-r01-p004')
        comparison = root / 'candidate-compare.json'
        comparison.write_text(json.dumps({'mode': 'bitwise', 'passed': False,
                                         'errors': ['field differs'], 'metrics': [{'passed': False}]}))
        with self.assertRaisesRegex(ValueError, 'failed candidate'):
            retire_scaling_outputs.retire(root)
        self.assertTrue((root / 'wrfout_d01_test').exists())
        comparison.write_text(json.dumps({'mode': 'bitwise', 'passed': True,
                                         'errors': [], 'metrics': [{'passed': True}]}))
        self.assertEqual(retire_scaling_outputs.retire(root), 17)
        journal = json.loads((root / 'retired-outputs.json').read_text())
        self.assertIn('candidate-compare.json', journal['retained_evidence_sha256'])

    def test_rejects_symlink_to_protected_data(self):
        root = self.fixture()
        target = self.art / 'golden-data'
        target.write_bytes(b'protected')
        (root / 'wrfout_d01_test').unlink()
        (root / 'wrfout_d01_test').symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'non-regular'):
            retire_scaling_outputs.retire(root)
        self.assertEqual(target.read_bytes(), b'protected')
        self.assertTrue((root / 'wrfrst_d01_test').exists())


if __name__ == '__main__':
    unittest.main()
