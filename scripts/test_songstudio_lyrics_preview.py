"""Lyrics preview and AI draft regressions; no outside network/model download."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
def load(filename, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "songstudio-pc" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

engine = load("engine.py", "xstage_lyric_preview_engine_test")
ai = engine.AI_LYRICS


class LyricPreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.audio = self.dir / "000012.mp3"
        self.audio.write_bytes(b"ID3..." * 1500)
        engine.FILES.clear()
        engine.FILE_BY_ID.clear()
        engine.NOTES.clear()
        engine.FILES.append({"id": 12, "path": str(self.audio), "code": "000012",
                             "kind": "MP3", "title": "ทดสอบ", "artist": "นักร้อง"})
        engine.FILE_BY_ID[12] = engine.FILES[0]

    def tearDown(self):
        self.tmp.cleanup()

    def test_real_lrc_preview_proves_source_and_exact_timestamps(self):
        self.audio.with_suffix(".lrc").write_text(
            "[00:01.25]เริ่มเพลง\n[00:05.75]เนื้อร้องที่สอง\n", encoding="utf-8")
        payload = engine.preview_lyrics(12)
        self.assertEqual(payload["status"], "found")
        self.assertEqual(payload["source"], "LRC")
        self.assertEqual([line["text"] for line in payload["lines"]],
                         ["เริ่มเพลง", "เนื้อร้องที่สอง"])
        self.assertEqual(payload["lines"][0]["startTime"], 1.25)
        self.assertEqual(payload["artist"], "นักร้อง")
        self.assertFalse(payload["requiresReview"])

    def test_missing_lyrics_never_shows_fake_transcript(self):
        with patch.object(engine, "DATA", self.dir), patch.object(ai, "available", return_value=False):
            payload = engine.preview_lyrics(12)
        self.assertEqual(payload["status"], "missing")
        self.assertEqual(payload["lines"], [])
        self.assertTrue(payload["aiEligible"])
        self.assertFalse(payload["aiAvailable"])

    def test_lyric_file_missing_cursor_reports_problem_not_fake_lyrics(self):
        ncndir = self.dir / "NCN"
        for component in ("Song", "Lyrics", "Cursor"):
            (ncndir / component / "0").mkdir(parents=True, exist_ok=True)
        mid = ncndir / "Song" / "0" / "0123.MID"
        mid.write_bytes(b"MThd" + b"\0" * 300)
        lir = ncndir / "Lyrics" / "0" / "0123.LYR"
        lir.write_bytes("ชื่อเพลง\nนักร้อง\nC\n\nทดสอบ".encode("cp874"))
        row = {"id": 20, "path": str(mid), "code": "0123", "title": "ทดสอบ",
               "artist": "นักร้อง", "kind": "MID"}
        engine.FILE_BY_ID[20] = row
        with patch.object(engine, "DATA", self.dir):
            payload = engine.preview_lyrics(20)
        self.assertEqual(payload["status"], "missing")
        self.assertEqual(payload["lines"], [])
        self.assertIn("cursor", payload["message"].lower())
        self.assertFalse(payload["aiAvailable"])

    def test_ai_transcription_json_is_marked_draft_and_preserves_offsets(self):
        data = {"transcription": [
            {"text": " สวัสดีค่ะ", "offsets": {"from": 1250, "to": 3500}},
            {"text": " โลกใบนี้", "offsets": {"from": 3500, "to": 6000}}
        ]}
        draft = ai.json_to_draft(data, "0123", "th")
        self.assertTrue(draft["requiresReview"])
        self.assertEqual(draft["source"], "AI_DRAFT_UNVERIFIED")
        self.assertEqual(draft["lines"][0]["startTime"], 1.25)
        self.assertIn("[00:01.25]สวัสดีค่ะ", draft["rawLrc"])

    def test_ai_transcription_creates_only_unverified_private_draft(self):
        mock_model = self.dir / "model"
        mock_model.mkdir()
        with patch.object(ai, "available", return_value=True):
            def fake_run(cmd, cancelled, phase, on_status, **_):
                if "ffmpeg" in str(cmd[0]):
                    Path(cmd[-1]).write_bytes(b"WAV-data" * 10000)
                else:
                    dest = Path(cmd[cmd.index("-of") + 1] + ".json")
                    dest.write_text(json.dumps({"transcription": [
                        {"text":"ทดสอบ", "offsets":{"from":1000,"to":2700}}
                    ]}), encoding="utf-8")
            with patch.object(ai, "_run", side_effect=fake_run):
                draft = ai.transcribe(
                    self.audio, "000012", self.dir, mock_model, "ffmpeg",
                    __import__("threading").Event(), lambda status: None)
        self.assertEqual(draft["lines"][0]["text"], "ทดสอบ")
        self.assertIsNotNone(ai.load_draft(self.dir, self.audio))
        self.assertFalse((self.dir / "songs" / "current.json").exists())
        self.assertFalse(list(self.dir.rglob("audio-16k.wav")))
        with patch.object(engine, "DATA", self.dir), patch.object(ai, "available", return_value=True):
            response = engine.preview_lyrics(12)
        self.assertEqual(response["status"], "ai-draft")
        self.assertEqual(response["source"], "AI · Whisper (ยังไม่ยืนยัน)")
        self.assertTrue(response["requiresReview"])

    def test_ai_cannot_generate_true_words_from_instrumental_midi(self):
        midi = self.dir / "000012.mid"
        midi.write_bytes(b"missing-lyrics")
        with self.assertRaisesRegex(ValueError, "MIDI"):
            ai.transcribe(midi, "000012", self.dir, self.dir, "ffmpeg",
                          __import__("threading").Event(), lambda status: None)


    def test_preview_title_and_artist_from_lrc_metadata(self):
        self.audio.with_suffix(".lrc").write_text(
            "[ti:เพลงที่ถูกต้อง]\\n[ar:ศิลปินต้นฉบับ]\\n[00:01.25]เนื้อเพลงจริง\\n",
            encoding="utf-8")
        row = engine.FILE_BY_ID[12]
        row["title"] = "000012"
        row["artist"] = ""
        details = engine.preview_song_identity(row)
        self.assertEqual(details["title"], "เพลงที่ถูกต้อง")
        self.assertEqual(details["artist"], "ศิลปินต้นฉบับ")
        payload = engine.preview_lyrics(12)
        self.assertEqual(payload["title"], "เพลงที่ถูกต้อง")
        self.assertEqual(payload["artist"], "ศิลปินต้นฉบับ")
        self.assertEqual(payload["lines"][0]["text"], "เนื้อเพลงจริง")

    def test_live_preview_returns_artist_not_only_title(self):
        self.audio.with_suffix(".lrc").write_text(
            "[ti:ชื่อเพลงสำหรับฟัง]\\n[ar:ผู้ร้องทดสอบ]\\n[00:01.00]ร้องเพลง\\n",
            encoding="utf-8")
        row = engine.FILE_BY_ID[12]
        row["title"] = "000012"
        row["artist"] = ""
        with patch.object(engine, "ffmpeg_binary", return_value="ffmpeg"):
            response = engine.prepare_live_preview(12)
        self.assertEqual(response["title"], "ชื่อเพลงสำหรับฟัง")
        self.assertEqual(response["artist"], "ผู้ร้องทดสอบ")
        self.assertEqual(response["code"], "000012")
        self.assertTrue(response["ticket"])

if __name__ == "__main__":
    unittest.main()
