"""Integration smoke for Song Studio -> offline XStageSong -> Karaoke PC."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


export = load_module("songstudio-pc/song_export.py", "xstage_test_song_export")
pc_export = load_module("songstudio-pc/pc_library_export.py", "xstage_test_pc_library_export")


class PCExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "SongStudio" / "XStageSong"
        self.destination = self.root / "Karaoke"
        source_audio = self.source / "audio" / "0" / "00001.m4a"
        source_lyrics = self.source / "lyrics" / "0" / "00001.json"
        source_audio.parent.mkdir(parents=True)
        source_lyrics.parent.mkdir(parents=True)
        source_audio.write_bytes(b"media" * 1000)
        source_lyrics.write_text(json.dumps({
            "schemaVersion": 1, "songCode": "00001",
            "lines": [{"startTime": 1.5, "endTime": 3,
                       "text": "สวัสดี", "syllables": [
                           {"start": 1.5, "text": "สวัส", "duration": .5},
                           {"start": 2.0, "text": "ดี", "duration": .5}]}]
        }, ensure_ascii=False), encoding="utf-8")
        (self.source / "lyrics" / "0" / "00001.lrc").write_text(
            "[00:01.50]สวัสดี", encoding="utf-8")
        row = {"webSongId": "audio/0/00001",
               "code": "00001", "title": "เพลงทดสอบ",
               "artist": "ศิลปินทดสอบ", "bucket": "0",
               "audio": {"path": "audio/0/00001.m4a", "size": source_audio.stat().st_size},
               "lyrics": {"path": "lyrics/0/00001.json"},
               "sourceFormat": "M4A"}
        export.publish_batch(self.source, [row])

    def tearDown(self):
        self.temp.cleanup()

    def test_copy_both_folders_and_reuse_without_overwriting(self):
        inspected = pc_export.inspect(self.source, str(self.destination), export)
        self.assertEqual(Path(inspected["destination"]).resolve(), (self.destination / "XStageSong").resolve())
        self.assertEqual(inspected["songs"], 1)
        self.assertEqual(inspected["newFiles"], 3)
        created = pc_export.publish(self.source, str(self.destination), export)
        self.assertEqual(created["copied"], 3)
        library = self.destination / "XStageSong"
        self.assertTrue((library / "AUDIO" / "0" / "00001.m4a").is_file())
        self.assertTrue((library / "LYRICS" / "0" / "00001.lrc").is_file())
        self.assertTrue((library / "LYRICS" / "current.json").is_file())
        self.assertTrue(list((library / "LYRICS").glob("catalog-pc-*.json")))
        again = pc_export.publish(self.source, str(library), export)
        self.assertEqual(again["copied"], 0)
        self.assertEqual(again["reused"], 3)
        self.assertEqual(again["songCount"], 1)

    def test_destination_name_exact_and_foreign_catalog_not_overwritten(self):
        library = self.root / "Other" / "XStageSong"
        self.assertEqual(pc_export.destination_root(str(library)), library.resolve())
        (library / "LYRICS").mkdir(parents=True)
        old = library / "LYRICS" / "current.json"
        old.write_text('{"schemaVersion":1,"format":"foreign"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "รูปแบบอื่น"):
            pc_export.publish(self.source, str(library), export)
        self.assertEqual(old.read_text(encoding="utf-8"),
                         '{"schemaVersion":1,"format":"foreign"}')

    def test_karaoke_pc_catalog_and_lyrics_json_roundtrip(self):
        import sys
        sys.path.insert(0, str(ROOT / "windows-pc" / "source"))
        from karaoke.pc_xstagesong import catalog_rows, source_lyrics, import_library
        pc_export.publish(self.source, str(self.destination), export)
        directory = self.destination / "XStageSong"
        base, rows = catalog_rows(str(self.destination))
        self.assertEqual(base, directory.resolve())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "เพลงทดสอบ")
        self.assertEqual(rows[0]["artist"], "ศิลปินทดสอบ")
        self.assertEqual(rows[0]["code"], "00001")
        self.assertEqual(rows[0]["format"], "M4A")
        lyrics = source_lyrics(rows[0]["path"])
        self.assertEqual(lyrics.lines[0].text, "สวัสดี")
        self.assertEqual(lyrics.lines[0].start, 1.5)
        self.assertEqual(lyrics.lines[0].words,
                         [(1.5, "สวัส"), (2.0, "ดี")])
        class FakeLibrary:
            def __init__(self):
                self.records = []
            def upsert_catalog(self, records, preserve_playable=False):
                self.records.extend(records)
                return len(records)
        lib = FakeLibrary()
        count, errors, warnings = import_library(lib, str(directory))
        self.assertEqual((count, errors, warnings), (1, 0, []))
        self.assertEqual(lib.records[0]["path"], rows[0]["path"])

    def test_revised_lyrics_are_versioned_and_play_latest_without_overwrite(self):
        import sys
        sys.path.insert(0, str(ROOT / "windows-pc" / "source"))
        from karaoke.pc_xstagesong import catalog_rows, source_lyrics

        first = pc_export.publish(self.source, str(self.destination), export)
        library = Path(first["destination"])
        original = library / "LYRICS" / "0" / "00001.json"
        old_bytes = original.read_bytes()
        old_pointer = (library / "LYRICS" / "current.json").read_bytes()

        source_lyrics_file = self.source / "lyrics" / "0" / "00001.json"
        doc = json.loads(source_lyrics_file.read_text(encoding="utf-8"))
        doc["lines"][0]["text"] = "แก้ไขเนื้อร้องแล้ว"
        doc["lines"][0]["startTime"] = 2.25
        doc["lines"][0]["syllables"] = []
        source_lyrics_file.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        (self.source / "lyrics" / "0" / "00001.lrc").write_text(
            "[00:02.25]แก้ไขเนื้อร้องแล้ว", encoding="utf-8")
        preview = pc_export.inspect(self.source, str(self.destination), export)
        self.assertEqual(preview["updatedLyrics"], 2)
        self.assertEqual(preview["newFiles"], 2)
        second = pc_export.publish(self.source, str(self.destination), export)
        self.assertEqual(second["copied"], 2)
        self.assertEqual(original.read_bytes(), old_bytes)
        self.assertNotEqual((library / "LYRICS" / "current.json").read_bytes(), old_pointer)
        _, rows = catalog_rows(str(library))
        self.assertEqual(len(rows), 1)
        lyrics = source_lyrics(rows[0]["path"])
        self.assertEqual(lyrics.lines[0].text, "แก้ไขเนื้อร้องแล้ว")
        self.assertEqual(lyrics.lines[0].start, 2.25)
        third = pc_export.publish(self.source, str(self.destination), export)
        self.assertEqual(third["copied"], 0)
        self.assertEqual(third["songCount"], 1)

    def test_content_mismatch_never_overwrites_original(self):
        pc_export.publish(self.source, str(self.destination), export)
        target = self.destination / "XStageSong" / "AUDIO" / "0" / "00001.m4a"
        target.write_bytes(b"different content" * 500)
        before = target.read_bytes()
        with self.assertRaises(FileExistsError):
            pc_export.publish(self.source, str(self.destination), export)
        self.assertEqual(target.read_bytes(), before)

    def test_cancellation_retains_old_pointer(self):
        pc_export.publish(self.source, str(self.destination), export)
        target = self.destination / "XStageSong" / "LYRICS" / "current.json"
        old_pointer = target.read_bytes()
        import threading
        stop = threading.Event()
        stop.set()
        with self.assertRaisesRegex(RuntimeError, "ยกเลิก"):
            pc_export.publish(self.source, str(self.destination), export, cancelled=stop)
        self.assertEqual(target.read_bytes(), old_pointer)


    def test_native_karaoke_sqlite_created_and_preserves_manual_edits(self):
        done = pc_export.publish(self.source, str(self.destination), export)
        db = Path(done["database"])
        self.assertTrue(db.is_file())
        self.assertEqual(done["databaseAction"], "created")
        with closing(sqlite3.connect(db)) as connection, connection:
            row = connection.execute(
                "SELECT code,title,artist,first_lyric,source_catalog FROM songs"
            ).fetchone()
            self.assertEqual(row[:3], ("00001", "เพลงทดสอบ", "ศิลปินทดสอบ"))
            self.assertIn("สวัสดี", row[3])
            self.assertEqual(row[4], "XStageSong PC")
            connection.execute(
                "UPDATE songs SET favorite=1,user_edited=1,title=?,artist=?",
                ("ชื่อที่แก้ใน Karaoke", "ศิลปินที่ผู้ใช้แก้")
            )
        again = pc_export.publish(self.source, str(self.destination), export)
        self.assertEqual(again["databaseAction"], "updated")
        self.assertTrue(list(db.parent.glob("songs-before-songstudio-*.sqlite3")))
        with closing(sqlite3.connect(db)) as connection, connection:
            row = connection.execute(
                "SELECT COUNT(*),favorite,user_edited,title,artist FROM songs"
            ).fetchone()
            self.assertEqual(row, (1, 1, 1, "ชื่อที่แก้ใน Karaoke", "ศิลปินที่ผู้ใช้แก้"))
            self.assertEqual(connection.execute("PRAGMA quick_check(1)").fetchone()[0], "ok")

    def test_existing_foreign_database_is_not_modified(self):
        target = self.destination / "XStageSong" / "DB"
        target.mkdir(parents=True)
        db = target / "songs.sqlite3"
        with closing(sqlite3.connect(db)) as connection, connection:
            connection.execute("CREATE TABLE foreign_data (keep TEXT)")
            connection.execute("INSERT INTO foreign_data VALUES ('safe')")
        with self.assertRaisesRegex(ValueError, "ไม่ใช่ฐานเพลง Karaoke PC"):
            pc_export.publish(self.source, str(self.destination), export)
        with closing(sqlite3.connect(db)) as connection, connection:
            self.assertEqual(connection.execute("SELECT keep FROM foreign_data").fetchone()[0], "safe")

    def test_shared_xstagesong_root_snapshots_lyrics_without_replacing(self):
        first = pc_export.publish(self.source, str(self.source), export)
        self.assertEqual(first["destination"], str(self.source.resolve()))
        self.assertEqual(first["databaseAction"], "created")
        pc_pointer = self.source / "LYRICS" / "current.json"
        self.assertTrue(pc_pointer.is_file())
        catalog = next((self.source / "LYRICS").glob("catalog-pc-*.json"))
        first_row = json.loads(catalog.read_text(encoding="utf-8"))["songs"][0]
        first_lyrics = self.source / first_row["lyrics"]["path"]
        self.assertIn("-pc-snapshot-", first_lyrics.name)
        before = first_lyrics.read_bytes()
        # Simulate a correction to the authoring JSON, not the immutable PC copy.
        editable = self.source / "lyrics" / "0" / "00001.json"
        doc = json.loads(editable.read_text(encoding="utf-8"))
        doc["lines"][0]["text"] = "แก้ไขคำร้อง"
        editable.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        second = pc_export.publish(self.source, str(self.source), export)
        self.assertEqual(first_lyrics.read_bytes(), before)
        self.assertEqual(second["databaseAction"], "updated")
        self.assertTrue((self.source / "DB" / "songs.sqlite3").is_file())

    def test_detect_installed_pc_and_use_its_real_data_sqlite(self):
        install = self.root / "InstalledKaraoke"
        (install / "App").mkdir(parents=True)
        (install / "App" / "XStageKaraoke.exe").write_bytes(b"real executable marker")
        (install / "Data").mkdir()
        inspected = pc_export.inspect(self.source, str(install), export)
        self.assertEqual(Path(inspected["destination"]).resolve(), (install / "Songs" / "XStageSong").resolve())
        self.assertEqual(Path(inspected["database"]).resolve(), (install / "Data" / "songs.sqlite3").resolve())
        self.assertTrue(inspected["databaseInstalled"])
        saved = pc_export.publish(self.source, str(install), export)
        self.assertTrue(Path(saved["database"]).is_file())
        self.assertEqual(saved["indexedSongs"], 1)
        updated = pc_export.publish(self.source, str(install / "Songs"), export)
        self.assertEqual(updated["databaseAction"], "updated")


if __name__ == "__main__":
    unittest.main()
