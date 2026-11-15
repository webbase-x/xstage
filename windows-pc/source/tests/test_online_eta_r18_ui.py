"""R18.1: one bar, honest ETA, Thai-capable page headers; no worker changes."""
from __future__ import annotations

from datetime import datetime
import math
import os
import unittest

from karaoke.online_eta import OverallSyncEstimate, readable_duration


class OverallSyncEstimateTests(unittest.TestCase):
    def setUp(self):
        self.estimate=OverallSyncEstimate()
        self.wall=datetime(2026,11,10,1,32)

    def tick(self, now, *, running=True, completed=False, step=4,
             done=0, total=100, unit='เพลง', message='กำลังอัปโหลด M4A และ Lyrics JSON'):
        return self.estimate.observe(running=running,completed=completed,
            step=step,done=done,total=total,unit=unit,message=message,
            now=now,wall_clock=self.wall)

    def test_no_fake_percent_from_preflight_row_scanning(self):
        self.assertEqual(self.tick(0,step=2,done=100,total=100)[0],0)
        self.assertEqual(self.tick(1,done=250,total=250,unit='แถวฐานเพลง')[0],0)
        self.assertEqual(self.tick(2,done=10,total=100, message='กำลังตรวจไฟล์ต้นทาง 10 แถวฐานเพลง')[0],0)

    def test_uses_real_completed_song_work_not_phase_count(self):
        self.assertEqual(self.tick(0,done=0)[0],0)
        pct,eta=self.tick(12,done=12)
        self.assertAlmostEqual(pct,11.4)
        self.assertIn('คาดว่าเสร็จราว',eta)
        self.assertIn('อีกประมาณ',eta)
        self.assertNotIn('00:00',eta)

    def test_eta_waits_for_multiple_real_updates(self):
        self.tick(0,done=0)
        self.assertIn('กำลังวัด',self.tick(6,done=2)[1])
        self.assertIn('กำลังวัด',self.tick(7,done=3)[1])
        self.assertIn('คาดว่า',self.tick(10,done=5)[1])

    def test_completion_is_only_100_when_worker_confirms_success(self):
        self.tick(0,done=0)
        self.assertEqual(self.tick(20,done=100)[0],95)
        self.assertEqual(self.tick(22,step=5,done=100,total=100)[0],95)
        self.assertEqual(self.tick(24,step=5,done=100,total=100,
            message='ตรวจความครบของเพลงเว็บ: 100/100')[0],99)
        self.assertEqual(self.tick(26,step=5,running=False,completed=True)[0],100)

    def test_error_and_cancellation_never_look_successful(self):
        self.tick(0,done=0)
        self.tick(10,done=30)
        pct,_=self.tick(12,running=False,completed=False)
        self.assertLess(pct,100)
        pct,_=self.tick(13,running=True,step=2)
        self.assertEqual(pct,0)

    def test_no_eta_if_stuck_without_completed_work(self):
        self.tick(0,done=0)
        pct,eta=self.tick(3600,done=0)
        self.assertEqual(pct,0)
        self.assertNotIn('คาดว่าเสร็จ',eta)

    def test_integrity_verification_counts_are_not_catalog_completion(self):
        self.tick(0,done=0)
        self.tick(10,done=20)
        pct,eta=self.tick(15,step=5,total=100,done=100,message='Catalog ฉบับสมบูรณ์')
        self.assertEqual(pct,95)
        self.assertNotIn('คาดว่าเสร็จ',eta)
        self.tick(20,step=5,total=100,done=5,message='ตรวจความครบของเพลงเว็บ: 5/100')
        pct,eta=self.tick(40,step=5,total=100,done=25,message='ตรวจความครบของเพลงเว็บ: 25/100')
        self.assertEqual(pct,96)
        self.assertIn('คาดว่าเสร็จ',eta)

    def test_readable_duration_bounds(self):
        self.assertEqual(readable_duration(0),'1 นาที')
        self.assertEqual(readable_duration(75),'2 นาที')
        self.assertEqual(readable_duration(3700),'1 ชม. 2 นาที')
        self.assertEqual(readable_duration(float('inf')),'ยังประเมินไม่ได้')


@unittest.skipUnless(os.environ.get('XSTAGE_TEST_GUI')=='1','Needs GUI display')
class OnlineR18OneBarWindowTests(unittest.TestCase):
    def setUp(self):
        from tests.test_online_compact_r16 import CompactWizardR16Tests
        self.legacy=CompactWizardR16Tests()
        self.legacy.setUp()
        self.wizard=self.legacy.wizard
        self.app=self.legacy.app

    def tearDown(self):
        self.legacy.tearDown()

    def test_percent_and_eta_refresh_from_worker_feedback(self):
        from unittest.mock import patch
        from tests.test_online_compact_r16 import CompactWizardR16Tests
        self.wizard['show']('progress')
        with patch('karaoke.online_wizard.OverallSyncEstimate.observe',
                   return_value=(42.7, 'คาดว่าเสร็จราว 02:15 น. (อีกประมาณ 10 นาที)')):
            CompactWizardR16Tests.pump(self.legacy,.65)
        self.assertAlmostEqual(float(self.wizard['progress_bar'].cget('value')),42.7)
        self.assertEqual(self.wizard['progress_percent'].cget('text'),'42.7%')
        self.assertIn('02:15',self.wizard['progress_eta'].cget('text'))

    def test_thai_titles_and_one_bar_preserve_quota(self):
        from tests.test_online_compact_r16 import CompactWizardR16Tests
        for page in ('login','settings','progress'):
            self.wizard['show'](page)
            CompactWizardR16Tests.pump(self.legacy,.13)
            frame={'login':self.wizard['login'], 'settings':self.wizard['settings'],
                   'progress':self.wizard['progress']}[page]
            labels=[w for w in CompactWizardR16Tests._descendants(frame)
                    if w.winfo_class()=='TLabel']
            titles=[w for w in labels if str(w.cget('text')).startswith('ขั้นตอน ')]
            self.assertEqual(len(titles),1)
            self.assertIn('Tahoma',str(titles[0].cget('font')))
        bar=self.wizard['progress_bar']
        bars=[w for w in CompactWizardR16Tests._descendants(self.wizard['progress'])
              if w.winfo_ismapped() and w.winfo_class()=='TProgressbar']
        self.assertEqual(bars,[bar])
        self.assertEqual(len(self.wizard['storage_views']),2)
        self.assertTrue(self.wizard['progress_eta'].winfo_ismapped())

if __name__ == '__main__':
    unittest.main()
