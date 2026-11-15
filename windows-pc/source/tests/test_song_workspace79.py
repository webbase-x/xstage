import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock
from karaoke.library import SongLibrary
from karaoke.song_workspace import CatalogSearch
from test_studio import midi_fixture

class CatalogTests(unittest.TestCase):
    def test_search_refresh_and_latest_query(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);db=SongLibrary(root/'songs.db')
            song=root/'1.mid';song.write_bytes(midi_fixture());db.add_files([song])
            search=CatalogSearch(db.path)
            try:
                search.submit('not found');revision=search.submit('')
                while True:
                    rev,rows,total,error=search.results.get(timeout=5)
                    if rev==revision:break
                self.assertIsNone(error);self.assertEqual(total,1);self.assertEqual(len(rows),1)
                db.edit(rows[0]['id'],'123','New Title','Singer')
                search.submit('New Title')
                _,rows,total,error=search.results.get(timeout=5)
                self.assertEqual(rows[0]['title'],'New Title')
            finally:search.close()

    def test_missing_database_reports_error(self):
        with tempfile.TemporaryDirectory() as temp:
            search=CatalogSearch(Path(temp)/'missing.db')
            try:
                search.submit('');_,rows,total,error=search.results.get(timeout=5)
                self.assertTrue(error);self.assertEqual(rows,[])
            finally:search.close()

@unittest.skipUnless(os.environ.get('DISPLAY'),'requires graphical display')
class WorkspaceGuiTests(unittest.TestCase):
    def test_unified_window_busy_cancel_repeat_and_catalog(self):
        import tkinter as tk
        from karaoke.job_dialog import JobWindow
        from karaoke.ui import KaraokeApp
        with tempfile.TemporaryDirectory() as temp:
            app=tk.Tk();app.geometry('300x100');errors=[]
            app.report_callback_exception=lambda *args:errors.append(args)
            app.library=SongLibrary(Path(temp)/'songs.db')
            song=Path(temp)/'music.mid';song.write_bytes(midi_fixture());app.library.add_files([song])
            app.settings={};app.scanning=False;app.cancel_scan=threading.Event()
            for name in 'show_import_report add_folder add_files connect_catalog rebuild_library show_error save_settings'.split():setattr(app,name,Mock())
            job=JobWindow(app);app.job_window=job
            def pump():
                for _ in range(30):app.update();time.sleep(.01)
            pump();self.assertEqual(len(job.workspace.catalog.get_children()),1)
            self.assertIs(app.song_manager,job.window)
            job.hide();KaraokeApp.show_job_progress(app);pump()
            self.assertIs(app.job_window,job);self.assertTrue(job.window.winfo_ismapped())
            app.scanning=True;job.reset_job();pump()
            self.assertEqual(str(job.workspace.start['state']),'disabled')
            job.request_cancel();self.assertTrue(app.cancel_scan.is_set())
            job.reset_job();self.assertFalse(job.cancel_requested)
            self.assertEqual(str(job.cancel['state']),'normal')
            app.scanning=False
            job.update({'state':{'finished':True,'total':1,'done':1,'accepted':1},'rows':[{'title':'Test song','ok':True}]});pump()
            self.assertEqual(len(job.tree.get_children()),1)
            job.reset_job();self.assertEqual(len(job.tree.get_children()),0)
            self.assertEqual(len(job.workspace.catalog.get_children()),1)
            for width,height in [(1100,740),(760,600)]:
                job.window.geometry(f'{width}x{height}');pump()
                self.assertGreater(job.workspace.start.winfo_y(),-1)
                self.assertLessEqual(job.workspace.start.winfo_rooty()+job.workspace.start.winfo_height(),job.window.winfo_rooty()+job.window.winfo_height())
            self.assertFalse(errors,errors)
            job.window.destroy();pump();self.assertTrue(job.workspace.reader.closed.is_set())
            app.destroy()
