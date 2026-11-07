"""Reject matching CPU names when NUMA/cache topology differs."""
import unittest

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


if __name__=='__main__':
    unittest.main()
