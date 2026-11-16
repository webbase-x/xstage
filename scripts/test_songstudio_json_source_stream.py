"""Regression tests for immediate source-by-code Lyrics JSON discovery."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "json_source_stream", ROOT / "songstudio-pc" / "json_source_stream.py")
streamer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(streamer)


class FastJsonSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def file(self, name, contents=b"test midi file" * 4):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return path.resolve()

    def test_ncns_pair_from_sibling_role_directories_by_filename_code(self):
        mid = self.file("MIDI/NCN/SONG/A/00001.mid")
        lyr = self.file("MIDI/NCN/LYR/A/00001.lyr")
        cur = self.file("MIDI/NCN/CUR/A/00001.cur")
        report = streamer.stream(str(self.root))
        row = next(report["complete"])
        self.assertEqual(row["kind"], "NCN")
        self.assertEqual({path for path, _ in row["files"]}, {mid, lyr, cur})
        self.assertEqual(report["fileCount"], 1)  # LYR/CUR folders not enumerated

    def test_plain_midi_does_not_require_input_json(self):
        midi = self.file("batch/00002.mid")
        report = streamer.stream(str(self.root))
        row = next(report["complete"])
        self.assertEqual(row["kind"], "KAR")  # embedded cues checked on conversion
        self.assertEqual([path for path, _ in row["files"]], [midi])
        self.assertFalse((self.root / "batch/00002.json").exists())

    def test_source_karaoke_kar_is_single_original_file(self):
        kar = self.file("MIDI/KAR/00003.kar")
        row = next(streamer.stream(str(self.root))["complete"])
        self.assertEqual(row["kind"], "KAR")
        self.assertEqual(row["files"][0][0], kar)

    def test_preserve_existing_audio_json_compatibility(self):
        audio = self.file("AUDIO/MP3/SONG/0/00004.mp3")
        lyric = self.file("AUDIO/MP3/LYRICS/0/00004.json", b'{"schemaVersion":1}')
        row = next(streamer.stream(str(self.root))["complete"])
        self.assertEqual(row["kind"], "MP3")
        self.assertEqual({x for x, _ in row["files"]}, {audio, lyric})

    def test_missing_cursor_is_not_published(self):
        self.file("MIDI/NCN/SONG/A/00005.mid")
        self.file("MIDI/NCN/LYR/A/00005.lyr")
        report = streamer.stream(str(self.root))
        self.assertEqual(list(report["complete"]), [])
        self.assertEqual(report["incompleteCount"], 1)

    def test_cancelled_discovery_stops_without_fake_completion(self):
        cancelled = threading.Event()
        self.file("MIDI/KAR/00006.kar")
        report = streamer.stream(str(self.root), cancelled=cancelled)
        cancelled.set()
        with self.assertRaises(RuntimeError):
            next(report["complete"])

    def test_engine_uses_stream_without_global_preflight(self):
        engine = (ROOT / "songstudio-pc" / "engine.py").read_text(encoding="utf-8")
        self.assertIn('source_stream=source_stream.stream', engine)
        self.assertIn('เริ่มจับคู่รหัสไฟล์ต้นฉบับ', engine)
        exporter = (ROOT / "songstudio-pc" / "json_pro_export.py").read_text(
            encoding="utf-8")
        self.assertIn("source_stream(str(source)", exporter)
        self.assertIn("known_total = None", exporter)


if __name__ == "__main__":
    unittest.main()
