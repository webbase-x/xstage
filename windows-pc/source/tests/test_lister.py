import tempfile, threading, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from karaoke.lister import locations, build_list
from karaoke.library import SongLibrary
from karaoke.ui import KaraokeApp
from test_studio import midi_fixture

class ListerTests(unittest.TestCase):
    def test_saved_locations_deduplicate_by_path_and_type(self):
        roots=locations({'song_folders':[{'path':'music','type':'EMK'},{'path':'music','type':'EMK'},None,{'path':'music','type':'bad'}]})
        self.assertEqual(len(roots),2)
        self.assertEqual(roots[1]['type'],'ทุกประเภท')

    @unittest.skip('v0.9.41 retired automatic-copy/hide/old cleanup; covered by test_v0941_*')

    def test_lister_discovers_new_files_and_keeps_ids_and_favorites(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); songs=root/'NCN'; songs.mkdir()
            db=SongLibrary(root/'data.sqlite3')
            first=songs/'1.mid';first.write_bytes(midi_fixture())
            roots=[{'path':str(songs),'type':'NCN / MIDI / KAR'}]
            self.assertEqual(build_list(db,roots)[0],1)
            sid=db.search()[0]['id']; db.favorite(sid)
            nested=songs/'sub';nested.mkdir();(nested/'2.mid').write_bytes(midi_fixture())
            self.assertEqual(build_list(db,roots)[0],2)
            self.assertEqual(db.count(),1); self.assertEqual(db.get(sid)['favorite'],1)
            with db.connect() as conn:self.assertEqual(conn.execute('SELECT count(*) FROM songs').fetchone()[0],2)
            self.assertTrue((root/'data-before-reindex.sqlite3').is_file())

    def test_type_filter_and_missing_root_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'1.mid').write_bytes(midi_fixture());db=SongLibrary(root/'data.db')
            roots=[{'path':str(root),'type':'EMK'},{'path':str(root/'missing'),'type':'ทุกประเภท'}]
            count,_,errors=build_list(db,roots)
            self.assertEqual(count,0);self.assertTrue(errors);self.assertEqual(db.count(),0)

    def test_cancelled_lister_retains_existing_database(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);song=root/'1.mid';song.write_bytes(midi_fixture());db=SongLibrary(root/'data.db');db.add_files([song])
            cancel=threading.Event();cancel.set()
            self.assertEqual(build_list(db,[{'path':temp,'type':'ทุกประเภท'}],cancelled=cancel)[0],0)
            self.assertEqual(db.count(),1)

    def test_build_requires_confirmation_and_snapshots_locations(self):
        app=SimpleNamespace(settings={'song_folders':[{'path':'music','type':'EMK'}]},start_index_job=Mock())
        with patch('karaoke.ui.messagebox.askyesno',return_value=False), patch('karaoke.import_ui.choose_copy',return_value=False), patch('karaoke.import_ui.options',return_value={}):
            KaraokeApp.rebuild_library(app)
        app.start_index_job.assert_not_called()
        with patch('karaoke.ui.messagebox.askyesno',return_value=True), patch('karaoke.import_ui.choose_copy',return_value=False), patch('karaoke.import_ui.options',return_value={}):
            KaraokeApp.rebuild_library(app)
        app.start_index_job.assert_called_once()

    def test_manager_opens_shared_workspace(self):
        from karaoke.performer import PlaybackApp
        app=SimpleNamespace(show_catalog_maintenance=Mock())
        PlaybackApp.manage_songs(app)
        app.show_catalog_maintenance.assert_called_once_with()
