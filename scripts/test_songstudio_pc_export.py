"""Integration smoke for Song Studio -> offline XStageWeb -> Karaoke PC."""
from __future__ import annotations

import importlib.util
import json
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
        self.source = self.root / "SongStudio" / "StageWeb"
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
        self.assertEqual(inspected["destination"], str(self.destination / "XStageWeb"))
        self.assertEqual(inspected["songs"], 1)
        self.assertEqual(inspected["newFiles"], 3)
        created = pc_export.publish(self.source, str(self.destination), export)
        self.assertEqual(created["copied"], 3)
        library = self.destination / "XStageWeb"
        self.assertTrue((library / "AUDIO" / "0" / "00001.m4a").is_file())
        self.assertTrue((library / "LYRICS" / "0" / "00001.lrc").is_file())
        self.assertTrue((library / "LYRICS" / "current.json").is_file())
        self.assertTrue(list((library / "LYRICS").glob("catalog-pc-*.json")))
        again = pc_export.publish(self.source, str(library), export)
        self.assertEqual(again["copied"], 0)
        self.assertEqual(again["reused"], 3)
        self.assertEqual(again["songCount"], 1)

    def test_destination_name_exact_and_foreign_catalog_not_overwritten(self):
        library = self.root / "Other" / "XStageWeb"
        self.assertEqual(pc_export.destination_root(str(library)), library)
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
        from karaoke.pc_stageweb import catalog_rows, source_lyrics, import_library
        pc_export.publish(self.source, str(self.destination), export)
        directory = self.destination / "XStageWeb"
        base, rows = catalog_rows(str(self.destination))
        self.assertEqual(base, directory)
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

    def test_content_mismatch_never_overwrites_original(self):
        pc_export.publish(self.source, str(self.destination), export)
        target = self.destination / "XStageWeb" / "AUDIO" / "0" / "00001.m4a"
        target.write_bytes(b"different content" * 500)
        before = target.read_bytes()
        with self.assertRaises(FileExistsError):
            pc_export.publish(self.source, str(self.destination), export)
        self.assertEqual(target.read_bytes(), before)

    def test_cancellation_retains_old_pointer(self):
        pc_export.publish(self.source, str(self.destination), export)
        target = self.destination / "XStageWeb" / "LYRICS" / "current.json"
        old_pointer = target.read_bytes()
        import threading
        stop = threading.Event()
        stop.set()
        with self.assertRaisesRegex(RuntimeError, "ยกเลิก"):
            pc_export.publish(self.source, str(self.destination), export, cancelled=stop)
        self.assertEqual(target.read_bytes(), old_pointer)


if __name__ == "__main__":
    unittest.main()
