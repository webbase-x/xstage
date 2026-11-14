"""R17: all 5 progress and Drive quota bars share the same x/w and status column."""
from __future__ import annotations
import os
import unittest
from tests import test_online_compact_r16 as compact_suite

@unittest.skipUnless(os.environ.get('XSTAGE_TEST_GUI')=='1', 'Requires GUI display')
class AlignedWizardR17Tests(unittest.TestCase):
    def setUp(self):
        compact_suite.CompactWizardR16Tests.setUp(self)

    def tearDown(self):
        compact_suite.CompactWizardR16Tests.tearDown(self)

    def test_one_bar_spans_compact_window_and_capacity_text_stays_inside(self):
        # R18.1 retains the R17 compact layout but replaces all five visible
        # percentages with a single overall bar and two capacity text lines.
        self.wizard['show']('progress')
        for width,height in ((680,460),(480,380),(320,310)):
            with self.subTest(size=(width,height)):
                self.window.geometry(f'{width}x{height}+10+10')
                compact_suite.CompactWizardR16Tests.pump(self,.15)
                bar=self.wizard['progress_bar']
                bars=[item for item in compact_suite.CompactWizardR16Tests._descendants(self.wizard['progress'])
                      if item.winfo_class()=='TProgressbar' and item.winfo_ismapped()]
                self.assertEqual(bars,[bar])
                self.assertGreater(bar.winfo_width(),100)
                self.assertLessEqual(bar.winfo_rootx()+bar.winfo_width(),
                                     self.window.winfo_rootx()+self.window.winfo_width()+1)
                for value,_note in self.wizard['storage_views'].values():
                    self.assertTrue(value.winfo_ismapped())
                    self.assertLessEqual(value.winfo_rootx()+value.winfo_width(),
                                         self.window.winfo_rootx()+self.window.winfo_width()+1)

if __name__ == '__main__': unittest.main()
