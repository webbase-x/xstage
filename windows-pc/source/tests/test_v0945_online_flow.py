"""Explicit UI workflow checks, opt-in when a graphical display is available."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from tests.test_studio import midi_fixture


@unittest.skipUnless(os.environ.get('XSTAGE_TEST_GUI') == '1',
                     'Opt-in GUI regression: set XSTAGE_TEST_GUI=1 with a working display')
class OnlineDialog0945Tests(unittest.TestCase):
    def test_dialog_counts_db_song_without_starting_google_or_conversion(self):
        from karaoke.ui import KaraokeApp
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'samples').mkdir()
            song = root / 'Songs' / '90001.mid'
            song.parent.mkdir()
            song.write_bytes(midi_fixture())
            app = KaraokeApp(root, root/'Data')
            try:
                app.withdraw()
                app.library.add_files([song])
                app.web_online_data()
                dialog = app._cloud_progress_window
                self.assertIn('X-Stage Karaoke Online', dialog.title())
                wizard=app._online_wizard
                self.assertEqual(wizard['page']['name'], 'login')
                self.assertEqual(wizard['login'].winfo_manager(), 'place')
                count=''
                limit=time.monotonic()+6
                def all_labels(parent):
                    values=[]
                    for child in parent.winfo_children():
                        if child.winfo_class()=='TLabel':values.append(child.cget('text'))
                        values.extend(all_labels(child))
                    return values
                while time.monotonic()<limit:
                    app.update()
                    count=next((t for t in all_labels(dialog)
                               if t.startswith('เพลงพร้อมซิงก์')), '')
                    if count:break
                    time.sleep(.025)
                self.assertIn('1 รายการ', count)
                self.assertEqual(str(wizard['confirm'].cget('state')), 'disabled',
                    'No upload may start before Google login and review confirmation')
                self.assertFalse(list((root/'Data'/'WebAssets').rglob('*.m4a')),
                                 'Opening the dialog must not begin converting audio')
                self.assertTrue(app._cloud_backup_busy)
            finally:
                try:
                    window=app._cloud_progress_window
                    if window is not None and window.winfo_exists():
                        window.tk.call(window.protocol('WM_DELETE_WINDOW'))
                        app.update()
                    app.after_cancel(app.tick_after)
                except Exception:pass
                app.destroy()
