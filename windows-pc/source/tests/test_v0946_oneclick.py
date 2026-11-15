"""Offline one-click environment and UI tests. No real Drive or credentials."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from karaoke.web_environment import resolve_ffmpeg, resolve_soundfont, prepare_online_renderer
from tests.test_studio import midi_fixture


class OneClickEnvironment0946Tests(unittest.TestCase):
    def test_auto_detect_soundfont_only_if_no_existing_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder)
            font=home/'SoundFonts'/'gm.sf2';font.parent.mkdir()
            font.write_bytes(b'fake-sf2')
            with patch('karaoke.web_environment.inspect_font', return_value={'name':'gm'}), \
                 patch('karaoke.soundfont.inspect_font', return_value={'name':'gm'}):
                settings, selected=resolve_soundfont(home,home/'Data',{})
            self.assertEqual(selected,font)
            self.assertEqual(settings['soundfont_audio']['fonts'][0]['path'],str(font))

    def test_missing_soundfont_never_opens_picker(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(FileNotFoundError, 'SoundFont'):
                resolve_soundfont(folder,Path(folder)/'Data',{})

    def test_invalid_configured_soundfont_is_not_replaced_silently(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder)
            other=home/'SoundFonts'/'gm.sf2';other.parent.mkdir();other.write_bytes(b'fake')
            with self.assertRaises((FileNotFoundError,OSError)):
                resolve_soundfont(home,home/'Data',{'soundfont':str(home/'wrong.sf2')})

    def test_ffmpeg_is_bundled_and_runnable(self):
        exe=resolve_ffmpeg(Path('.'),{})
        self.assertTrue(Path(exe).is_file())

    def test_ui_contains_no_modal_file_dialog_or_confirm(self):
        import inspect
        from karaoke.ui import KaraokeApp
        source=inspect.getsource(KaraokeApp.web_online_data)
        self.assertNotIn('askopenfilename(',source)
        self.assertNotIn('askyesno(',source)
        self.assertNotIn('worker_combo',source)
        self.assertIn('self.library.path, None',source)
        # Website launch must be a deliberate click on the completed wizard,
        # never automatic from the background worker.
        from karaoke.online_wizard import setup_online_wizard
        self.assertNotIn('self.open_karaoke_online()',source)
        self.assertIn('app.open_karaoke_online()',inspect.getsource(setup_online_wizard))


@unittest.skipUnless(__import__('os').environ.get('XSTAGE_TEST_GUI') == '1',
                     'Opt-in GUI: requires an explicit graphical display')
class OneClickWindow0946Tests(unittest.TestCase):
    def setup_app(self, folder):
        from karaoke.ui import KaraokeApp
        root=Path(folder);(root/'samples').mkdir()
        song=root/'Songs'/'91001.mid';song.parent.mkdir()
        song.write_bytes(midi_fixture())
        app=KaraokeApp(root,root/'Data')
        app.withdraw();app.library.add_files([song])
        app.google_account.credentials=('token','user@example.com','refresh',time.monotonic()+3600)
        app.google_account.profile={'email':'user@example.com','name':'Owner'}
        return app
    def pump(self,app,condition,seconds=7):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            app.update()
            if condition():return True
            time.sleep(.015)
        return False
    def start_reviewed_sync(self,app):
        app.web_online_data()
        wizard=app._online_wizard
        self.assertEqual(wizard['page']['name'],'login')
        wizard['login_button'].invoke()
        self.assertEqual(wizard['page']['name'],'settings')
        self.assertTrue(self.pump(app,lambda:str(wizard['confirm'].cget('state'))=='normal'))
        wizard['confirm'].invoke()
        self.assertEqual(wizard['page']['name'],'progress')
    def close(self,app):
        w=app._cloud_progress_window
        if w is not None and w.winfo_exists():
            w.tk.call(w.protocol('WM_DELETE_WINDOW'))
            self.pump(app,lambda:app._cloud_progress_window is None,3)
        try:app.after_cancel(app.tick_after)
        except Exception:pass
        app.destroy()
    def test_missing_prerequisite_is_shown_inline_without_opening_browser(self):
        with tempfile.TemporaryDirectory() as folder:
            app=self.setup_app(folder)
            try:
                with patch.object(app,'open_karaoke_online') as browser, \
                     patch('karaoke.web_environment.prepare_online_renderer',
                           side_effect=FileNotFoundError('ไม่มี SoundFont ทดสอบ')):
                    self.start_reviewed_sync(app)
                    dialog=app._cloud_progress_window
                    def feedback():
                        found=[]
                        def walk(w):
                            for child in w.winfo_children():
                                if child.winfo_class()=='TLabel':found.append(child.cget('text'))
                                walk(child)
                        walk(dialog)
                        return ' '.join(found)
                    self.assertTrue(self.pump(app,lambda:'ไม่มี SoundFont ทดสอบ' in feedback()))
                    self.assertTrue(dialog.winfo_exists())
                    browser.assert_not_called()
            finally:self.close(app)
    def test_click_sync_runs_complete_pipeline_without_other_dialogs(self):
        with tempfile.TemporaryDirectory() as folder:
            app=self.setup_app(folder)
            try:
                with patch.object(app,'open_karaoke_online') as browser, \
                     patch('karaoke.web_environment.prepare_online_renderer',
                           return_value=({},Path(folder)/'dummy.sf2','ffmpeg',1)), \
                     patch('karaoke.google_drive_sync.load_client',return_value=('client-id','')), \
                     patch('karaoke.google_drive_sync.Drive',return_value=object()), \
                     patch('karaoke.web_drive.sync_web_assets',
                           return_value={'total':1,'uploaded_files':2,'failed':[]}) as syncer, \
                     patch('tkinter.filedialog.askopenfilename',side_effect=AssertionError('picker called')), \
                     patch('tkinter.messagebox.askyesno',side_effect=AssertionError('extra confirm called')):
                    self.start_reviewed_sync(app)
                    wizard=app._online_wizard
                    self.assertTrue(self.pump(app,lambda:bool(wizard['state'].get('sync_completed'))))
                    browser.assert_not_called()
                    self.assertTrue(syncer.called)
                    self.assertIsNone(syncer.call_args.args[2], 'must use DB paths only')
                    self.assertIsNotNone(app._cloud_progress_window)
                    wizard['progress_pause'].invoke()
                    self.assertTrue(self.pump(app,lambda:browser.call_count==1))
                    self.assertIsNone(app._cloud_progress_window)
            finally:self.close(app)

if __name__=='__main__':unittest.main()
