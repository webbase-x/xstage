"""Regression coverage for repeatable X-Stage Online dialog and SoundFont choice.

No Google credentials or actual media upload required. GUI tests opt-in.
"""
import os
import tempfile
import time
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from karaoke.web_environment import online_soundfont_choices, resolve_online_soundfont
from tests.test_studio import midi_fixture


class OnlineFont0947Tests(unittest.TestCase):
    def test_current_pc_soundfont_stack_is_default_without_changing_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            first=root/'one.sf2'; second=root/'two.sf2'
            first.write_bytes(b'one');second.write_bytes(b'two')
            player={'soundfont_audio':{'fonts':[{'path':str(first),'gain_db':-3},
                                                   {'path':str(second),'gain_db':-7}]},
                    'instrument_fonts':{'piano':str(second)}}
            with patch('karaoke.soundfont.inspect_font'):
                effective,selected=resolve_online_soundfont(root, root/'Data', player)
            self.assertEqual(selected,first)
            self.assertEqual(effective['soundfont_audio']['fonts'],player['soundfont_audio']['fonts'])
            self.assertEqual(effective['instrument_fonts'],player['instrument_fonts'])
            self.assertEqual(player['soundfont_audio']['fonts'][1]['gain_db'],-7)

    def test_override_uses_only_selected_font_without_modifying_pc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            pc=root/'pc.sf2';other=root/'online.sf2'
            pc.write_bytes(b'pc');other.write_bytes(b'online')
            player={'soundfont_audio':{'fonts':[{'path':str(pc),'gain_db':-3}]},
                    'instrument_fonts':{'piano':str(pc)}}
            with patch('karaoke.web_environment.inspect_font'), \
                 patch('karaoke.soundfont.inspect_font'):
                effective,selected=resolve_online_soundfont(root,root/'Data',player,override=other)
            self.assertEqual(selected,other)
            self.assertEqual(effective['instrument_fonts'],{})
            self.assertTrue(effective['soundfont_follow_song'])
            self.assertEqual(effective['soundfont_audio']['fonts'][0]['path'],str(other))
            self.assertEqual(player['soundfont_audio']['fonts'][0]['path'],str(pc))
            self.assertEqual(player['instrument_fonts'],{'piano':str(pc)})

    def test_list_contains_pc_fonts_and_installed_sf2_without_folder_chooser(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            pc=root/'pc.sf2';pc.write_bytes(b'a')
            built=root/'SoundFonts'/'installed.sf2';built.parent.mkdir();built.write_bytes(b'b')
            other=root/'SoundFonts'/'not-a-font.txt';other.write_text('hello')
            found=online_soundfont_choices(root,root/'Data',{'soundfont':str(pc)})
            self.assertEqual(found,[pc,built])


@unittest.skipUnless(os.environ.get('XSTAGE_TEST_GUI')=='1',
                     'Opt-in GUI regression (Windows or xvfb-run)')
class OnlineDialog0947Tests(unittest.TestCase):
    def setUp(self):
        from karaoke.ui import KaraokeApp
        from unittest.mock import patch
        self.folder=tempfile.TemporaryDirectory()
        root=Path(self.folder.name);(root/'samples').mkdir()
        song=root/'Songs'/'91001.mid';song.parent.mkdir();song.write_bytes(midi_fixture())
        with patch('karaoke.google_session.has_saved_session',return_value=False):
            self.app=KaraokeApp(root,root/'Data')
        self.app.withdraw()
        self.app.library.add_files([song])
        self.app.settings['soundfont']='C:/PC/default.sf2'
        self.app.google_account.credentials=('token','user@example.com','refresh',time.monotonic()+3600)
        self.app.google_account.profile={'email':'user@example.com','name':'Sync Owner'}
    def tearDown(self):
        try:
            self.app.after_cancel(self.app.tick_after)
            dialog=self.app._cloud_progress_window
            if dialog is not None and dialog.winfo_exists():
                dialog.tk.call(dialog.protocol('WM_DELETE_WINDOW'))
                self.app.update()
            self.app.destroy()
        finally:self.folder.cleanup()
    def pump(self,predicate=lambda:True, seconds=5):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            self.app.update()
            if predicate():return True
            time.sleep(.015)
        return False
    def open_ready(self):
        self.app.web_online_data()
        self.assertEqual(self.app._online_wizard['page']['name'],'login')
        self.app._online_wizard['login_button'].invoke()
        self.assertEqual(self.app._online_wizard['page']['name'],'settings')
        self.assertTrue(self.pump(lambda:str(self.app._online_wizard['confirm'].cget('state'))=='normal'))
        return self.app._online_wizard
    def test_close_reopen_replans_and_defaults_to_pc_font(self):
        wizard=self.open_ready()
        first=self.app._cloud_progress_window
        self.assertTrue(self.app._cloud_backup_busy)
        self.assertIn('Recovery R16',first.title())
        combos=[]
        def walk(w):
            for child in w.winfo_children():
                if child.winfo_class()=='TCombobox':combos.append(child)
                walk(child)
        walk(first)
        self.assertEqual(len(combos),2)  # review + preserved progress control
        self.assertTrue(all('ตาม X-Stage PC' in c.get() for c in combos))
        first.tk.call(first.protocol('WM_DELETE_WINDOW'))
        self.assertTrue(self.pump(lambda:self.app._cloud_progress_window is None))
        self.assertFalse(self.app._cloud_backup_busy)
        self.open_ready()
        self.assertIsNot(first,self.app._cloud_progress_window)
    def test_success_waits_for_explicit_button_before_opening_website(self):
        captured=[]
        def simulated(*args,**kwargs):
            captured.append((args,kwargs))
            return {'total':1,'uploaded_files':2,'failed':[]}
        with patch.object(self.app,'open_karaoke_online') as browser, \
             patch('karaoke.web_environment.prepare_online_renderer',return_value=({},'pc.sf2','ffmpeg',1)), \
             patch('karaoke.google_drive_sync.load_client',return_value=('client','secret')), \
             patch('karaoke.google_drive_sync.Drive',return_value=object()), \
             patch('karaoke.web_drive.sync_web_assets',side_effect=simulated):
            wizard=self.open_ready()
            wizard['confirm'].invoke()
            self.assertTrue(self.pump(lambda:bool(wizard['state'].get('sync_completed'))))
            self.assertEqual(len(captured),1)
            browser.assert_not_called()
            self.assertIsNotNone(self.app._cloud_progress_window)
            self.assertTrue(self.app._cloud_progress_window.winfo_exists())
            button=wizard['progress_pause']
            self.assertTrue(self.pump(lambda:'สำเร็จ' in button.cget('text')))
            button.invoke()
            self.assertTrue(self.pump(lambda:browser.call_count==1))
            self.assertIsNone(self.app._cloud_progress_window)
            self.assertFalse(self.app._cloud_backup_busy)
            self.open_ready()
    def test_soundfont_override_changes_online_only(self):
        font=Path(self.folder.name)/'alternative.sf2';font.write_bytes(b'fixture')
        pc_font=self.app.settings['soundfont']
        with patch('karaoke.ui.choose_online_soundfont_file',return_value=str(font)), \
             patch('karaoke.soundfont.inspect_font',return_value={'name':'alternative'}), \
             patch('karaoke.web_environment.prepare_online_renderer',return_value=({},font,'ffmpeg',1)) as prepare, \
             patch('karaoke.google_drive_sync.load_client',return_value=('client','secret')), \
             patch('karaoke.google_drive_sync.Drive',return_value=object()), \
             patch('karaoke.web_drive.sync_web_assets',return_value={'total':1,'uploaded_files':2,'failed':[]}), \
             patch.object(self.app,'open_karaoke_online') as browser:
            wizard=self.open_ready()
            def controls():
                all=[]
                def recur(x):
                    for c in x.winfo_children():
                        if c.winfo_class()=='TButton':all.append(c)
                        recur(c)
                recur(wizard['settings'])
                return all
            next(x for x in controls() if x.cget('text')=='เลือก SF2…').invoke()
            wizard['confirm'].invoke()
            self.assertTrue(self.pump(lambda:bool(wizard['state'].get('sync_completed'))))
            browser.assert_not_called()
            wizard['progress_pause'].invoke()
            self.assertTrue(self.pump(lambda:browser.call_count==1))
            self.assertEqual(prepare.call_args.kwargs['override'],str(font))
            self.assertEqual(self.app.settings['soundfont'],pc_font)
    def test_app_close_does_not_wait_on_idle_online_window(self):
        from karaoke.shutdown import wait_for_index
        self.open_ready()
        self.assertFalse(wait_for_index(self.app))
        self.assertFalse(self.app._cloud_backup_busy)
        self.assertIsNone(self.app._cloud_progress_window)
        self.open_ready()
    def test_window_x_during_sync_closes_after_worker_finishes(self):
        entered=threading.Event()
        def waiting(*args,**kwargs):
            entered.set()
            while not kwargs['cancel'].is_set():time.sleep(.005)
            raise RuntimeError('cancelled')
        with patch('karaoke.web_environment.prepare_online_renderer',return_value=({},'pc.sf2','ffmpeg',1)), \
             patch('karaoke.google_drive_sync.load_client',return_value=('client','secret')), \
             patch('karaoke.google_drive_sync.Drive',return_value=object()), \
             patch('karaoke.web_drive.sync_web_assets',side_effect=waiting):
            wizard=self.open_ready();wizard['confirm'].invoke()
            self.assertTrue(self.pump(entered.is_set))
            dialog=self.app._cloud_progress_window
            dialog.tk.call(dialog.protocol('WM_DELETE_WINDOW'))
            self.assertTrue(self.pump(lambda:self.app._cloud_progress_window is None))
            self.assertFalse(self.app._cloud_backup_busy)
            self.open_ready()
    def test_cancel_then_repeat_after_opening_again(self):
        entered=threading.Event()
        def waiting(*args,**kwargs):
            entered.set()
            while not kwargs['cancel'].is_set():time.sleep(.005)
            raise RuntimeError('cancelled')
        with patch('karaoke.web_environment.prepare_online_renderer',return_value=({},'pc.sf2','ffmpeg',1)), \
             patch('karaoke.google_drive_sync.load_client',return_value=('client','secret')), \
             patch('karaoke.google_drive_sync.Drive',return_value=object()), \
             patch('karaoke.web_drive.sync_web_assets',side_effect=waiting):
            wizard=self.open_ready();wizard['confirm'].invoke()
            self.assertTrue(self.pump(entered.is_set))
            dialog=self.app._cloud_progress_window
            # Find preserved Stop button while stage-3 is visible.
            def buttons():
                found=[]
                def walk(w):
                    for child in w.winfo_children():
                        if child.winfo_class()=='TButton':found.append(child)
                        walk(child)
                walk(dialog)
                return found
            next(x for x in buttons() if x.cget('text')=='หยุด').invoke()
            self.assertTrue(self.pump(lambda:self.app._online_sync_thread is None))
            dialog.tk.call(dialog.protocol('WM_DELETE_WINDOW'))
            self.assertTrue(self.pump(lambda:self.app._cloud_progress_window is None))
            self.open_ready()

if __name__=='__main__':unittest.main()
