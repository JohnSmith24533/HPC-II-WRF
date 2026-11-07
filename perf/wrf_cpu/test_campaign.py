"""Scheduler observation gaps must not duplicate experiments or bypass failure gates."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import campaign


class CampaignTests(unittest.TestCase):
    def fixture(self, root):
        plan = root / 'plan.json'
        plan.write_text(json.dumps([
            {'name': 'existing', 'existing_job': '123', 'result': 'existing.json'},
            {'name': 'next', 'sbatch': ['job.sh'], 'result': 'next.json'}]))
        artifacts = root / '.wrf-cpu'
        artifacts.mkdir()
        for name in ('existing', 'next'):
            (artifacts / (name + '.json')).write_text(json.dumps({
                'experiment': {'status': 'completed'}, 'runs': [{'execution_passed': True}]}))
        return ['campaign.py', '--plan', str(plan), '--state', str(root / 'state.json')]

    def test_observation_gap_keeps_job_and_submits_next_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            argv = self.fixture(root)
            observations = [subprocess.TimeoutExpired('sacct', 20), (None, None),
                            ('RUNNING', '0:0'), ('COMPLETED', '0:0'), ('COMPLETED', '0:0')]
            submitted = subprocess.CompletedProcess(['sbatch'], 0, '456\n', '')
            with mock.patch.object(campaign, 'ROOT', root), mock.patch('sys.argv', argv), \
                 mock.patch.object(campaign, 'job_state', side_effect=observations) as observe, \
                 mock.patch.object(campaign.time, 'sleep'), \
                 mock.patch.object(campaign.subprocess, 'run', return_value=submitted) as submit:
                campaign.main()
            self.assertEqual([c.args[0] for c in observe.call_args_list], ['123', '123', '123', '123', '456'])
            self.assertEqual(submit.call_count, 1)
            self.assertEqual(json.loads((root / 'state.json').read_text())['status'], 'campaign_complete')

    def test_failed_job_prevents_next_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            argv = self.fixture(root)
            with mock.patch.object(campaign, 'ROOT', root), mock.patch('sys.argv', argv), \
                 mock.patch.object(campaign, 'job_state', return_value=('FAILED', '1:0')), \
                 mock.patch.object(campaign.subprocess, 'run') as submit:
                with self.assertRaisesRegex(RuntimeError, 'stage failed'):
                    campaign.main()
            submit.assert_not_called()

    def test_profiles_require_verified_values_and_useful_sampling_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports=[Path(tmp)/name for name in ['flat.txt','callgraph.txt']]
            for path in reports:path.write_text('retained profiling report')
            evidence={'status':'completed','profile_only':True,'numerical_comparison_passed':True,
                      'sampled_ranks':[0],'samples_by_rank':{'0':150.},'reports':list(map(str,reports))}
            self.assertTrue(campaign.evidence_complete(evidence,True))
            for change in [{'numerical_comparison_passed':False},{'samples_by_rank':{'0':99.}},
                           {'samples_by_rank':{'0':float('nan')}},{'reports':[]},{'status':'failed'}]:
                with self.subTest(change=change):
                    self.assertFalse(campaign.evidence_complete({**evidence,**change},True))
            reports[0].unlink()
            self.assertFalse(campaign.evidence_complete(evidence,True))


if __name__ == '__main__':
    unittest.main()
