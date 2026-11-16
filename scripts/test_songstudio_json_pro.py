"""Offline regressions for Song Studio Pro Lyrics JSON/media exporter."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1] / "songstudio-pc"


def load(name):
    spec = importlib.util.spec_from_file_location("studio_pro_test_" + name, BASE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pro = load("json_pro_export")
export = load("song_export")
folder_upload = load("folder_upload")


class JsonProTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.dest = self.root / "result"
        self.source.mkdir()
        self.dest.mkdir()
        self.mp3 = self.source / "00001.mp3"
        self.lrc = self.source / "00001.lrc"
        self.mp3.write_bytes(b"ID3" + b"X" * 3000)
        self.lrc.write_text("[00:02.50]เนื้อร้องบรรทัดแรก\n[00:05.10]บรรทัดสอง", encoding="utf-8")

    def run_export(self, fmt="original", **extra):
        return pro.export_folder(str(self.source), str(self.dest), output_format=fmt,
                                 export=export, scanner=folder_upload, **extra)

    def test_copy_original_json_and_catalog_skip_repeat(self):
        before = hashlib.sha256(self.mp3.read_bytes()).hexdigest()
        first = self.run_export()
        self.assertEqual(first["created"], 1)
        target = self.dest / "XStageSong"
        records = export.existing_records(target)
        self.assertEqual(len(records), 1)
        record = records[0]
        audio = export.safe_media_path(target, record["audio"]["path"], "audio")
        lyrics = export.safe_media_path(target, record["lyrics"]["path"], "lyrics")
        self.assertEqual(hashlib.sha256(audio.read_bytes()).hexdigest(), before)
        doc = json.loads(lyrics.read_text(encoding="utf-8"))
        self.assertEqual(doc["lines"][0]["startTime"], 2.5)
        self.assertEqual(doc["lines"][1]["startTime"], 5.1)
        second = self.run_export()
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(export._read_current(target)[0]["songCount"], 1)
        self.assertEqual(hashlib.sha256(self.mp3.read_bytes()).hexdigest(), before)

    def test_nested_audio_and_lyrics_json_with_conversion(self):
        self.mp3.unlink()
        self.lrc.unlink()
        media = self.source / "Album" / "AUDIO" / "00234.mp3"
        lyric = self.source / "Album" / "LYRICS" / "00234.json"
        media.parent.mkdir(parents=True)
        lyric.parent.mkdir(parents=True)
        media.write_bytes(b"ID3" + b"T" * 3000)
        doc = export.lrc_to_json("[00:05.25]ทดสอบ", "00234")
        lyric.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        def fake_convert(src, out, fmt):
            self.assertEqual(fmt, "m4a")
            out.write_bytes(b"FAKE" + b"M" * 3000)
        result = self.run_export("m4a", convert=fake_convert)
        self.assertEqual(result["created"], 1)
        record = export.existing_records(self.dest / "XStageSong")[0]
        self.assertTrue(record["audio"]["path"].endswith(".m4a"))
        self.assertTrue(media.read_bytes().startswith(b"ID3"))
        self.assertEqual(record["sourceFormat"], "MP3")

    def test_renaming_identical_audio_and_lyrics_does_not_duplicate(self):
        original = self.mp3.read_bytes()
        text = self.lrc.read_text(encoding="utf-8")
        self.assertEqual(self.run_export()["created"], 1)
        (self.source / "99999.mp3").write_bytes(original)
        (self.source / "99999.lrc").write_text(text, encoding="utf-8")
        repeat = self.run_export()
        self.assertEqual(repeat["created"], 0)
        self.assertEqual(repeat["skipped"], 2)
        self.assertEqual(len(export.existing_records(
            self.dest / "XStageSong")), 1)

    def test_editing_only_lyrics_creates_new_immutable_version(self):
        first = self.run_export()
        self.assertEqual(first["created"], 1)
        root = self.dest / "XStageSong"
        original = export.existing_records(root)[0]
        audio_before = export.safe_media_path(root, original["audio"]["path"], "audio")
        lyrics_before = export.safe_media_path(root, original["lyrics"]["path"], "lyrics")
        original_audio = audio_before.read_bytes()
        original_text = lyrics_before.read_text(encoding="utf-8")
        self.lrc.write_text("[00:02.50]คำร้องที่แก้ไขแล้ว\\n[00:05.10]บรรทัดสอง",
                            encoding="utf-8")
        updated = self.run_export()
        self.assertEqual(updated["created"], 1)
        records = export.existing_records(root)
        self.assertEqual(len(records), 2)
        self.assertEqual(audio_before.read_bytes(), original_audio)
        self.assertEqual(lyrics_before.read_text(encoding="utf-8"), original_text)
        self.assertEqual(len({row["lyrics"]["path"] for row in records}), 2)
        self.assertEqual(len({row["webSongId"] for row in records}), 2)
        self.assertNotEqual(records[0]["sourceIdentity"]["lyricsSha256"],
                            records[1]["sourceIdentity"]["lyricsSha256"])
        again = self.run_export()
        self.assertEqual(again["created"], 0)
        self.assertEqual(again["skipped"], 1)

    def test_json_title_and_artist_are_preserved_in_catalog(self):
        self.mp3.unlink()
        self.lrc.unlink()
        midi = self.source / "02345.mid"
        midi.write_bytes(b"MThd" + b"T" * 100)
        doc = export.lrc_to_json("[00:01.50]เพลงไทย", "02345")
        doc["title"] = "ชื่อเพลงจาก JSON"
        doc["artist"] = "ศิลปินจาก JSON"
        (self.source / "02345.json").write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        result = self.run_export()
        self.assertEqual(result["created"], 1)
        saved = export.existing_records(self.dest / "XStageSong")[0]
        self.assertEqual(saved["title"], "ชื่อเพลงจาก JSON")
        self.assertEqual(saved["artist"], "ศิลปินจาก JSON")

    def test_output_formats_do_not_mask_other_formats(self):
        self.run_export()
        def fake_convert(src, out, fmt):
            out.write_bytes(b"FAKE" + bytes(fmt, "utf-8") * 1200)
        second = self.run_export("mp3", convert=fake_convert)
        self.assertEqual(second["created"], 1)
        records = export.existing_records(self.dest / "XStageSong")
        self.assertEqual(len(records), 2)

    def test_cannot_write_into_source_tree(self):
        with self.assertRaisesRegex(ValueError, "ต้นทางและปลายทางต้องแยก"):
            pro.export_folder(str(self.source), str(self.source),
                              output_format="original", export=export,
                              scanner=folder_upload)

    def test_recover_complete_files_after_interrupted_journal_append(self):
        with patch.object(export, "append_journal", side_effect=OSError("crash")):
            with self.assertRaisesRegex(ValueError, "ไม่มีไฟล์ที่ส่งออกสำเร็จ"):
                self.run_export()
        root = self.dest / "XStageSong"
        self.assertFalse((root / "current.json").exists())
        self.assertTrue(any((root / "audio").rglob("*.mp3")))
        resumed = self.run_export()
        self.assertEqual(resumed["created"], 1)
        self.assertEqual(resumed["errors"], 0)
        self.assertEqual(len(export.existing_records(root)), 1)

    def test_exclusive_publish_never_overwrites_racing_file(self):
        stage = self.dest / "pending.json"
        target = self.dest / "new.json"
        stage.write_bytes(b"pending")
        def collision(_source, _target):
            target.write_bytes(b"other-process")
            raise FileExistsError("another writer")
        with patch.object(pro.os, "link", side_effect=collision):
            with self.assertRaises(FileExistsError):
                pro._publish_no_overwrite(stage, target)
        self.assertEqual(target.read_bytes(), b"other-process")
        self.assertEqual(stage.read_bytes(), b"pending")

    def test_recover_when_catalog_publish_was_interrupted(self):
        with patch.object(export, "publish_batch", side_effect=OSError("simulated interruption")):
            with self.assertRaisesRegex(OSError, "interruption"):
                self.run_export()
        root = self.dest / "XStageSong"
        self.assertFalse((root / "current.json").exists())
        self.assertEqual(len(export.journal_records(root)), 1)
        resumed = self.run_export()
        self.assertEqual(resumed["skipped"], 1)
        self.assertEqual(export._read_current(root)[0]["songCount"], 1)
        self.assertFalse((root / ".build-journal.jsonl").exists())

    def test_invalid_lyrics_not_published(self):
        self.lrc.write_text("ไม่มีเวลา", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "ไม่พบเพลง"):
            self.run_export()
        self.assertFalse((self.dest / "XStageSong" / "current.json").exists())


if __name__ == "__main__":
    unittest.main()
