"""R16: Online wizard is compact, balanced and has no visible scrollbars.

Tests include actual widget placement at reduced desktop sizes, not just text.
"""
from __future__ import annotations
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

@unittest.skipUnless(os.environ.get('XSTAGE_TEST_GUI') == '1','Needs GUI display')
class CompactWizardR16Tests(unittest.TestCase):
    def setUp(self):
        from karaoke.ui import KaraokeApp
        from tests.test_studio import midi_fixture
        self.tmp=tempfile.TemporaryDirectory()
        root=Path(self.tmp.name)
        (root/'samples').mkdir()
        song=root/'Songs'/'12345.mid'
        song.parent.mkdir()
        song.write_bytes(midi_fixture())
        with patch('karaoke.google_session.has_saved_session',return_value=False):
            self.app=KaraokeApp(root,root/'Data')
        self.app.library.add_files([song])
        self.app.withdraw()
        self.app.web_online_data()
        self.wizard=self.app._online_wizard
        self.window=self.app._cloud_progress_window
        account=self.app.google_account
        account.credentials=('fake','account-owner-long-email@example.com','refresh',time.monotonic()+3600)
        account.profile={'name':'Owner with a very long profile name that should not overflow the compact panel',
                         'email':'account-owner-long-email@example.com'}
        import tkinter as tk
        account._photo=tk.PhotoImage(master=self.app,width=44,height=44)

    def tearDown(self):
        try:
            if self.window.winfo_exists():self.window.destroy()
            try:self.app.after_cancel(self.app.tick_after)
            except Exception:pass
            self.app.destroy()
        finally:self.tmp.cleanup()

    def pump(self,seconds=.10):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            self.app.update()
            time.sleep(.009)

    def test_all_pages_fit_without_scrollbars_or_clipped_controls(self):
        for wh in ((680,460),(480,380),(320,310)):
            self.window.geometry(f'{wh[0]}x{wh[1]}+10+10')
            for page in ('login','settings','progress'):
                with self.subTest(window=wh,page=page):
                    self.wizard['show'](page)
                    self.pump()
                    rootx=self.window.winfo_rootx();rooty=self.window.winfo_rooty()
                    width=self.window.winfo_width();height=self.window.winfo_height()
                    visible=[]
                    def collect(widget):
                        for child in widget.winfo_children():
                            if child.winfo_ismapped():
                                visible.append(child)
                                collect(child)
                    collect(self.window)
                    self.assertFalse(any('Scrollbar' in w.winfo_class() for w in visible))
                    for widget in visible:
                        if widget.winfo_class() not in ('TButton','TLabel','TCheckbutton','TCombobox','TProgressbar'):
                            continue
                        x=widget.winfo_rootx()-rootx
                        y=widget.winfo_rooty()-rooty
                        self.assertGreaterEqual(x,-1,(wh,page,widget))
                        self.assertGreaterEqual(y,-1,(wh,page,widget))
                        self.assertLessEqual(x+widget.winfo_width(),width+2,(wh,page,widget))
                        self.assertLessEqual(y+widget.winfo_height(),height+2,(wh,page,widget))

    @staticmethod
    def _descendants(widget):
        yield widget
        for child in widget.winfo_children():
            yield from CompactWizardR16Tests._descendants(child)

    def test_status_has_one_progress_bar_and_two_capacity_labels(self):
        self.wizard['show']('progress')
        self.pump()
        self.assertEqual(set(self.wizard['storage_views']),{'actual','forecast'})
        self.assertTrue(self.wizard['progress_bar'].winfo_ismapped())
        self.assertEqual(self.wizard['progress_pause'].cget('text'),'ปิด')
        self.assertTrue(self.wizard['storage_views']['actual'][0].winfo_ismapped())
        self.assertTrue(self.wizard['storage_views']['forecast'][0].winfo_ismapped())
        self.assertEqual(len([widget for widget in self.wizard['progress'].winfo_children()
            for item in self._descendants(widget)
            if item.winfo_class()=='TProgressbar' and item.winfo_ismapped()]),1)

if __name__ == '__main__': unittest.main()
