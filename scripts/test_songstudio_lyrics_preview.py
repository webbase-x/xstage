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
        (mock_model / "models").mkdir(parents=True)
        (mock_model / "models" / "ggml-base.bin").write_bytes(b"mock")
        with patch.object(ai, "readiness", return_value=(True, "")):
            def fake_run(cmd, cancelled, phase, on_status, **_):
                if "ffmpeg" in str(cmd[0]):
                    Path(cmd[-1]).write_bytes(b"WAV-data" * 10000)
                else:
                    dest = Path(str(cmd[cmd.index("-of") + 1]) + ".json")
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

    def test_whisper_readiness_explains_missing_executable(self):
        good, reason = ai.readiness(self.dir)
        self.assertFalse(good)
        self.assertIn("whisper-cli.exe", reason)

    def test_ai_retries_auto_language_once_when_first_pass_has_no_words(self):
        source = self.dir / "new-vocals.wav"
        source.write_bytes(b"RIFF" + b"z" * 90000)
        attempts = []

        def fake_run(cmd, cancelled, phase, on_status, **_):
            if "ffmpeg" in str(cmd[0]):
                Path(cmd[-1]).write_bytes(b"WAV" * 11000)
                return
            language = str(cmd[cmd.index("-l") + 1])
            attempts.append(language)
            dest = Path(str(cmd[cmd.index("-of") + 1]) + ".json")
            text = [{"text": "เสียงร้อง", "offsets": {"from": 1000, "to": 2200}}] \
                if language == "auto" else []
            dest.write_text(json.dumps({"transcription": text}), encoding="utf-8")

        model_dir = self.dir / "models"
        model_dir.mkdir()
        (model_dir / "ggml-base.bin").write_bytes(b"mock")
        with patch.object(ai, "readiness", return_value=(True, "")), \
             patch.object(ai, "_run", side_effect=fake_run):
            draft = ai.transcribe(
                source, "NEWVOCALS", self.dir, self.dir, "ffmpeg",
                __import__("threading").Event(), lambda status: None, language="th")
        self.assertEqual(attempts, ["th", "auto"])
        self.assertEqual(draft["language"], "auto")
        self.assertEqual(draft["lines"][0]["text"], "เสียงร้อง")
        self.assertTrue(draft["requiresReview"])

    def test_short_ffmpeg_pipe_reads_do_not_insert_silence(self):
        live = load("live_preview.py", "xstage_short_read_live_preview_test")
        class ShortReadPipe:
            def __init__(self, data):
                self.data, self.offset = data, 0
            def read(self, count):
                take = min(3, count)
                out = self.data[self.offset:self.offset + take]
                self.offset += len(out)
                return out
        pcm = bytes(range(32))
        pipe = ShortReadPipe(pcm)
        self.assertEqual(live.read_pcm_block(pipe, 16), pcm[:16])
        self.assertEqual(live.read_pcm_block(pipe, 16), pcm[16:])
        self.assertEqual(live.read_pcm_block(pipe, 16), b"")
        tail = ShortReadPipe(b"\x01\x00\x01\x00")
        self.assertEqual(live.read_pcm_block(tail, 8),
                         b"\x01\x00\x01\x00" + b"\x00" * 4)

    def test_whisper_uses_ascii_relative_model_path_under_thai_install(self):
        # Regression for Windows MSVC whisper.cpp 0xC0000409 when -m has
        # Thai path elements. The working directory can contain Unicode.
        runtime = self.dir / "โปรแกรมเพลงไทย" / ".runtime"
        (runtime / "models").mkdir(parents=True)
        (runtime / "models" / "ggml-base.bin").write_bytes(b"model")
        source = self.dir / "เพลงทดสอบ.mp3"
        source.write_bytes(b"ID3" * 6000)
        calls = []

        def fake_run(cmd, cancelled, phase, on_status, **kwargs):
            calls.append((list(map(str, cmd)), kwargs.get("cwd")))
            if "ffmpeg" in str(cmd[0]):
                Path(cmd[-1]).write_bytes(b"wav" * 15000)
            else:
                dest = Path(str(cmd[cmd.index("-of") + 1]) + ".json")
                dest.write_text(json.dumps({"transcription": [
                    {"text": "เพลงทดสอบ", "offsets": {"from": 1000, "to": 3000}}
                ]}), encoding="utf-8")
        with patch.object(ai, "readiness", return_value=(True, "")), \\
             patch.object(ai, "_run", side_effect=fake_run), \\
             patch.object(ai, "resources", return_value=(runtime / "whisper" / "whisper-cli.exe",
                                                        runtime / "models" / "ggml-base.bin")):
            result = ai.transcribe(source, "001", self.dir, runtime,
                                   "ffmpeg", __import__("threading").Event(),
                                   lambda _: None)
        self.assertEqual(result["lines"][0]["text"], "เพลงทดสอบ")
        args, working_directory = calls[-1]
        self.assertEqual(working_directory, runtime)
        self.assertEqual(args[args.index("-m") + 1], str(Path("models") / "ggml-base.bin"))
        self.assertTrue(args[args.index("-m") + 1].isascii())
        self.assertTrue(Path(args[args.index("-f") + 1]).is_absolute())

    def test_ai_cannot_generate_true_words_from_instrumental_midi(self):
        midi = self.dir / "000012.mid"
        midi.write_bytes(b"missing-lyrics")
        with self.assertRaisesRegex(ValueError, "MIDI"):
            ai.transcribe(midi, "000012", self.dir, self.dir, "ffmpeg",
                          __import__("threading").Event(), lambda status: None)


    def test_preview_title_and_artist_from_lrc_metadata(self):
        self.audio.with_suffix(".lrc").write_text(
            "[ti:เพลงที่ถูกต้อง]\n[ar:ศิลปินต้นฉบับ]\n[00:01.25]เนื้อเพลงจริง\n",
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
            "[ti:ชื่อเพลงสำหรับฟัง]\n[ar:ผู้ร้องทดสอบ]\n[00:01.00]ร้องเพลง\n",
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


    def test_source_picker_offers_only_discovered_types(self):
        other_midi = self.dir / "000012.mid"
        other_midi.write_bytes(b"MThd" + b"x" * 1500)
        midi_row = {"id": 13, "path": str(other_midi), "code": "000012",
                    "kind": "MID", "title": "ทดสอบ", "artist": ""}
        engine.FILES.append(midi_row)
        engine.FILE_BY_ID[13] = midi_row
        report = engine.preview_source_report(12)
        values = {option["value"] for option in report["options"]}
        self.assertIn("auto", values)
        self.assertIn("audio:12", values)
        self.assertIn("midi:13", values)
        self.assertNotIn("audio:13", values)
        with patch.object(engine, "ffmpeg_binary", return_value="ffmpeg"):
            audio = engine.prepare_live_preview(12, source_choice="audio:12")
            self.assertTrue(audio["has_backing"])
            self.assertFalse(audio["has_midi"])
            with self.assertRaisesRegex(ValueError, "ไม่มีอยู่จริง"):
                engine.prepare_live_preview(12, source_choice="audio:13")
            with patch.object(engine, "sf_available", return_value=True):
                synth = engine.prepare_live_preview(12, source_choice="midi:13")
            self.assertFalse(synth["has_backing"])
            self.assertTrue(synth["has_midi"])
        self.assertEqual(
            engine.LIVE_TICKETS[audio["ticket"]]["audio"], self.audio)
        self.assertEqual(
            engine.LIVE_TICKETS[synth["ticket"]]["midi"], other_midi)

    def test_audio_without_lyrics_reports_no_timed_karaoke(self):
        with patch.object(engine, "DATA", self.dir), patch.object(ai, "available", return_value=False):
            report = engine.preview_source_report(12)
        self.assertFalse(report["timedLyricsReady"])
        self.assertFalse(report["complete"])
        self.assertFalse(any(option["kind"] == "inspect" for option in report["options"]))


    def test_karaoke_pc_enhanced_lrc_syllables_and_plain_lrc_no_fake_cues(self):
        """Web stage must receive genuinely timestamped words, never guesses."""
        export = engine._song_export_module()
        original = ("[ti:เพลงทดลอง]\n[offset:250]\n"
                    "[00:01.00]<00:01.00>สวัสดี <00:02.50>โลก\n"
                    "[00:04.00]บรรทัดสอง\n")
        document = export.lrc_to_json(original, "10001")
        self.assertEqual(document["audioOffsetMs"], 250)
        self.assertEqual(document["rawLrc"], original)
        self.assertEqual(document["lines"][0]["text"], "สวัสดี โลก")
        self.assertEqual([unit["text"] for unit in document["lines"][0]["syllables"]],
                         ["สวัสดี ", "โลก"])
        self.assertEqual([unit["start"] for unit in document["lines"][0]["syllables"]],
                         [1.0, 2.5])
        self.assertEqual([unit["duration"] for unit in document["lines"][0]["syllables"]],
                         [1.5, 1.5])
        self.assertNotIn("syllables", document["lines"][1])

    def test_enhanced_lrc_repeated_stamps_shift_word_cues(self):
        document = engine._song_export_module().lrc_to_json(
            "[00:01.00][00:05.00]<00:01.00>ร้อง <00:02.00>เพลง\n", "20001")
        self.assertEqual(len(document["lines"]), 2)
        self.assertEqual(document["lines"][0]["syllables"][0]["start"], 1.)
        self.assertEqual(document["lines"][1]["syllables"][0]["start"], 5.)
        self.assertEqual(document["lines"][1]["syllables"][1]["start"], 6.)

    def test_enhanced_lrc_preview_gives_real_token_timing(self):
        self.audio.with_suffix(".lrc").write_text(
            "[00:01.00]<00:01.00>ร้อง<00:02.00>ตาม\n", encoding="utf-8")
        data = engine.preview_lyrics(12)
        self.assertEqual(data["status"], "found")
        self.assertEqual(data["lines"][0]["text"], "ร้องตาม")
        self.assertEqual(
            [(entry["text"], entry["startTime"])
             for entry in data["lines"][0]["characters"]],
            [("ร้อง", 1.), ("ตาม", 2.)])

if __name__ == "__main__":
    unittest.main()
