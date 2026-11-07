"""Prevent favorable partial/short timings from becoming a scaling baseline."""
import unittest

import select_finalists


class FinalistTests(unittest.TestCase):
    def row(self,ranks,time,grid=None):
        return {'case':'case','tier':'full','execution_passed':True,'ranks':ranks,
                'wall_seconds_per_timestep':time,'processor_grid':grid,'directory':str((ranks,time,grid))}

    def test_uses_repeated_medians_not_fastest_outlier(self):
        rows=[self.row(4,t) for t in [10.,12.,100.]]+[self.row(8,t) for t in [11.,11.,11.]]
        chosen=select_finalists.choose(rows,['case'],1)['case'][0]
        self.assertEqual(chosen['ranks'],8)
        self.assertEqual(chosen['measured_repetitions'],3)

    def test_partial_or_failed_work_cannot_select_finalists(self):
        for change in [{'tier':'short'},{'execution_passed':False},{'error':'late failure'},
                       {'wall_seconds_per_timestep':float('nan')},{'wall_seconds_per_timestep':0.}]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                select_finalists.choose([{**self.row(4,1.),**change}],['case'],1)
        with self.assertRaisesRegex(ValueError,'all five'):
            select_finalists.choose([self.row(4,1.)],['case','missing'],1)

    def test_same_rank_different_layouts_remain_distinct(self):
        chosen=select_finalists.choose([self.row(112,3.),self.row(112,2.,[14,8])],['case'],2)['case']
        self.assertEqual(len(chosen),2)
        self.assertEqual(chosen[0]['processor_grid'],[14,8])

    def test_near_ties_are_repeated_before_excluding_a_configuration(self):
        rows=[self.row(rank,time) for rank,time in enumerate([1.,1.01,1.02,1.025,1.04],1)]
        chosen=select_finalists.choose(rows,['case'],3,near_best_fraction=.03)['case']
        self.assertEqual([r['ranks'] for r in chosen],[1,2,3,4])
        # Final winner selection remains a single median winner when no window is requested.
        self.assertEqual(len(select_finalists.choose(rows,['case'],1)['case']),1)
        for window in [-.01,float('nan'),float('inf')]:
            with self.subTest(window=window),self.assertRaises(ValueError):
                select_finalists.choose(rows,['case'],3,window)

    def test_cross_rank_numeric_differences_cannot_hide_missing_data(self):
        report={'mode':'bitwise','metrics':[{'time':'time','variable':'T','passed':False}],
                'errors':['time: T differs']}
        select_finalists.validate_cross_rank(report)
        for error in ['variable names, dimensions, shape or dtype differ',
                      'output time coverage differs','time: nonnumeric field differs: Times']:
            with self.subTest(error=error),self.assertRaisesRegex(ValueError,'structural'):
                select_finalists.validate_cross_rank({**report,'errors':[*report['errors'],error]})

    def test_placement_variants_get_separate_repeat_plans(self):
        packed={'processor_grid':None,'mpi_options':['--bind-to','core','--map-by','core','--report-bindings']}
        spread={**packed,'mpi_options':['--bind-to','core','--map-by','package:SPAN','--report-bindings']}
        self.assertEqual(select_finalists.repeat_family('les',packed),('ideal-core','core'))
        self.assertEqual(select_finalists.repeat_family('les',spread),('ideal-spread','package:SPAN'))
        with self.assertRaises(ValueError):
            select_finalists.repeat_family('les',{'processor_grid':None,'mpi_options':[]})


if __name__=='__main__':
    unittest.main()
