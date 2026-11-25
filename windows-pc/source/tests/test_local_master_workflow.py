"""Regression for local-first PC/Online catalog and non-destructive transfer."""
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import sqlite3
import subprocess
import sys
import threading
from karaoke.library_setup import prepare_online
from karaoke.local_master import activate, kind, snapshot
from karaoke.library import SongLibrary
from karaoke.shared_catalog_builder import build
from karaoke.shared_song_library import SharedSongLibrary
from test_shared_catalog_builder import _xmid

MIDI = bytes.fromhex("4d546864000000060000000100604d54726b0000000400ff2f00")

class LocalMasterWorkflowTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / "App"
        self.data = self.home / "data"
        self.data.mkdir(parents=True)
        self.drive = self.base / "My Drive"
        self.drive.mkdir()
        self.source = self.base / "External"
        self.source.mkdir()
        self.file = self.source / "10001.xmid"
        self.file.write_bytes(_xmid("10001", "เพลง", "นักร้อง", MIDI))

    def test_move_gate_and_resume_preserve_original(self):
        with patch("karaoke.library_setup.drive_roots", return_value=[]):
            with self.assertRaises(ValueError):
                prepare_online(self.source, self.drive)
        with patch("karaoke.library_setup.drive_roots", return_value=[self.drive]):
            root = prepare_online(self.source, self.drive)
            target = root / "SONGS/MIDI/10001.xmid"
            self.assertEqual(target.read_bytes(), self.file.read_bytes())
            self.assertEqual(prepare_online(self.source, self.drive), root)
            self.assertTrue((root / "DB").is_dir())
            target.write_bytes(b"do not overwrite")
            with self.assertRaises(ValueError):
                prepare_online(self.source, self.drive)
            self.assertEqual(target.read_bytes(), b"do not overwrite")
            self.assertTrue(self.file.is_file())

    def test_local_first_and_keep_duplicate_midi(self):
        with patch("karaoke.library_setup.drive_roots", return_value=[self.drive]):
            root = prepare_online(self.source, self.drive)
        duplicate = root / "SONGS/MIDI/10002.xmid"
        duplicate.write_bytes(self.file.read_bytes())
        pending = self.home / "DB/.online-pending.sqlite3"
        result = build(root, deduplicate=False, local_database=pending)
        self.assertEqual(result["accepted"], 2)
        self.assertEqual(result["duplicates"], 0)
        for database in (pending, root / "DB/songs.sqlite3"):
            with closing(sqlite3.connect(database)) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM songs").fetchone()[0], 2)
                self.assertEqual(db.execute("SELECT COUNT(midi_md5) FROM songs").fetchone()[0], 0)
                self.assertEqual(db.execute("PRAGMA quick_check").fetchone()[0], "ok")
        # Separate duplicate review is read-only.
        self.assertEqual(build(root, publish=False)["duplicates"], 1)
        settings = {"pending_online_master": {"root": str(root), "generation": result["generation"]}}
        native = self.home / "DB/songs.sqlite3"
        SongLibrary(native)
        self.assertEqual(kind(native), "pc")
        self.assertEqual(activate(self.home, self.data, settings, installed=True), native)
        self.assertEqual(kind(native), "online")
        self.assertEqual(SharedSongLibrary(root, database=native).count(), 2)
        self.assertTrue((native.parent / settings["pc_only_backup"]).is_file())
        settings["pending_pc_only"] = True
        activate(self.home, self.data, settings, installed=True)
        self.assertEqual(kind(native), "pc")
        self.assertTrue(self.file.exists())

    def test_installed_legacy_migration_preserves_database(self):
        legacy = self.data / "songs.sqlite3"
        lib = SongLibrary(legacy)
        lib.upsert_catalog([{"path": str(self.file), "code": "10001", "title": "เพลง",
                             "artist": "นักร้อง", "kind": "MIDI", "playable": 1}])
        native = activate(self.home, self.data, {}, installed=True)
        self.assertEqual(native, self.home / "DB/songs.sqlite3")
        self.assertEqual(SongLibrary(native).count(), 1)
        self.assertEqual(SongLibrary(legacy).count(), 1)
        self.assertTrue(legacy.is_file())

    def test_closed_wal_with_committed_frames_is_recovered_before_replacement(self):
        target = self.data / "songs.sqlite3"
        source = self.data / "new.sqlite3"
        archive = self.data / "archive.sqlite3"
        # Simulate an interrupted process: SQLite has committed a WAL frame,
        # but the last connection never executed its normal cleanup.
        script = (
            "import os, sqlite3, sys\n"
            "db=sqlite3.connect(sys.argv[1])\n"
            "db.execute('PRAGMA journal_mode=WAL')\n"
            "db.execute('PRAGMA wal_autocheckpoint=0')\n"
            "db.execute('CREATE TABLE songs (title TEXT)')\n"
            "db.execute(\"INSERT INTO songs VALUES ('committed')\")\n"
            "db.commit()\n"
            "os._exit(0)\n"
        )
        subprocess.run([sys.executable, "-c", script, str(target)], check=True)
        self.assertTrue(target.with_name(target.name + "-wal").is_file())
        with closing(sqlite3.connect(source)) as db:
            db.execute("CREATE TABLE songs (title TEXT)")
            db.execute("INSERT INTO songs VALUES ('replacement')")
            db.commit()
        snapshot(target, archive)
        snapshot(source, target)
        with closing(sqlite3.connect(archive)) as db:
            self.assertEqual(db.execute("SELECT title FROM songs").fetchone()[0], "committed")
        with closing(sqlite3.connect(target)) as db:
            self.assertEqual(db.execute("SELECT title FROM songs").fetchone()[0], "replacement")
        for suffix in ("-wal", "-shm", "-journal"):
            self.assertFalse(target.with_name(target.name + suffix).exists())

    def test_active_wal_reader_blocks_replacement_and_preserves_database(self):
        target = self.data / "songs.sqlite3"
        source = self.data / "new.sqlite3"
        with closing(sqlite3.connect(source)) as db:
            db.execute("CREATE TABLE songs (title TEXT)")
            db.execute("INSERT INTO songs VALUES ('replacement')")
            db.commit()
        with closing(sqlite3.connect(target)) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("CREATE TABLE songs (title TEXT)")
            writer.execute("INSERT INTO songs VALUES ('original')")
            writer.commit()
            with closing(sqlite3.connect(target)) as reader:
                reader.execute("BEGIN")
                self.assertEqual(reader.execute("SELECT title FROM songs").fetchone()[0], "original")
                writer.execute("UPDATE songs SET title='committed'")
                writer.commit()
                with self.assertRaises(ValueError):
                    snapshot(source, target)
                self.assertEqual(writer.execute("SELECT title FROM songs").fetchone()[0], "committed")
                self.assertEqual(reader.execute("SELECT title FROM songs").fetchone()[0], "original")
                reader.rollback()
        snapshot(source, target)
        with closing(sqlite3.connect(target)) as db:
            self.assertEqual(db.execute("SELECT title FROM songs").fetchone()[0], "replacement")

    def test_cancel_transfer_does_not_remove_source(self):
        cancel = threading.Event()
        cancel.set()
        with patch("karaoke.library_setup.drive_roots", return_value=[self.drive]):
            with self.assertRaises(InterruptedError):
                prepare_online(self.source, self.drive, cancel=cancel)
        self.assertTrue(self.file.is_file())
