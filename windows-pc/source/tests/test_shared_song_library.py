"""The Online SQLite is the Karaoke PC's primary song registry in Drive mode."""
import hashlib
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from karaoke.shared_song_library import SharedSongLibrary, validate_shared, UnavailableSharedSongLibrary


class SharedSongLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "XStageKaraoke"
        for item in ("SONGS", "SOUNDFONT", "FX", "DB"):
            (self.root / item).mkdir(parents=True, exist_ok=True)
        self.file = self.root / "SONGS/MIDI/XMID/1/00001.xmid"
        self.file.parent.mkdir(parents=True)
        self.file.write_bytes(b"Xmid-test-placeholder")
        self.database = self.root / "DB/songs.sqlite3"
        with closing(sqlite3.connect(self.database)) as db:
            db.executescript("""
                CREATE TABLE catalog_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                INSERT INTO catalog_meta VALUES('format','xstage-sqlite3-v1');
                INSERT INTO catalog_meta VALUES('schemaVersion','1');
                INSERT INTO catalog_meta VALUES('kind','snapshot');
                INSERT INTO catalog_meta VALUES('pcSchema','shared-v1');
                INSERT INTO catalog_meta VALUES('pathBase','SONGS');
                CREATE TABLE songs (
                    id INTEGER PRIMARY KEY, web_song_id TEXT UNIQUE NOT NULL,
                    path TEXT NOT NULL, kind TEXT NOT NULL, search TEXT NOT NULL,
                    favorite INTEGER NOT NULL DEFAULT 0, playable INTEGER NOT NULL DEFAULT 1,
                    format TEXT NOT NULL DEFAULT '', code TEXT NOT NULL, title TEXT NOT NULL,
                    artist TEXT NOT NULL, source_format TEXT NOT NULL,
                    original_relative_path TEXT NOT NULL, payload TEXT NOT NULL,
                    key_signature TEXT NOT NULL DEFAULT '', duplicate_of INTEGER NOT NULL DEFAULT 0,
                    duplicate_state TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX songs_code ON songs(code);
                CREATE INDEX songs_title ON songs(title COLLATE NOCASE,id);
                INSERT INTO songs(id,web_song_id,path,kind,search,code,title,artist,
                                  source_format,original_relative_path,payload)
                VALUES(1417,'browser/xmid/abc','SONGS/MIDI/XMID/1/00001.xmid',
                       'MIDI','00001 เพลงทดสอบ ศิลปิน','00001','เพลงทดสอบ','ศิลปิน',
                       'XMID','MIDI/XMID/1/00001.xmid','{}');
            """)
        self.prefs = {}

    def test_search_get_queue_identity_and_no_local_db(self):
        original = hashlib.sha256(self.database.read_bytes()).hexdigest()
        library = SharedSongLibrary(str(self.root),self.prefs)
        self.assertEqual(library.count(),1)
        self.assertTrue(library.has_songs())
        self.assertEqual(library.search("เพลง")[0]["id"],1417)
        self.assertEqual(library.search("00001")[0]["code"],"00001")
        self.assertEqual(library.get(1417)["path"],str(self.file.resolve()))
        with closing(library.open_reader()) as reader:
            self.assertEqual(reader.warm_up(),1)
        library.favorite(1417)
        self.assertEqual(library.search("เพลง",favorite=True)[0]["id"],1417)
        self.assertEqual(original,hashlib.sha256(self.database.read_bytes()).hexdigest())
        self.assertFalse((self.database.parent / "songs.sqlite3-wal").exists())
        self.assertFalse((self.database.parent / "songs.sqlite3-shm").exists())
        self.assertEqual(list((self.root / "DB").iterdir()),[self.database])

    def test_write_actions_fail_closed(self):
        library = SharedSongLibrary(str(self.root),{})
        for action in [lambda:library.add_files([self.file]),
                       lambda:library.edit(1417,"1","x","y"),
                       lambda:library.rebuild()]:
            with self.assertRaises(ValueError):
                action()
        self.assertEqual(library.count(),1)

    def test_missing_media_does_not_reference_wrong_path(self):
        library = SharedSongLibrary(str(self.root),{})
        self.file.unlink()
        row = library.get(1417)
        self.assertEqual(row["playable"],0)
        self.assertEqual(row["path"],"")

    def test_reject_legacy_catalog_and_report_missing_drive(self):
        with closing(sqlite3.connect(self.database)) as db:
            with db:
                db.execute("DELETE FROM catalog_meta WHERE key='pcSchema'")
        with self.assertRaises(ValueError):
            validate_shared(str(self.root))
        unavailable = UnavailableSharedSongLibrary(self.root,"ต้องสร้างฐานใหม่")
        self.assertEqual(unavailable.search(),[])
        self.assertEqual(unavailable.count(),0)
        with self.assertRaises(ValueError):
            unavailable.open_reader()


if __name__ == "__main__":
    unittest.main()
