"""Prevent short, irreproducible, or unconfirmed timings becoming a sealed baseline."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import certify_scaled
import run


class CertificationSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        evidence = root / 'results.json'
        evidence.write_text(json.dumps({'experiment': {'status': 'completed'}}))
        self.selection = {'top_per_case': 1, 'experiments': {
            'repeat': {'path': str(evidence), 'sha256': run.digest(evidence)}}, 'cases': {}}
        for case, spec in run.CASES.items():
            steps = spec['full_seconds'] // spec['dt']
            trials = []
            for repeat, wall in enumerate([12., 10., 100.], 1):
                label = f'S005-test-r{repeat:02d}-p004'
                trial = root / label / case / 'full'
                trial.mkdir(parents=True)
                meta = {'label': label, 'case': case, 'tier': 'full', 'exit_code': 0,
                        'ranks': 4, 'processor_grid': None, 'mpi_options': [],
                        'step_timing_seconds': {'count': steps}, 'wall_seconds': wall}
                (trial / 'run.json').write_text(json.dumps(meta))
                (trial / 'check.json').write_text(json.dumps({'passed': True, 'steps': steps}))
                if repeat > 1:
                    (trial / 'repeat-compare.json').write_text(json.dumps({'passed': True, 'mode': 'bitwise'}))
                trials.append(str(trial))
            self.selection['cases'][case] = [{'ranks': 4, 'processor_grid': None, 'mpi_options': [],
                'measured_repetitions': 3, 'source_trials': trials, 'wall_seconds_per_timestep': 12. / steps}]

    def test_confirmed_median_and_all_case_coverage(self):
        self.assertEqual(set(certify_scaled.selected_configurations(self.selection)), set(run.CASES))
        partial = copy.deepcopy(self.selection)
        partial['cases'].pop('conus12')
        with self.assertRaisesRegex(ValueError, 'all five'):
            certify_scaled.selected_configurations(partial)

    def test_rejects_outlier_instead_of_median(self):
        selection = copy.deepcopy(self.selection)
        selection['cases']['les'][0]['wall_seconds_per_timestep'] = 10. / 3600
        with self.assertRaisesRegex(ValueError, 'median'):
            certify_scaled.selected_configurations(selection)

    def test_rejects_duplicate_trials(self):
        config = self.selection['cases']['les'][0]
        config['source_trials'][2] = config['source_trials'][1]
        with self.assertRaisesRegex(ValueError, 'distinct'):
            certify_scaled.selected_configurations(self.selection)

    def test_rejects_missing_or_failed_bitwise_repeat(self):
        trial = Path(self.selection['cases']['les'][0]['source_trials'][1])
        comparison = trial / 'repeat-compare.json'
        for result in [{'passed': False, 'mode': 'bitwise'}, {'passed': True, 'mode': 'per-variable tolerance'}]:
            comparison.write_text(json.dumps(result))
            with self.subTest(result=result), self.assertRaisesRegex(ValueError, 'bitwise'):
                certify_scaled.selected_configurations(self.selection)
        comparison.unlink()
        with self.assertRaisesRegex(ValueError, 'missing independent'):
            certify_scaled.selected_configurations(self.selection)


if __name__ == '__main__':
    unittest.main()
