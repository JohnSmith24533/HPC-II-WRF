"""Profiling evidence needs actual samples and safe, rank-selective wrappers."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import wrf_profile


class ProfilingTests(unittest.TestCase):
    def test_sample_counts_come_from_report_not_header_only_output(self):
        self.assertEqual(wrf_profile.reported_samples("# Samples: 12  of event 'cycles:u'"), 12)
        self.assertEqual(wrf_profile.reported_samples("# Samples: 1.5K of event 'cycles:u'"), 1500)
        self.assertEqual(wrf_profile.reported_samples("# Samples: 0 of event 'cycles:u'"), 0)
        with self.assertRaises(ValueError):
            wrf_profile.reported_samples('# hostname : node\n# cmdline : perf record')

    def test_unsampled_rank_executes_exact_target_with_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            executable = directory / 'WRF target; harmless'
            executable.write_text('#!/usr/bin/env bash\nprintf "target executed\\n"\n')
            executable.chmod(0o755)
            wrapper = directory / 'wrapper'
            wrapper.write_text(wrf_profile.wrapper_text(executable, directory, 8, 199))
            env = dict(os.environ, OMPI_COMM_WORLD_RANK='5')
            result = subprocess.run(['bash', str(wrapper)], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'target executed\n')


if __name__ == '__main__':
    unittest.main()
