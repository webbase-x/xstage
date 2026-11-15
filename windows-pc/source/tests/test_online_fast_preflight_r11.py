"""R11 regression: 70k-song SQLite must not block wizard or touch media files."""
import os
import sqlite3
from contextlib import closing
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from karaoke.online_preflight import quick_eligible_counts, visible_row_count

class FastSQLPreflightTests(unittest.TestCase):
    def test_counts_large_catalog_without_touching_missing_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'songs.sqlite3'
            # sqlite3.Connection.__exit__ commits but does not close on Windows.
            # Close before TemporaryDirectory cleanup to prevent WinError 32.
            with closing(sqlite3.connect(db)) as conn, conn:
                conn.execute('CREATE TABLE songs (id INTEGER PRIMARY KEY, path TEXT, format TEXT, playable INT, duplicate_of INT, duplicate_state TEXT)')
                conn.executemany('INSERT INTO songs VALUES (?,?,?,?,?,?)',
                    ((i, 'Z:/missing-folder/song%05d.mid'%i, 'NCN' if i<70000 else 'MIDI', 1,0,'visible')
                     for i in range(70525)))
                conn.execute('INSERT INTO songs VALUES (70526,"other.mp4","MP4",1,0,"visible")')
                conn.execute('INSERT INTO songs VALUES (70527,"hidden.mid","MIDI",1,0,"manual_hidden")')
                conn.execute('INSERT INTO songs VALUES (70528,"inactive.mid","MIDI",0,0,"visible")')
            with patch('pathlib.Path.is_file',side_effect=AssertionError('No media stat allowed')), \
                 patch('karaoke.visible_sync.visible_song_plan',side_effect=AssertionError('No physical scan allowed')):
                before=time.monotonic()
                self.assertEqual(quick_eligible_counts(db),{'NCN':70000,'MIDI':525})
                self.assertEqual(visible_row_count(db),70527)
                self.assertLess(time.monotonic()-before,15.,'SQL-only preflight unreasonably slow')

    def test_rejects_invalid_database_without_creating_or_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing=Path(tmp)/'missing.sqlite3'
            with self.assertRaises(sqlite3.OperationalError): quick_eligible_counts(missing)
            self.assertFalse(missing.exists())

@unittest.skipUnless(os.environ.get('XSTAGE_TEST_GUI')=='1','Requires display')
class WizardFastStartTests(unittest.TestCase):
    def test_step_two_does_not_wait_for_full_disk_inspection(self):
        from karaoke.ui import KaraokeApp
        from tests.test_studio import midi_fixture
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'samples').mkdir()
            src=root/'Songs'/'32409.mid';src.parent.mkdir();src.write_bytes(midi_fixture())
            app=KaraokeApp(root,root/'Data')
            try:
                app.withdraw();app.library.add_files([src])
                with patch('karaoke.web_assets.local_candidates', side_effect=AssertionError('Full scan must be deferred')):
                    app.web_online_data()
                    acc=app.google_account
                    acc.credentials=('token','owner@example.com','refresh',time.monotonic()+3600)
                    acc.profile={'email':'owner@example.com','name':'Owner'}
                    wizard=app._online_wizard
                    wizard['login_button'].invoke()
                    self.assertEqual(wizard['page']['name'],'settings')
                    until=time.monotonic()+5
                    while time.monotonic()<until and str(wizard['confirm'].cget('state'))!='normal':
                        app.update();time.sleep(.015)
                    self.assertEqual(str(wizard['confirm'].cget('state')),'normal')
                    self.assertFalse(list((root/'Data'/'WebAssets').rglob('*.m4a')))
            finally:
                w=getattr(app,'_cloud_progress_window',None)
                if w is not None and w.winfo_exists():w.destroy()
                try:app.after_cancel(app.tick_after)
                except Exception:pass
                app.destroy()

if __name__=='__main__':unittest.main()
