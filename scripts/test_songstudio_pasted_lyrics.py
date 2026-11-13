"""Owner-supplied untimed lyrics: timing help without replacing the owner's words."""
from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import time
import unittest


ROOT = Path(__file__).resolve().parents[1] / "songstudio-pc"


def module(path, name):
    spec = spec_from_file_location(name, ROOT / path)
    result = module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


align = module("lyric_alignment.py", "songstudio_pasted_lyrics_test")
ai = module("ai_lyrics.py", "songstudio_ai_marker_test")
engine = module("engine.py", "songstudio_pasted_lyrics_engine_test")


def speech_draft():
    return {"source": "AI_DRAFT_UNVERIFIED",
            "lines": [
                {"startTime": 5, "endTime": 7.1, "text": "ฉันเดินทางไกล"},
                {"startTime": 8, "endTime": 10.3, "text": "ยังคงคิดถึงเธอ"},
                {"startTime": 12, "endTime": 14, "text": "แม้เวลาผ่านไป"},
            ]}


class PastedLyricsTests(unittest.TestCase):
    def test_plain_thai_lyrics_remain_verbatim_and_are_timed_monotonically(self):
        original = "ฉันเดินทางไกล\nยังคงคิดถึงเธอ\nแม้เวลาผ่านไป"
        result = align.align_lyrics(original, speech_draft())
        self.assertEqual(result["lines"], 3)
        self.assertEqual([row.split("]", 1)[1]
                          for row in result["rawLrc"].splitlines()],
                         original.splitlines())
        stamps = [line.split("]", 1)[0] for line in result["rawLrc"].splitlines()]
        self.assertEqual(stamps, sorted(stamps))
        self.assertTrue(result["requiresReview"])
        self.assertEqual(result["uncertain"], 0)
        self.assertIn("[00:05.", result["rawLrc"])
        self.assertIn("[00:08.", result["rawLrc"])
        # Whisper's phrase timestamps are approximate; a ~50 ms difference
        # is not a failure of alignment or the owner's verbatim words.
        third_stamp = result["rawLrc"].splitlines()[2].split("]", 1)[0][1:]
        minutes, seconds = third_stamp.split(":")
        self.assertAlmostEqual(int(minutes)*60+float(seconds), 12.0, delta=.5)

    def test_wrong_whisper_words_do_not_replace_correct_owner_lyrics(self):
        original = "ฉันเดินทางไกล\nยังคงคิดถึงเธอนะ\nแม้เวลาผ่านไป"
        result = align.align_lyrics(original, speech_draft())
        self.assertIn("ยังคงคิดถึงเธอนะ", result["rawLrc"])
        self.assertEqual([line.split("]", 1)[1] for line in
                          result["rawLrc"].splitlines()], original.splitlines())
        self.assertEqual(result["lines"], 3)

    def test_unrecognized_middle_line_is_marked_for_manual_review(self):
        original = "ฉันเดินทางไกล\nข้อความท่อนใหม่ไม่ตรงสิ่งที่ฟัง\nแม้เวลาผ่านไป"
        result = align.align_lyrics(original, speech_draft())
        self.assertIn("ข้อความท่อนใหม่ไม่ตรงสิ่งที่ฟัง", result["rawLrc"])
        self.assertGreaterEqual(result["uncertain"], 1)
        self.assertTrue(result["issues"])
        self.assertTrue(all(line.startswith("[") for line in
                            result["rawLrc"].splitlines()))

    def test_refuses_wrong_song_or_instrumental_without_any_speech(self):
        with self.assertRaisesRegex(ValueError, "จับคู่เนื้อร้อง"):
            align.align_lyrics("ชื่นใจเหลือเกิน\nวันนี้ที่เธอยิ้มให้",
                               {"lines":[{"startTime":1, "endTime":5,
                                          "text":"Another English song playing"}]})
        with self.assertRaisesRegex(ValueError, "ไม่มีผลถอดเสียง AI"):
            align.align_lyrics("มีคำร้องอยู่จริง", {"lines":[]})

    def test_rejects_timestamped_lyrics_empty_and_oversized_input(self):
        with self.assertRaisesRegex(ValueError, "ยังไม่มีเวลา"):
            align.align_lyrics("[00:01.15]เนื้อร้องพร้อมเวลา", speech_draft())
        with self.assertRaisesRegex(ValueError, "วางเนื้อเพลง"):
            align.align_lyrics(" \n  ", speech_draft())
        with self.assertRaisesRegex(ValueError, "20,000"):
            align.align_lyrics("ก" * 20001, speech_draft())

    def test_music_marker_uses_branded_text_in_new_draft_and_cached_draft(self):
        payload = {"transcription":[
            {"text":"[เสียงดนตรี]", "offsets":{"from":1000,"to":4000}},
            {"text":"ท่อนนี้ [เสียงดนตรี]", "offsets":{"from":4500,"to":6100}},
            {"text":"[music]", "offsets":{"from":6100,"to":7000}},
        ]}
        draft = ai.json_to_draft(payload, "0001", "th")
        self.assertEqual([line["text"] for line in draft["lines"]],
                         ["[X-Stage Karaoke]", "ท่อนนี้ [X-Stage Karaoke]"])
        self.assertIn("[00:01.00][X-Stage Karaoke]", draft["rawLrc"])
        self.assertNotIn("[เสียงดนตรี]", draft["rawLrc"])
        with TemporaryDirectory() as temp:
            source = Path(temp) / "เพลง.mp3"
            source.write_bytes(b"ID3" * 500)
            old = {"source":"AI_DRAFT_UNVERIFIED",
                   "rawLrc":"[00:01.00][เสียงดนตรี]\n",
                   "lines":[{"startTime":1,"endTime":3,"text":"[เสียงดนตรี]"}]}
            draft_file = ai.draft_path(Path(temp), source)
            draft_file.parent.mkdir(parents=True,exist_ok=True)
            draft_file.write_text(json.dumps(old,ensure_ascii=False),encoding="utf-8")
            loaded = ai.load_draft(Path(temp),source)
            self.assertIn("[X-Stage Karaoke]",loaded["rawLrc"])
            self.assertEqual(loaded["lines"][0]["text"], "[X-Stage Karaoke]")
            self.assertIn("[เสียงดนตรี]",draft_file.read_text(encoding="utf-8"),
                          "Do not silently overwrite user's existing draft file")

    def test_execute_ai_align_reuses_existing_asr_without_modifying_pasted_words(self):
        with TemporaryDirectory() as temp:
            source = Path(temp) / "source.mp3"
            source.write_bytes(b"ID3" * 5000)
            song = {"id":-555,"path":str(source),"code":"T0001",
                    "kind":"MP3","title":"ทดสอบ","artist":"ทดลอง","size":source.stat().st_size}
            original_job = dict(engine.JOB)
            engine.FILE_BY_ID[-555] = song
            words = "ฉันเดินทางไกล\nยังคงคิดถึงเธอ\nแม้เวลาผ่านไป"
            try:
                engine.JOB.update({"state":"running","kind":"ai-align",
                                   "id":"test", "total":1, "completed":0,
                                   "logs":[], "detail":"", "started":time.monotonic()})
                engine.CANCEL.clear()
                with patch.object(engine.AI_LYRICS,"load_draft",return_value=speech_draft()), \
                     patch.object(engine.AI_LYRICS,"transcribe",
                                  side_effect=AssertionError("Whisper should not rerun")):
                    engine.execute_job("ai-align",{"id":-555,"lyrics":words,"language":"th"},
                                       time.monotonic())
                self.assertEqual(engine.JOB["state"],"success")
                result = engine.JOB["result"]
                self.assertIn("ฉันเดินทางไกล", result["rawLrc"])
                self.assertEqual(result["songId"],-555)
                self.assertTrue(source.is_file())
            finally:
                engine.FILE_BY_ID.pop(-555,None)
                engine.JOB.clear()
                engine.JOB.update(original_job)
                engine.CANCEL.clear()


if __name__ == "__main__":
    unittest.main()
