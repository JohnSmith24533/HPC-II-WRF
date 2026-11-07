"""Diagnostic cleanup must never accept a partial/failed comparison or live job."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import retire_diagnostic_outputs as cleanup
import run


class DiagnosticRetirementTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.art = Path(temporary.name)
        mocked = patch.object(run, 'ART', self.art); mocked.start(); self.addCleanup(mocked.stop)
        mocked = patch.object(cleanup.subprocess, 'check_output', return_value='42|COMPLETED|0:0|\n')
        self.accounting = mocked.start(); self.addCleanup(mocked.stop)
        payload = self.art/'model'; payload.write_bytes(b'model')
        harness = self.art/'harness.py'; harness.write_text('source')
        group = self.art/'experiments/D009-test/real/results.json'; group.parent.mkdir(parents=True)
        rows = []
        report = {'mode':'bitwise','passed':True,'errors':[],'metrics':[{'passed':True}]}
        self.directories = {}
        for tier in ['single','short','full','restart']:
            directory = self.art/'runs/D009-test/conus12'/tier; directory.mkdir(parents=True)
            self.directories[tier] = directory
            (directory/'run.json').write_text(json.dumps({'label':'D009-test','case':'conus12','tier':tier,'exit_code':0,'job_id':'42'}))
            (directory/'check.json').write_text(json.dumps({'passed':True}))
            (directory/('restart-compare.json' if tier=='restart' else 'diagnostic-compare.json')).write_text(json.dumps(report))
            (directory/'namelist.input').write_text('original settings')
            (directory/'wrfout_d01_test').write_bytes(b'history')
            rows.append({'case':'conus12','tier':tier,'directory':str(directory),'passed':True})
        (self.directories['full']/'wrfrst_d01_test').write_bytes(b'checkpoint')
        (self.directories['restart']/'wrfrst_d01_test').symlink_to(self.directories['full']/'wrfrst_d01_test')
        self.group = group
        self.data = {'label':'D009-test','status':'completed','job_id':'42','diagnostic_only':True,
                     'timings_excluded':True,'all_executed_checks_passed':True,'runs':rows,
                     'payload_sha256':{str(payload):run.digest(payload)},
                     'harness_sha256':{str(harness):run.digest(harness)}}
        self.save()

    def save(self):
        self.group.write_text(json.dumps(self.data))

    def assert_preserved(self):
        for directory in self.directories.values():
            self.assertTrue((directory/'wrfout_d01_test').is_file())
        self.assertTrue((self.directories['full']/'wrfrst_d01_test').is_file())

    def test_successful_all_tier_group_has_durable_provenance(self):
        self.assertEqual(cleanup.retire_group(self.group),38)
        for directory in self.directories.values():
            journal=json.loads((directory/'retired-outputs.json').read_text())
            self.assertEqual(journal['diagnostic_provenance']['group_sha256'],run.digest(self.group))
            self.assertTrue(all(row['removed'] for row in journal['files'].values()))
            self.assertFalse((directory/'wrfout_d01_test').exists())
        self.assertTrue((self.directories['restart']/'wrfrst_d01_test').is_symlink())

    def test_failed_restart_preserves_every_tier(self):
        p=self.directories['restart']/'restart-compare.json';a=json.loads(p.read_text())
        a['passed']=False;a['metrics'][0]['passed']=False;p.write_text(json.dumps(a))
        with self.assertRaisesRegex(ValueError,'scientific comparison'):cleanup.retire_group(self.group)
        self.assert_preserved()

    def test_live_job_and_incomplete_group_are_protected(self):
        self.accounting.return_value='42|RUNNING|0:0|\n'
        with self.assertRaisesRegex(ValueError,'terminal accounting'):cleanup.retire_group(self.group)
        self.assert_preserved()
        self.accounting.return_value='42|COMPLETED|0:0|\n'
        self.data['runs'].pop();self.save()
        with self.assertRaisesRegex(ValueError,'all four'):cleanup.retire_group(self.group)
        self.assert_preserved()

    def test_changed_payload_and_canonical_rows_are_protected(self):
        (self.art/'model').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'payload or harness'):cleanup.retire_group(self.group)
        self.assert_preserved()
        (self.art/'model').write_bytes(b'model')
        directory=self.directories['full'];p=directory/'run.json';a=json.loads(p.read_text())
        a['label']='baseline';p.write_text(json.dumps(a))
        with self.assertRaisesRegex(ValueError,'non-scratch'):cleanup.retire_group(self.group)
        self.assert_preserved()


if __name__=='__main__':unittest.main()
