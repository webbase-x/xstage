"""Regression tests for strictly V4 XStageWeb AUDIO/LYRICS and legacy rejection."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "songstudio-pc" / "online_publish.py"
SPEC = importlib.util.spec_from_file_location("xstage_online_layout_test", MODULE)
layout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(layout)


class XStageWebLayoutTests(unittest.TestCase):
    def test_new_root_and_pointer_compatibility(self):
        self.assertEqual(layout.ONLINE_ROOT, "XStageWeb")
        self.assertEqual(layout.LAYOUT_VERSION, 4)

    def test_all_media_use_one_flat_audio_folder(self):
        for source, expected in (
                ("audio/8/My Song.m4a", "AUDIO/My Song.m4a"),
                ("audio/_/Song.mp3", "AUDIO/Song.mp3"),
                ("midi/4/Track.mid", "AUDIO/Track.mid"),
                ("video/_/Movie.mp4", "AUDIO/Movie.mp4"),
                ("audio/_/Piano.sf2", "AUDIO/Piano.sf2")):
            with self.subTest(source=source):
                self.assertEqual(str(layout.media_drive_path(source, code="A205")), expected)

    def test_lyrics_json_only_in_one_flat_folder(self):
        self.assertEqual(str(layout.media_drive_path(
            "lyrics/0/Track.json", code="B88")), "LYRICS/Track.json")
        for source in ("lyrics/0/Track.lrc", "lyrics/0/Track.lyr",
                       "midi_cursor/0/Track.cur", "midi_lyrics/0/Track.lyr"):
            with self.subTest(source=source):
                with self.assertRaises(layout.PublishError):
                    layout.media_drive_path(source, code="B88")

    def test_unknown_code_does_not_lose_file(self):
        self.assertEqual(str(layout.media_drive_path(
            "audio/_/เพลง.m4a", code="เพลง")), "AUDIO/เพลง.m4a")

    def test_traversal_and_unhandled_types_fail_closed(self):
        for name in ("audio/../../secret.m4a", "/absolute.m4a",
                     "audio/a/movie.avi", "lyrics/3/a.exe"):
            with self.subTest(name=name):
                with self.assertRaises(layout.PublishError):
                    layout.media_drive_path(name, code="123")

    def test_only_v4_root_is_discovered(self):
        class Drive:
            def __init__(self, roots):
                self.roots = roots
            def list_children(self, parent):
                return self.roots
        old = [{"id": "old", "name": "StageWeb",
                "mimeType": layout.FOLDER_MIME}]
        self.assertIsNone(layout.OnlinePublisher(Drive(old))._existing_root())
        modern = old + [{"id": "v4", "name": "XStageWeb",
                         "mimeType": layout.FOLDER_MIME}]
        self.assertEqual(layout.OnlinePublisher(Drive(modern))._existing_root(), "v4")

    def test_no_pointer_does_not_discard_unindexed_media(self):
        class Drive:
            def __init__(self, filename):
                self.filename = filename
            def list_children(self, parent):
                if parent == "library":
                    return [{"id": "a", "name": "AUDIO", "mimeType": layout.FOLDER_MIME},
                            {"id": "l", "name": "LYRICS", "mimeType": layout.FOLDER_MIME}]
                if parent == "a":
                    return [{"id": "f", "name": self.filename, "mimeType": "audio/mpeg"}]
                return []
        for media in ("song.mp3", "song.mid", "movie.mp4"):
            with self.subTest(media=media):
                with self.assertRaisesRegex(layout.PublishError, "current.json"):
                    layout.OnlinePublisher(Drive(media))._read_online("library")
        result = layout.OnlinePublisher(Drive("piano.sf2"))._read_online("library")
        self.assertIsNone(result[0])
        self.assertEqual(result[1], {})

    def test_duplicate_v4_roots_are_rejected(self):
        class Drive:
            def list_children(self, parent):
                return [{"id": str(i), "name": "XStageWeb",
                         "mimeType": layout.FOLDER_MIME} for i in range(2)]
        with self.assertRaisesRegex(layout.PublishError, "ซ้ำ"):
            layout.OnlinePublisher(Drive())._existing_root()


if __name__ == "__main__":
    unittest.main()
