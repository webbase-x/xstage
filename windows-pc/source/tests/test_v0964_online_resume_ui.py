"""Opt-in Tk regression: Google Login is on home; sync only displays account.

Run on Windows or with: XSTAGE_TEST_GUI=1 xvfb-run -a python -m unittest
  tests.test_v0964_online_resume_ui
"""
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from karaoke.web_resume import OnlineSyncRecovery
from tests.test_studio import midi_fixture


@unittest.skipUnless(os.environ.get('XSTAGE_TEST_GUI')=='1', 'Requires desktop display')
class OnlineResumeWindowTests(unittest.TestCase):
    def setUp(self):
        from karaoke.ui import KaraokeApp
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        (root/'samples').mkdir()
        music=root/'Songs'/'91001.mid';music.parent.mkdir();music.write_bytes(midi_fixture())
        self.app=KaraokeApp(root,root/'Data');self.app.withdraw()
        self.app.google_account=SimpleNamespace(credentials=('access','test@example.com',None,time.monotonic()+3500),
                                               profile={'name':'Operator','email':'test@example.com'},auth_busy=False,show_home=Mock())
        self.app.library.add_files([music])

    def tearDown(self):
        try:
            if self.app._cloud_progress_window is not None and self.app._cloud_progress_window.winfo_exists():
                self.app._cloud_progress_window.destroy()
            self.app.after_cancel(self.app.tick_after)
        except Exception:pass
        self.app.destroy()

    def widgets(self):
        dialog=self.app._cloud_progress_window
        result=[]
        def walk(parent):
            for widget in parent.winfo_children():
                result.append(widget);walk(widget)
        walk(dialog)
        return result

    def pump(self,predicate,timeout=7):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            self.app.update()
            if predicate():return True
            time.sleep(.015)
        return False

    def test_sync_displays_home_identity_without_manual_oauth_buttons(self):
        self.app.web_online_data()
        self.assertTrue(self.pump(lambda: bool(self.widgets())))
        dialog=self.app._cloud_progress_window
        self.assertIn('Recovery R16',dialog.title())
        def signed_in():
            return any('Operator' in x.cget('text') for x in self.widgets() if x.winfo_class()=='TLabel')
        self.assertTrue(self.pump(signed_in))
        widgets=self.widgets()
        wizard=self.app._online_wizard
        self.assertEqual(wizard['page']['name'], 'login')
        wizard['login_button'].invoke()
        self.assertEqual(wizard['page']['name'], 'settings')
        self.assertEqual(wizard['settings'].winfo_manager(), 'place')
        self.assertFalse(any(x.winfo_class()=='TButton' and 'OAuth JSON' in x.cget('text') for x in widgets))

    def test_interrupted_sync_is_offered_resume_button_on_reopen(self):
        state=OnlineSyncRecovery(self.app.data_dir/'WebAssets')
        state.begin(song_types={'MIDI'},total=70000,font='C:/A.sf2')
        state.progress('กำลังแปลงเพลง',400,70000)
        self.app.web_online_data()
        wizard=self.app._online_wizard
        wizard['login_button'].invoke()
        self.assertEqual(wizard['page']['name'], 'settings')
        self.assertTrue(self.pump(lambda: str(wizard['confirm'].cget('state'))=='normal'),
                        'Should offer resume, not start uploading automatically')
        self.assertEqual(wizard['confirm'].cget('text'), 'ซิงค์ต่อ')
        self.assertIn('พบงานค้าง', wizard['recovery_status'].cget('text'))
        # Loading the window alone never overwrites the last upload checkpoint.
        reopened=OnlineSyncRecovery(self.app.data_dir/'WebAssets')
        self.assertEqual(reopened.state['status'],'running')
        self.assertEqual(reopened.state['total'],70000)

if __name__=='__main__':unittest.main()
