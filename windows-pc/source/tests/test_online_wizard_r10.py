"""R10 online-only Google login / sync confirmation UI and recovery guard.
GUI tests use XSTAGE_TEST_GUI=1 and xvfb-run or Windows display.
"""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from tests.test_studio import midi_fixture

@unittest.skipUnless(os.environ.get('XSTAGE_TEST_GUI') == '1', 'Needs Tk GUI display')
class OnlineWizardR10Tests(unittest.TestCase):
    def setUp(self):
        from karaoke.ui import KaraokeApp
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / 'samples').mkdir()
        song = root / 'Songs' / '12345.mid'
        song.parent.mkdir()
        song.write_bytes(midi_fixture())
        with patch('karaoke.google_session.has_saved_session', return_value=False):
            self.app = KaraokeApp(root, root / 'Data')
        self.app.library.add_files([song])
        self.app.withdraw()
    def tearDown(self):
        try:
            w = self.app._cloud_progress_window
            if w is not None and w.winfo_exists(): w.destroy()
            self.app.after_cancel(self.app.tick_after)
            self.app.destroy()
        finally:
            self.tmp.cleanup()
    def pump(self, predicate=lambda:True, seconds=4):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            self.app.update()
            if predicate():return True
            time.sleep(.015)
        return False
    def test_login_only_inside_online_and_separate_steps(self):
        account=self.app.google_account
        self.assertEqual(account.bar.winfo_manager(), '')
        self.assertEqual(account.home.winfo_manager(), '')
        self.app.web_online_data()
        wizard=self.app._online_wizard
        self.assertEqual(wizard['page']['name'], 'login')
        self.assertEqual(wizard['login'].winfo_manager(), 'place')
        self.assertEqual(wizard['settings'].winfo_manager(), '')
        account.credentials=('access','owner@gmail.com','refresh',time.monotonic()+3600)
        account.profile={'email':'owner@gmail.com', 'name':'Owner Name'}
        wizard['login_button'].invoke()
        self.assertEqual(wizard['page']['name'],'settings')
        self.pump(lambda:str(wizard['confirm'].cget('state'))=='normal',seconds=4)
        self.assertEqual(wizard['settings'].winfo_manager(),'place')
        self.assertEqual(str(wizard['confirm'].cget('state')),'normal')
        self.assertNotIn('OAuth', ' '.join(b.cget('text') for b in self._buttons()))
    def _buttons(self):
        found=[]
        def walk(w):
            for child in w.winfo_children():
                if child.winfo_class()=='TButton':found.append(child)
                walk(child)
        walk(self.app._cloud_progress_window)
        return found
    def test_close_before_login_keeps_database_and_no_worker(self):
        self.app.web_online_data()
        window=self.app._cloud_progress_window
        window.tk.call(window.protocol('WM_DELETE_WINDOW'))
        self.pump(lambda:self.app._cloud_progress_window is None)
        self.assertIsNone(self.app._cloud_progress_window)
        self.assertFalse(self.app._cloud_backup_busy)
        self.assertTrue(self.app.library.has_songs())
        self.app.web_online_data()
        self.assertEqual(self.app._online_wizard['page']['name'],'login')
    def test_confirm_requires_login_and_nonempty_selection(self):
        self.app.web_online_data()
        wizard=self.app._online_wizard
        wizard['show']('settings')
        self.pump()
        self.assertEqual(str(wizard['confirm'].cget('state')),'disabled')
        self.assertEqual(wizard['page']['name'],'settings')

if __name__=='__main__':unittest.main()
