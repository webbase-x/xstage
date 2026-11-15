"""Regressions for X-Stage Online duplicate progress and idle-looking phase transitions.

These tests are pure Python, require no Tk display, Windows, Google login or media.
"""
import unittest

from karaoke.online_sync_feedback import OnlineSyncFeedback


class OnlineSyncFeedback0949Tests(unittest.TestCase):
    def test_step_one_shows_stage_once_and_scanned_counts_once(self):
        feedback = OnlineSyncFeedback(now=100)
        feedback.signal(100, 500, now=101)
        self.assertEqual(feedback.header, 'ขั้นตอนที่ 1/5 • ตรวจฐานข้อมูลเพลง')
        label = feedback.indicator(now=104)
        self.assertEqual(label.count('100 / 500'), 1)
        self.assertEqual(label.count('20.0%'), 1)
        self.assertNotIn('100 / 500', feedback.header)

    def test_spinner_and_elapsed_time_keep_changing_without_events(self):
        feedback = OnlineSyncFeedback(now=5)
        feedback.begin(3, 'ยืนยันบัญชี Google', now=10)
        first = feedback.indicator(now=11)
        second = feedback.indicator(now=12)
        self.assertNotEqual(first, second)
        self.assertIn('รอการอนุญาตจาก Google ในเบราว์เซอร์', first)
        self.assertIn('1 วินาที', first)
        self.assertIn('2 วินาที', second)

    def test_silent_network_phase_displays_actionable_hint_after_30_seconds(self):
        feedback = OnlineSyncFeedback(now=0)
        feedback.begin(4, 'ตรวจและซิงค์ไฟล์เพลง', now=1)
        self.assertNotIn('ยังไม่ได้รับความคืบหน้าใหม่', feedback.indicator(now=29))
        self.assertIn('ยังไม่ได้รับความคืบหน้าใหม่', feedback.indicator(now=31))
        self.assertIn('กดหยุด', feedback.indicator(now=31))

    def test_duplicate_status_events_do_not_reset_stall_detection(self):
        feedback = OnlineSyncFeedback(now=0)
        feedback.begin(4, 'ซิงค์', now=0)
        feedback.signal(0, 50, now=1)
        feedback.signal(0, 50, now=20)
        self.assertIn('ยังไม่ได้รับความคืบหน้าใหม่', feedback.indicator(now=31))

    def test_actual_song_progress_resets_stall_hint_and_clamps_count(self):
        feedback = OnlineSyncFeedback(now=0)
        feedback.begin(4, 'ซิงค์เพลง', now=1)
        feedback.signal(0, 20, now=2)
        self.assertIn('ยังไม่ได้รับความคืบหน้าใหม่', feedback.indicator(now=35))
        feedback.signal(3, 20, now=36)
        self.assertNotIn('ยังไม่ได้รับความคืบหน้าใหม่', feedback.indicator(now=37))
        feedback.signal(80, 20, now=39)
        self.assertIn('20 / 20 เพลง • 100.0%', feedback.indicator(now=39))

    def test_phase_transition_resets_progress_and_provides_new_header(self):
        feedback = OnlineSyncFeedback(now=0)
        feedback.signal(200, 300, now=2)
        feedback.begin(3, 'ยืนยันบัญชี Google', now=3)
        self.assertEqual((feedback.done, feedback.total), (0, 0))
        self.assertEqual(feedback.header, 'ขั้นตอนที่ 3/5 • ยืนยันบัญชี Google')
        self.assertNotIn('200 / 300', feedback.indicator(now=4))

    def test_invalid_phase_rejected(self):
        feedback = OnlineSyncFeedback(now=0)
        for phase in (-1, 0, 6, 99):
            with self.subTest(phase=phase), self.assertRaises(ValueError):
                feedback.begin(phase, 'ผิดพลาด', now=1)


if __name__ == '__main__':
    unittest.main()


# The following tests are opt-in because Tk requires a display server.
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(os.environ.get('XSTAGE_TEST_GUI') == '1',
                     'Opt-in GUI regression (Windows or xvfb-run)')
