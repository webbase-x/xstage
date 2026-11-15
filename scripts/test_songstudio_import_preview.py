"""Regression coverage for safe read-only import song previews."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "songstudio-pc"
spec = importlib.util.spec_from_file_location("import_preview", ROOT / "import_preview.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class ExportStub:
    def __init__(self, rows):
        self.rows = rows

    def existing_records(self, root):
        return self.rows

    def songs_root(self, folder):
        return Path(folder)

    def safe_media_path(self, root, relative, directory):
        if not relative.startswith(directory + "/"):
            raise ValueError("bad prefix")
        target = (Path(root) / relative).resolve()
        if not target.is_relative_to(Path(root).resolve()):
            raise ValueError("path traversal")
        return target

    def lrc_to_json(self, value, code):
        return {"lines": [{"startTime": 1, "endTime": 3, "text": "ทดสอบ"}]}


class ImportPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "audio" / "0").mkdir(parents=True)
        (self.root / "lyrics" / "0").mkdir(parents=True)
        self.audio = self.root / "audio" / "0" / "00001.mp3"
        self.lyric = self.root / "lyrics" / "0" / "00001.json"
        self.audio.write_bytes(b"ID3" + b"x" * 1000)
        self.doc = {"schemaVersion": 1, "songCode": "00001",
                    "lines": [{"startTime": 1.25, "endTime": 3.5, "text": "ทดสอบ"}]}
        self.lyric.write_text(json.dumps(self.doc, ensure_ascii=False), encoding="utf-8")
        self.export = ExportStub([{"code": "00001", "title": "เพลงทดสอบ",
                                   "artist": "ศิลปิน", "audio": {"path": "audio/0/00001.mp3"},
                                   "lyrics": {"path": "lyrics/0/00001.json"}}])

    def tearDown(self):
        self.temp.cleanup()

    def test_pc_preview_is_read_only_and_paged(self):
        orig_audio = self.audio.read_bytes()
        orig_lyric = self.lyric.read_bytes()
        items = mod.scan("pc", "", self.root, self.export, None, None)
        self.assertEqual(len(items), 1)
        self.assertEqual(mod.page(items, "เพลง")["rows"][0]["id"], 0)
        self.assertEqual(mod.page(items, "nothing")["total"], 0)
        self.assertEqual(mod.lyrics(items[0], self.export, None)["lines"][0]["startTime"], 1.25)
        self.assertEqual(self.audio.read_bytes(), orig_audio)
        self.assertEqual(self.lyric.read_bytes(), orig_lyric)

    def test_traversal_and_missing_file_are_never_listed(self):
        self.export.rows.append({"code": "99999", "audio": {"path": "audio/../../secret.mp3"}})
        self.export.rows.append({"code": "88888", "audio": {"path": "audio/0/missing.mp3"}})
        items = mod.scan("pc", "", self.root, self.export, None, None)
        self.assertEqual(len(items), 1)

    def test_reject_bad_source_kind(self):
        with self.assertRaises(ValueError):
            mod.scan("wrong", "", self.root, self.export, None, None)


if __name__ == "__main__":
    unittest.main()
