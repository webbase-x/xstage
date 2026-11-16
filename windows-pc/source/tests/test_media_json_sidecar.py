"""Regression tests for audio/video + same-stem timed Lyrics JSON."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from karaoke.lyrics import json_sidecar, read_timed_json, sidecar_lyrics, timed_json_lyrics
from karaoke.library import MIDI_EXT, AUDIO_EXT, VIDEO_EXT


class MediaJsonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def write_json(self, name, document):
        file = self.folder / name
        file.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        return file

    def document(self):
        return {"schemaVersion": 1, "songCode": "00001",
                "metadata": {"title": "ชื่อเพลงจริง", "artist": "ศิลปินจริง"},
                "lines": [{"startTime": 1.0, "text": "ร้องเพลง",
                           "syllables": [{"start": 1.0, "text": "ร้อง"},
                                         {"start": 1.5, "text": "เพลง"}]},
                          {"startTime": 4.0, "text": "ต่อไป"}]}

    def test_audio_and_video_get_their_own_json_without_cross_pair(self):
        for ext in (".mp3", ".m4a", ".wav", ".mp4", ".mkv", ".avi"):
            with self.subTest(ext=ext):
                media = self.folder / ("00001" + ext)
                media.write_bytes(b"media")
                doc = self.write_json("00001.json", self.document())
                self.assertEqual(json_sidecar(media), doc)
                lyrics = sidecar_lyrics(media)
                self.assertEqual(lyrics.lines[0].text, "ร้องเพลง")
                self.assertEqual(lyrics.at(1.3)[2], "ร้อง")
                self.assertEqual(lyrics.at(1.7)[2], "ร้องเพลง")
        other = self.folder / "00002.mp3"
        other.write_bytes(b"media")
        self.assertIsNone(sidecar_lyrics(other))

    def test_existing_lrc_stays_higher_priority(self):
        media = self.folder / "00001.mp3"
        media.write_bytes(b"media")
        self.write_json("00001.json", self.document())
        (self.folder / "00001.lrc").write_text("[00:02.00]ข้อมูล LRC เดิม", encoding="utf-8")
        self.assertEqual(sidecar_lyrics(media).lines[0].text, "ข้อมูล LRC เดิม")

    def test_bad_schema_timestamps_and_word_times_rejected(self):
        bad = [
            {"schemaVersion": 99, "lines": [{"startTime": 1, "text": "ผิด"}]},
            {"schemaVersion": 1, "lines": [{"startTime": 5, "text": "หนึ่ง"},
                                           {"startTime": 1, "text": "สอง"}]},
            {"schemaVersion": 1, "lines": [{"startTime": float("nan"), "text": "ผิด"}]},
            {"schemaVersion": 1, "lines": [{"startTime": 1, "text": "ผิด",
                                           "syllables": [{"start": -1, "text": "ผิด"}]}]},
        ]
        for doc in bad:
            with self.subTest(doc=doc):
                with self.assertRaises(ValueError):
                    timed_json_lyrics(doc)

    def test_json_size_limit(self):
        file = self.folder / "00001.json"
        with file.open("wb") as target:
            target.truncate(8 * 1024 * 1024 + 1)
        with self.assertRaises(ValueError):
            read_timed_json(file)

    def test_legacy_media_formats_remain_registered(self):
        self.assertTrue({".mid", ".midi", ".kar", ".emk"} <= MIDI_EXT)
        self.assertTrue({".wav", ".mp3", ".wma"} <= AUDIO_EXT)
        self.assertTrue({".mp4", ".avi", ".wmv", ".mkv"} <= VIDEO_EXT)


if __name__ == "__main__":
    unittest.main()
