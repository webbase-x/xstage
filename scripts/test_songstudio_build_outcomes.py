"""Guard against misleading success when a Song Studio build produces no verified output."""
from __future__ import annotations
import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("songstudio_engine_build_guard", ROOT / "songstudio-pc" / "engine.py")
engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(engine)


class BuildOutcomeTests(unittest.TestCase):
    def test_zero_created_zero_verified_skipped_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "songs"
            fake_export = SimpleNamespace(
                songs_root=lambda workspace: root,
                existing_records=lambda root: [],
                journal_records=lambda root: [],
            )
            with patch.object(engine, "_song_export_module", return_value=fake_export), \
                 patch.dict(engine.PREFS, {"workspace": tmp}):
                with self.assertRaisesRegex(RuntimeError, "ไม่มีเพลงที่สร้างสำเร็จ"):
                    engine.build_library([], "original", {"audio_only": False})

    def test_build_with_item_errors_must_not_be_marked_success(self):
        rows = [{"id": 1, "path": "dummy.m4a", "title": "เพลง", "code": "1"}]
        outcome = {"created": 1, "skipped": 0, "errors": 1, "m4aCount": 1,
                   "lyricsCount": 0, "message": "1 created, 1 error"}
        with patch.object(engine, "build_library", return_value=outcome), \
             patch.dict(engine.FILE_BY_ID, {1: rows[0]}, clear=True), \
             patch.dict(engine.PREFS, {"mode": "original"}):
            engine.JOB = {"id": "test", "kind": "build", "state": "running",
                          "total": 1, "completed": 0, "logs": [],
                          "started": 0, "updated": 0}
            engine.CANCEL.clear()
            engine.execute_job("build", {"ids": [1]}, 0)
            self.assertEqual(engine.JOB["state"], "error")
            self.assertEqual(engine.JOB["result"]["created"], 1)
            self.assertEqual(engine.JOB["result"]["errors"], 1)


if __name__ == "__main__":
    unittest.main()
