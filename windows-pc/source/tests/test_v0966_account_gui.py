"""Run with XSTAGE_TEST_GUI=1 xvfb-run -a python -m unittest tests.test_v0966_account_gui.
No network or real Google sign-in is performed.
"""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import time

@unittest.skipUnless(os.environ.get('XSTAGE_TEST_GUI')=='1','Requires Tk display')
class AccountWindowTests(unittest.TestCase):
    def setUp(self):
        from karaoke.ui import KaraokeApp
        from tests.test_studio import midi_fixture
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        (root/'samples').mkdir()
        song=root/'Songs'/'92001.mid';song.parent.mkdir();song.write_bytes(midi_fixture())
        self.app=KaraokeApp(root,root/'Data')
        self.app.library.add_files([song]);self.app.withdraw()
        self.app.google_account=SimpleNamespace(credentials=('token','owner@example.com','refresh',time.monotonic()+3000),
                                               profile={'name':'Owner','email':'owner@example.com'},auth_busy=False,show_home=Mock())
    def tearDown(self):
        try:
            if self.app._cloud_progress_window and self.app._cloud_progress_window.winfo_exists():
                self.app._cloud_progress_window.destroy()
            self.app.after_cancel(self.app.tick_after)
        except Exception:pass
        self.app.destroy()
    def children(self):
        parent=self.app._cloud_progress_window
        result=[]
        def walk(w):
            for child in w.winfo_children():
                result.append(child);walk(child)
        walk(parent)
        return result
    def test_sync_first_panel_reads_home_identity_not_oauth_picker(self):
        self.app.web_online_data()
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            self.app.update();time.sleep(.02)
            if any('Owner' in x.cget('text') for x in self.children() if x.winfo_class()=='TLabel'):
                break
        widgets=self.children()
        labels=' '.join(x.cget('text') for x in widgets if x.winfo_class()=='TLabel')
        buttons=[x for x in widgets if x.winfo_class()=='TButton']
        self.assertIn('owner@example.com',labels)
        self.assertIn('Recovery R16',self.app._cloud_progress_window.title())
        self.assertFalse(any('เลือก OAuth' in x.cget('text') for x in buttons))
        wizard=self.app._online_wizard
        self.assertEqual(wizard['login'].winfo_manager(),'place')
        wizard['login_button'].invoke()
        self.app.update()
        self.assertEqual(wizard['settings'].winfo_manager(),'place')
        self.app.google_account.show_home.assert_not_called()

if __name__=='__main__':unittest.main()

@unittest.skipUnless(os.environ.get('XSTAGE_TEST_GUI')=='1','Requires Tk display')
class LoginHomeVisualTests(unittest.TestCase):
    def test_separate_login_home_and_profile_in_topbar(self):
        import tkinter as tk
        from karaoke.google_account_ui import GoogleAccountUI
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            root=tk.Tk()
            root.geometry('1120x700')
            root.home=home;root.data_dir=home/'Data';root.data_dir.mkdir()
            root.surface=tk.Frame(root,bg='#090d1f');root.surface.pack(fill='both',expand=True)
            root.focus_song_input=Mock()
            try:
                with patch('karaoke.google_session.has_saved_session',return_value=False):
                    account=GoogleAccountUI(root)
                    until=time.monotonic()+.4
                    while time.monotonic()<until:
                        root.update();time.sleep(.01)
                    self.assertEqual(account.home.winfo_manager(),'place')
                    self.assertEqual(account.bar.winfo_manager(),'place')
                    account.hide_home();root.update()
                    self.assertEqual(account.home.winfo_manager(),'')
                    account.show_home();root.update()
                    self.assertEqual(account.home.winfo_manager(),'place')
                    # A successful account event displays verified identity on the main bar.
                    account._messages.put((account._generation,'ready',
                        (('token','operator@example.com','refresh',time.monotonic()+3500),{},None)))
                    account._messages.put((account._generation,'profile',
                        ({'email':'operator@example.com','name':'Operator'},None)))
                    account._poll()
                    root.update()
                    self.assertIn('Operator',account.profile_button.cget('text'))
                    self.assertIn('operator@example.com',account.profile_button.cget('text'))
                    account.close()
            finally:
                root.destroy()
