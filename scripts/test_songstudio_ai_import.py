"""Tests the standalone AI Lyrics import path without requiring Google or an AI model."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "songstudio_ai_import_engine_test", ROOT / "songstudio-pc" / "engine.py")
engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(engine)


class IndependentAIImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.one = self.root / "เพลงต้นฉบับ.mp3"
        self.one.write_bytes(b"ID3" + b"A" * 4096)
        self.two = self.root / "second.m4a"
        self.two.write_bytes(b"fake" * 2000)
        self.old_imports = dict(engine.AI_IMPORTED)
        self.old_catalog = list(engine.FILES)
        self.old_by_id = dict(engine.FILE_BY_ID)
        self.old_notes = dict(engine.NOTES)
        self.old_source = engine.PREFS["source"]
        self.old_workspace = engine.PREFS["workspace"]
        self.old_data = engine.DATA
        self.old_import_file = engine.AI_IMPORTS_FILE
        engine.AI_IMPORTED.clear()
        engine.FILES.clear()
        engine.FILE_BY_ID.clear()
        engine.NOTES.clear()
        engine.DATA = self.root
        engine.AI_IMPORTS_FILE = self.root / "ai-imports.json"

    def tearDown(self):
        engine.AI_IMPORTED.clear()
        engine.AI_IMPORTED.update(self.old_imports)
        engine.FILES[:] = self.old_catalog
        engine.FILE_BY_ID.clear()
        engine.FILE_BY_ID.update(self.old_by_id)
        engine.NOTES.clear()
        engine.NOTES.update(self.old_notes)
        engine.PREFS["source"] = self.old_source
        engine.PREFS["workspace"] = self.old_workspace
        engine.DATA = self.old_data
        engine.AI_IMPORTS_FILE = self.old_import_file
        self.temp.cleanup()

    def test_import_picker_json_contract_and_removal(self):
        with patch.object(engine, "open_picker", return_value=json.dumps(
                [str(self.one), str(self.two)], ensure_ascii=False)):
            result = engine.import_vocal_sources()
        self.assertEqual(result["added"], 2)
        self.assertEqual(len(engine.available_vocal_sources()["rows"]), 2)
        self.assertEqual(engine.visible_files(), [])
        with patch.object(engine, "open_picker", return_value=json.dumps([str(self.one)])):
            repeated = engine.import_vocal_sources()
        self.assertEqual(repeated["skipped"], 1)
        engine.remove_vocal_source(result["song"]["id"])
        self.assertTrue(self.one.is_file())
        self.assertEqual(engine.available_vocal_sources()["total"], 1)

    def test_remove_preserves_source_draft_and_reimport(self):
        imported=engine.import_ai_audio(str(self.one))
        original_id=imported["song"]["id"]
        draft=engine.AI_LYRICS.draft_path(self.root, self.one)
        draft.parent.mkdir(parents=True, exist_ok=True)
        draft.write_text('{"source":"AI_DRAFT_UNVERIFIED","lines":[{"text":"test"}]}', encoding="utf-8")
        initial=self.one.read_bytes()
        with patch.dict(engine.JOB, {"state": "idle"}):
            response=engine.remove_vocal_source(original_id)
        self.assertTrue(response["ok"])
        self.assertIn("ไม่ลบ", response["message"])
        self.assertTrue(self.one.exists())
        self.assertEqual(self.one.read_bytes(),initial)
        self.assertTrue(draft.exists(),"AI draft must survive removal")
        self.assertEqual(engine.available_vocal_sources()["total"],0)
        self.assertNotIn(original_id,engine.FILE_BY_ID)
        engine.AI_IMPORTED.clear()
        engine.FILE_BY_ID.clear()
        engine.restore_ai_imports()
        self.assertEqual(engine.available_vocal_sources()["total"],0)
        second=engine.import_ai_audio(str(self.one))
        self.assertFalse(second["alreadyImported"])
        self.assertEqual(engine.available_vocal_sources()["total"],1)
        self.assertTrue(draft.exists())

    def test_cannot_remove_import_during_active_processing(self):
        song=engine.import_ai_audio(str(self.one))["song"]
        with patch.dict(engine.JOB, {"state":"running","kind":"ai-lyrics"}):
            with self.assertRaisesRegex(ValueError,"มีงานกำลังดำเนินการ"):
                engine.remove_vocal_source(song["id"])
        self.assertEqual(engine.available_vocal_sources()["total"],1)
        self.assertTrue(self.one.exists())

    def test_import_picker_cancel_is_non_destructive(self):
        with patch.object(engine, "open_picker", return_value=None):
            response = engine.import_vocal_sources()
        self.assertTrue(response["cancelled"])
        self.assertEqual(engine.available_vocal_sources()["total"], 0)

    def test_new_audio_import_only_affects_ai_menu(self):
        imported = engine.import_ai_audio(str(self.one))
        self.assertTrue(imported["ok"])
        self.assertFalse(imported["alreadyImported"])
        self.assertLess(imported["song"]["id"], 0)
        self.assertEqual(engine.FILES, [])
        self.assertEqual(engine.visible_files(), [])
        self.assertEqual(len(engine.available_vocal_sources()["rows"]), 1)
        self.assertEqual(engine.available_vocal_sources()["rows"][0]["kind"], "MP3")
        self.assertEqual(len(engine.FILE_BY_ID), 1)
        self.assertTrue(engine.AI_IMPORTS_FILE.is_file())
        second = engine.import_ai_audio(str(self.one))
        self.assertTrue(second["alreadyImported"])
        self.assertEqual(second["song"]["id"], imported["song"]["id"])

    def test_scan_regular_library_keeps_independent_ai_selection(self):
        info = engine.import_ai_audio(str(self.one))
        id_value = info["song"]["id"]
        source = self.root / "regular"
        source.mkdir()
        (source / "00001.mp3").write_bytes(b"ID3"+b"B"*2400)
        engine.PREFS["source"] = str(source)
        self.assertEqual(engine.scan_source(), 1)
        self.assertEqual(len(engine.visible_files()), 1)
        self.assertIn(id_value, engine.FILE_BY_ID)
        self.assertEqual(len(engine.available_vocal_sources()["rows"]), 1)
        self.assertEqual(engine.available_vocal_sources()["rows"][0]["id"], id_value)

    def test_import_survives_restart_and_rejects_other_filetypes(self):
        a = engine.import_ai_audio(str(self.one))
        b = engine.import_ai_audio(str(self.two))
        self.assertNotEqual(a["song"]["id"], b["song"]["id"])
        engine.AI_IMPORTED.clear()
        engine.FILE_BY_ID.clear()
        engine.restore_ai_imports()
        self.assertEqual(len(engine.available_vocal_sources()["rows"]), 2)
        self.assertEqual(len(engine.FILE_BY_ID), 2)
        invalid = self.root / "invalid.mid"
        invalid.write_bytes(b"MThd"*400)
        with self.assertRaisesRegex(ValueError, "ไฟล์เสียง"):
            engine.import_ai_audio(str(invalid))
        with self.assertRaisesRegex(ValueError, "ไม่พบไฟล์"):
            engine.import_ai_audio(str(self.root / "missing.mp3"))

    def test_ai_draft_not_auto_published_and_review_required(self):
        song = engine.import_ai_audio(str(self.one))["song"]
        with patch.object(engine.AI_LYRICS, "load_draft", return_value=None):
            with self.assertRaisesRegex(ValueError, "ยังไม่มีฉบับร่าง"):
                engine.approve_ai_lyrics(song["id"], "[00:01.00]เนื้อร้อง")
        draft = {"source": "AI_DRAFT_UNVERIFIED",
                 "rawLrc": "[00:01.00]ร่างเนื้อร้อง", "lines": [
                     {"startTime":1.0,"endTime":3.0,"text":"ร่างเนื้อร้อง"}]}
        with patch.object(engine.AI_LYRICS, "load_draft", return_value=draft):
            found = engine.ai_lyrics_draft(song["id"])
            self.assertTrue(found["hasDraft"])
            self.assertEqual(found["approvedLrc"], "")
            with self.assertRaisesRegex(ValueError, "รูปแบบ LRC"):
                engine.approve_ai_lyrics(song["id"], "ไม่มีเวลา")
            with patch.object(engine, "NOTES_FILE", self.root / "song-metadata.json"):
                response = engine.approve_ai_lyrics(song["id"], "[00:01.00]ทดสอบหนึ่ง\n[00:03.15]ทดสอบสอง")
            self.assertTrue(response["ok"])
            self.assertEqual(response["lines"], 2)
            self.assertIn("[00:03.15]", engine.NOTES[song["path"]]["lyrics"])


if __name__ == "__main__":
    unittest.main()