class OnlineSyncWindow0949Tests(unittest.TestCase):
    def setUp(self):
        from karaoke.ui import KaraokeApp
        from tests.test_studio import midi_fixture
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / 'samples').mkdir()
        media = root / 'Songs' / '98001.mid'
        media.parent.mkdir()
        media.write_bytes(midi_fixture())
        self.app = KaraokeApp(root, root / 'Data')
        self.app.withdraw()
        self.app.library.add_files([media])
        self.app.web_online_data()
        self.window = self.app._cloud_progress_window
        self.panel = self.window

    def tearDown(self):
        try:
            if self.window.winfo_exists():
                def stop_bars(widget):
                    for child in widget.winfo_children():
                        if child.winfo_class() == 'TProgressbar':
                            child.stop()
                        stop_bars(child)
                stop_bars(self.window)
                self.window.destroy()
            try:
                self.app.after_cancel(self.app.tick_after)
            except (AttributeError, Exception):
                pass
            self.app.destroy()
        finally:
            self.temp.cleanup()

    def pump(self, condition, limit=5):
        import time
        deadline = time.monotonic()+limit
        while time.monotonic()<deadline:
            self.app.update()
            if condition():return True
            time.sleep(.03)
        return False

    def labels(self):
        found=[]
        def walk(parent):
            for w in parent.winfo_children():
                if w.winfo_class()=='TLabel':found.append(w.cget('text'))
                walk(w)
        walk(self.panel)
        return found

    def buttons(self):
        found={}
        def descend(widget):
            for c in widget.winfo_children():
                if c.winfo_class()=='TButton':found[c.cget('text')]=c
                descend(c)
        descend(self.panel)
        return found

    def test_step_one_has_one_phase_label_and_one_progress_line(self):
        self.assertEqual(len([s for s in self.labels()
                              if s.startswith('ขั้นตอนที่ 1/5')]),1)
        self.assertTrue(self.pump(lambda:'ตรวจฐานข้อมูลเสร็จ' in ' '.join(self.labels())))
        self.assertEqual(str(self.app._online_wizard['confirm'].cget('state')),'disabled')
        labels=self.labels()
        self.assertEqual(len([s for s in labels if 'เพลงพร้อมซิงก์' in s]),1)
        self.assertEqual(len([s for s in labels if 'ตรวจฐานข้อมูลเสร็จ' in s]),1)

    def test_network_waiting_heartbeat_changes_without_fake_progress(self):
        import time
        account=self.app.google_account
        account.credentials=('token','owner@example.com','refresh',time.monotonic()+3600)
        account.profile={'email':'owner@example.com','name':'Owner'}
        wizard=self.app._online_wizard
        wizard['login_button'].invoke()
        self.assertEqual(wizard['page']['name'],'settings')
        self.assertTrue(self.pump(lambda:str(wizard['confirm'].cget('state'))=='normal'))
        entered=threading.Event()
        def waiting_drive(*args,**kwargs):
            entered.set()
            while not kwargs['cancel'].is_set():time.sleep(.015)
            raise RuntimeError('ยกเลิกตามคำสั่งผู้ใช้')
        with patch('karaoke.web_environment.prepare_online_renderer',return_value=({},'pc.sf2','ffmpeg',1)), \
             patch('karaoke.google_drive_sync.load_client',return_value=('client','secret')), \
             patch('karaoke.google_drive_sync.Drive',return_value=object()), \
             patch('karaoke.web_drive.sync_web_assets',side_effect=waiting_drive):
            wizard['confirm'].invoke()
            self.assertTrue(self.pump(lambda:entered.is_set() and
                any('ขั้นตอนที่ 4/5' in text for text in self.labels())))
            def heartbeat():
                values=[x for x in self.labels() if 'วินาที' in x and '●' in x]
                return values[-1] if values else ''
            before=heartbeat()
            self.assertTrue(self.pump(lambda:heartbeat() and heartbeat()!=before,limit=2.5))
            self.assertNotIn('100.0%',heartbeat())
            self.buttons()['หยุด'].invoke()
            self.assertTrue(self.pump(lambda:'ซิงก์ใหม่' in self.buttons()))
            self.assertTrue(any('หยุดซิงก์แล้ว' in t for t in self.labels()))
