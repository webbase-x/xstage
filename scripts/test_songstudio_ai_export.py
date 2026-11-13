"""Offline selectable AI export tests: no real model or Google connection."""
from __future__ import annotations
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ai_export_engine_test", ROOT / "songstudio-pc" / "engine.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


class AIExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.source = self.base / "demo.mp3"
        self.source.write_bytes(b"ID3" + b"x" * 2000)
        self.target = self.base / "downloads"
        self.target.mkdir()
        self.before_imports = dict(engine.AI_IMPORTED)
        self.before_notes = dict(engine.NOTES)
        self.before_download = engine.PREFS["download"]
        engine.AI_IMPORTED.clear()
        engine.NOTES.clear()
        engine.PREFS["download"] = str(self.target)
        engine.AI_IMPORTED[-1] = {
            "id": -1, "path": str(self.source), "code": "A001", "title": "Demo"
        }
        engine.CANCEL.clear()

    def tearDown(self):
        engine.AI_IMPORTED.clear()
        engine.AI_IMPORTED.update(self.before_imports)
        engine.NOTES.clear()
        engine.NOTES.update(self.before_notes)
        engine.PREFS["download"] = self.before_download
        engine.CANCEL.clear()
        self.temp.cleanup()

    def test_only_reviewed_lrc_exported(self):
        engine.NOTES[str(self.source)] = {"lyrics": "[00:10.00]บรรทัดแรก"}
        result = engine.export_ai_lyrics_files(-1, include_lyrics=True)
        self.assertEqual(result["count"], 1)
        self.assertEqual(Path(result["files"][0]).suffix, ".lrc")
        self.assertIn("บรรทัดแรก", Path(result["files"][0]).read_text(encoding="utf-8-sig"))
        self.assertEqual(list(self.target.glob("*.m4a")), [])

    def test_draft_only_is_not_exported_as_approved_lyrics(self):
        with self.assertRaisesRegex(ValueError, "บันทึกเนื้อร้อง"):
            engine.export_ai_lyrics_files(-1, include_lyrics=True)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_instrumental_only_and_unique_filename(self):
        source_music = self.base / "instrumental.m4a"
        source_music.write_bytes(b"A" * 5000)
        with patch.object(engine, "ai_vocals_target",
                          return_value=self.base / "demo - AI Vocals-xyz.m4a"):
            correct = self.base / "demo - AI Instrumental-xyz.m4a"
            source_music.rename(correct)
            first = engine.export_ai_lyrics_files(-1, include_instrumental=True)
            second = engine.export_ai_lyrics_files(-1, include_instrumental=True)
        self.assertEqual(first["count"], 1)
        self.assertEqual(second["count"], 1)
        self.assertNotEqual(first["files"], second["files"])
        self.assertEqual(correct.read_bytes(), b"A" * 5000)
        self.assertEqual(list(self.target.glob("*.lrc")), [])

    def test_requires_selection(self):
        with self.assertRaises(ValueError):
            engine.export_ai_lyrics_files(-1)


if __name__ == "__main__":
    unittest.main()
