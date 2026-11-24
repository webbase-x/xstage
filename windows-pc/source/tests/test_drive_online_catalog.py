"""The PC must read the hosted Online SQLite schema without migrating or writing it."""
import hashlib
import os
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from karaoke import drive_online_catalog as online


class MountedOnlineCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "XStageKaraoke"
        for directory in ("SONGS", "SOUNDFONT", "FX", "DB"):
            (self.root / directory).mkdir(parents=True)
        self.db_path = self.root / "DB" / "songs.sqlite3"
        with closing(sqlite3.connect(self.db_path)) as db:
            db.executescript("""
                CREATE TABLE catalog_meta (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE songs (
                    web_song_id TEXT PRIMARY KEY, code TEXT, title TEXT, artist TEXT,
                    source_format TEXT, original_relative_path TEXT, payload TEXT,
                    midi_md5 TEXT
                );
                INSERT INTO catalog_meta VALUES ('format','xstage-sqlite3-v1');
                INSERT INTO catalog_meta VALUES ('schemaVersion','1');
                INSERT INTO catalog_meta VALUES ('kind','snapshot');
                INSERT INTO songs VALUES
                  ('id1','00001','เพลงทดสอบ','ศิลปิน','XMID','MIDI/XMID/0/00001.xmid','{}','11111111111111111111111111111111'),
                  ('id2','00002','ไม่พร้อม','ศิลปิน','XMID','../secret.xmid','{}',NULL);
            """)
        media = self.root / "SONGS" / "MIDI" / "XMID" / "0"
        media.mkdir(parents=True)
        (media / "00001.xmid").write_bytes(b"valid-package-placeholder")

    def test_read_online_db_without_schema_migration(self):
        before = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        info = online.summary(str(self.root))
        self.assertEqual(info["songs"], 2)
        self.assertTrue(os.path.samefile(info["database"], self.db_path),
                        "Drive for Desktop may expose 8.3 and long Windows path aliases")
        rows = online.search(str(self.root), "เพลง")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "00001")
        self.assertTrue(rows[0]["local_path"].endswith("00001.xmid"))
        self.assertIsNone(online.search(str(self.root), "ไม่พร้อม")[0]["local_path"])
        self.assertEqual(before, hashlib.sha256(self.db_path.read_bytes()).hexdigest())
        self.assertFalse(Path(str(self.db_path) + "-wal").exists())
        self.assertFalse(Path(str(self.db_path) + "-shm").exists())
        with closing(sqlite3.connect(self.db_path)) as db:
            fields = {row[1] for row in db.execute("PRAGMA table_info(songs)")}
        self.assertNotIn("duplicate_of", fields)

    def test_read_only_duplicate_report(self):
        self.assertEqual(online.duplicate_report(str(self.root)), [])
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute("INSERT INTO songs VALUES (?,?,?,?,?,?,?,?)",
                       ("id3", "00003", "เพลงซ้ำ", "ศิลปิน", "XMID",
                        "MIDI/XMID/0/00003.xmid", "{}", "11111111111111111111111111111111"))
            db.commit()
        self.assertEqual(online.duplicate_report(str(self.root))[0]["copies"], 2)

    def test_reject_incompatible_database(self):
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute("UPDATE catalog_meta SET value='legacy' WHERE key='format'")
            db.commit()
        with self.assertRaises(ValueError):
            online.summary(str(self.root))

    def test_reject_path_escape(self):
        self.assertIsNone(online._local_media(self.root, "../../private.mid"))
        self.assertIsNone(online._local_media(self.root, "C:/Windows/secret.mid"))


if __name__ == "__main__":
    unittest.main()
