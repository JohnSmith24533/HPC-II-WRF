"""Reject matching CPU names when NUMA/cache topology differs."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import hardware


class HardwareTests(unittest.TestCase):
    def cpu(self):
        values={key:'same' for key in hardware.REQUIRED}
        values.update({'NUMA node(s):':'2','NUMA node0 CPU(s):':'0-55','NUMA node1 CPU(s):':'56-111',
                       'CPU MHz:':'800.000'})
        return {'lscpu':[{'field':key,'data':value} for key,value in values.items()]}

    def test_detects_numa_difference_with_identical_cpu_name(self):
        reference=self.cpu(); actual=self.cpu()
        actual['lscpu'].append({'field':'NUMA node(s):','data':'8'})
        mismatch=hardware.differences(hardware.signature(actual),hardware.signature(reference))
        self.assertEqual(mismatch['NUMA node(s):'],{'actual':'8','expected':'2'})

    def test_excludes_transient_clock_but_checks_maximum_clock(self):
        reference=self.cpu(); actual=self.cpu()
        actual['lscpu'].append({'field':'CPU MHz:','data':'2001.000'})
        self.assertEqual(hardware.differences(hardware.signature(actual),hardware.signature(reference)),{})
        actual['lscpu'].append({'field':'CPU max MHz:','data':'3800.000'})
        self.assertIn('CPU max MHz:',hardware.differences(hardware.signature(actual),hardware.signature(reference)))

    def test_rejects_incomplete_topology(self):
        with self.assertRaisesRegex(ValueError,'incomplete'):
            hardware.signature({'lscpu':[{'field':'Model name:','data':'same'}]})

    def test_selected_and_sealed_reference_signatures(self):
        expected=hardware.signature(self.cpu())
        self.assertEqual(hardware.reference_signature({'hardware_signature':expected}),expected)
        plan={'hardware_by_case':{'les':expected}}
        self.assertEqual(hardware.reference_signature(plan,'les'),expected)
        with self.assertRaisesRegex(ValueError,'known case'):
            hardware.reference_signature(plan)
        with self.assertRaisesRegex(ValueError,'incomplete'):
            hardware.reference_signature({'hardware_signature':{'NUMA node(s):':'2'}})

    def test_original_experiment_reference_signature(self):
        document={'experiment':{'lscpu':self.cpu()}}
        self.assertEqual(hardware.reference_signature(document),hardware.signature(self.cpu()))

    def audit_fixture(self,directory):
        reference=directory/'reference.json'
        expected=hardware.signature(self.cpu())
        reference.write_text(json.dumps({'hardware_signature':expected}))
        report={'host':'node1','job_id':'123','lscpu':self.cpu(),
                'hardware_signature':expected,'expected_signature':expected,
                'reference':str(reference.resolve()),
                'reference_sha256':hashlib.sha256(reference.read_bytes()).hexdigest(),
                'passed':True,'differences':{}}
        other=copy.deepcopy(report);other['host']='node2'
        return reference,[report,other]

    def test_collects_complete_node_reports_without_remote_file_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);reference,reports=self.audit_fixture(directory)
            reports[0]['padding']='x'*9000
            completed=[subprocess.CompletedProcess([],0,stdout=json.dumps(r,indent=2)) for r in reports]
            with patch.dict(os.environ,SLURM_JOB_ID='123',SLURM_JOB_NUM_NODES='2',SLURM_JOB_NODELIST='node[1-2]'), \
                    patch.object(hardware.subprocess,'check_output',return_value='node1\nnode2\n'), \
                    patch.object(hardware.subprocess,'run',side_effect=completed) as called:
                hardware.audit_allocation(reference,directory/'output')
            self.assertEqual(len(called.call_args_list),2)
            for index,call in enumerate(called.call_args_list,1):
                command=call.args[0]
                self.assertIn('--stdout',command)
                self.assertNotIn('--output-dir',command)
                self.assertIn('--nodes=1',command)
                self.assertIn('--nodelist=node'+str(index),command)
                self.assertLess(command.index('--nodelist=node'+str(index)),command.index(hardware.sys.executable))
            self.assertEqual([json.loads((directory/'output'/(r['host']+'.json')).read_text()) for r in reports],reports)

    def test_missing_duplicate_or_unsafe_hosts_cannot_publish_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);reference,reports=self.audit_fixture(directory)
            unsafe=copy.deepcopy(reports);unsafe[1]['host']='../outside'
            for values in [reports[:1],[reports[0],reports[0]],unsafe]:
                with self.subTest(hosts=[r['host'] for r in values]):
                    completed=[subprocess.CompletedProcess([],0,stdout=json.dumps(r)) for r in values]+[subprocess.CompletedProcess([],0,stdout='')]
                    with patch.dict(os.environ,SLURM_JOB_ID='123',SLURM_JOB_NUM_NODES='2',SLURM_JOB_NODELIST='node[1-2]'), \
                            patch.object(hardware.subprocess,'check_output',return_value='node1\nnode2\n'), \
                            patch.object(hardware.subprocess,'run',side_effect=completed), \
                            self.assertRaises(RuntimeError):
                        hardware.audit_allocation(reference,directory/'output')
                    self.assertFalse((directory/'output').exists())

    def test_report_claims_cannot_hide_wrong_job_reference_or_topology(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);reference,reports=self.audit_fixture(directory)
            variants=[]
            for key,value in [('job_id','124'),('reference_sha256','wrong'),('passed',False)]:
                changed=copy.deepcopy(reports);changed[1][key]=value;variants.append(changed)
            changed=copy.deepcopy(reports)
            changed[1]['lscpu']['lscpu'].append({'field':'NUMA node(s):','data':'8'})
            variants.append(changed)
            for values in variants:
                completed=[subprocess.CompletedProcess([],0,stdout=json.dumps(r)) for r in values]
                with patch.dict(os.environ,SLURM_JOB_ID='123',SLURM_JOB_NUM_NODES='2',SLURM_JOB_NODELIST='node[1-2]'), \
                        patch.object(hardware.subprocess,'check_output',return_value='node1\nnode2\n'), \
                        patch.object(hardware.subprocess,'run',side_effect=completed), \
                        self.assertRaises(RuntimeError):
                    hardware.audit_allocation(reference,directory/'output')
                self.assertFalse((directory/'output').exists())


if __name__=='__main__':
    unittest.main()
