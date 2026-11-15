"""R12 regressions: online three steps fit small displays; completed songs clear lyrics."""
import os
import time
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

@unittest.skipUnless(os.environ.get('XSTAGE_TEST_GUI')=='1','Needs Tk display')
class OnlineWizardR12Tests(unittest.TestCase):
    def setUp(self):
        from karaoke.ui import KaraokeApp
        from tests.test_studio import midi_fixture
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        (root/'samples').mkdir()
        song=root/'Songs'/'12345.mid';song.parent.mkdir();song.write_bytes(midi_fixture())
        with patch('karaoke.google_session.has_saved_session',return_value=False):
            self.app=KaraokeApp(root,root/'Data')
        self.app.library.add_files([song]);self.app.withdraw()
    def tearDown(self):
        w=self.app._cloud_progress_window
        if w is not None and w.winfo_exists():w.destroy()
        try:self.app.after_cancel(self.app.tick_after)
        except Exception:pass
        self.app.destroy();self.tmp.cleanup()
    def pump(self,condition=lambda:True,timeout=4):
        limit=time.monotonic()+timeout
        while time.monotonic()<limit:
            self.app.update();time.sleep(.012)
            if condition():return True
        return False
    def wizard_with_account(self):
        self.app.web_online_data();wizard=self.app._online_wizard
        account=self.app.google_account
        account.credentials=('token','owner@example.com','refresh',time.monotonic()+3600)
        account.profile={'email':'owner@example.com','name':'X-Stage Owner'}
        wizard['login_button'].invoke()
        self.assertTrue(self.pump(lambda:str(wizard['confirm'].cget('state'))=='normal'))
        return wizard
    def test_three_pages_and_progress_has_verified_identity(self):
        wizard=self.wizard_with_account()
        self.assertEqual(wizard['page']['name'],'settings')
        wizard['show']('progress');self.pump()
        self.assertEqual(wizard['page']['name'],'progress')
        self.assertEqual(wizard['progress'].winfo_manager(),'place')
        self.assertEqual(wizard['settings'].winfo_manager(),'')
        self.assertIsNotNone(wizard['progress_bar'])
        self.assertNotIn('OAuth',' '.join(str(b.cget('text')) for b in
            (wizard['confirm'],wizard['progress_pause'])))
        self.assertTrue(wizard['progress_bar'].winfo_ismapped())
    def test_small_window_keeps_controls_inside_compact_pages(self):
        wizard=self.wizard_with_account();window=self.app._cloud_progress_window
        for width,height in [(480,380),(320,310),(810,500)]:
            window.geometry(f'{width}x{height}+5+5')
            self.pump()
            for name in ('settings','progress','login'):
                wizard['show'](name);self.pump()
                frame=wizard[name]
                self.assertLessEqual(frame.winfo_width(),window.winfo_width()+3)
                # Every step occupies the window without an interactive scrollbar.
                self.assertGreater(frame.winfo_height(),100)
    def test_no_queue_completion_releases_engine_and_previous_lyrics(self):
        from karaoke.ui import KaraokeApp
        from karaoke.lyrics import Lyrics
        app=self.app
        fake=Mock();app.engine=fake
        app.current_song={'title':'เพลงเดิม'};app.current_item=object()
        app.song_queue.items.clear();app.now_var.set('เพลงเดิม')
        app.lyrics=Lyrics()
        KaraokeApp.on_song_ended(app)
        fake.close.assert_called_once()
        self.assertIsNone(app.current_song)
        self.assertIsNone(app.engine)
        self.assertEqual(app.now_var.get(),'')
        self.assertEqual(app.preview.state[0],'พร้อมร้องเพลง')
    def test_tick_routes_ended_song_to_completion(self):
        from karaoke.ui import KaraokeApp
        app=self.app
        fake=Mock();fake.position=15;fake.duration=30;fake.ended=True
        app.engine=fake
        with patch.object(app,'on_song_ended') as finished, patch.object(app,'after',return_value='fake'):
            KaraokeApp._tick_once(app)
        finished.assert_called_once_with()

if __name__=='__main__':unittest.main()
