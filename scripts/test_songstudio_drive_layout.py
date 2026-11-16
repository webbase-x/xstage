"""Regression tests for typed/bucketed XStageSong Drive folders and v4 File-ID safety."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "songstudio-pc" / "online_publish.py"
SPEC = importlib.util.spec_from_file_location("xstage_online_layout_test", MODULE)
layout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(layout)


class XStageSongLayoutTests(unittest.TestCase):
    def test_new_root_and_pointer_compatibility(self):
        self.assertEqual(layout.ONLINE_ROOT, "XStageSong")
        self.assertEqual(layout.LAYOUT_VERSION, 4)

    def test_media_uses_shared_typed_bucket_folders(self):
        for source, expected in (
                ("audio/8/My Song.m4a", "AUDIO/M4A/SONG/A/My Song.m4a"),
                ("audio/_/Song.mp3", "AUDIO/MP3/SONG/A/Song.mp3"),
                ("midi/4/Track.mid", "MIDI/MID/SONG/A/Track.mid"),
                ("video/_/Movie.mp4", "VIDEO/MP4/SONG/A/Movie.mp4"),
                ("audio/_/Piano.sf2", "SOUNDFONT/SF2/Piano.sf2")):
            with self.subTest(source=source):
                self.assertEqual(str(layout.media_drive_path(source, code="A205")), expected)

    def test_lyrics_json_only_in_one_flat_folder(self):
        self.assertEqual(str(layout.media_drive_path(
            "lyrics/0/Track.json", code="B88")), "AUDIO/M4A/LYRICS/B/Track.json")
        for source in ("lyrics/0/Track.lrc", "lyrics/0/Track.lyr",
                       "midi_cursor/0/Track.cur", "midi_lyrics/0/Track.lyr"):
            with self.subTest(source=source):
                with self.assertRaises(layout.PublishError):
                    layout.media_drive_path(source, code="B88")

    def test_unknown_code_does_not_lose_file(self):
        self.assertEqual(str(layout.media_drive_path(
            "audio/_/เพลง.m4a", code="เพลง")), "AUDIO/M4A/SONG/_/เพลง.m4a")

    def test_traversal_and_unhandled_types_fail_closed(self):
        for name in ("audio/../../secret.m4a", "/absolute.m4a",
                     "audio/a/movie.exe", "lyrics/3/a.exe"):
            with self.subTest(name=name):
                with self.assertRaises(layout.PublishError):
                    layout.media_drive_path(name, code="123")

    def test_existing_canonical_root_reused_without_new_root(self):
        class Drive:
            def __init__(self):
                self.made = []
            def list_children(self, parent):
                return ([{"id": "existing-123", "name": "XStageSong",
                          "mimeType": layout.FOLDER_MIME}]
                        if parent == "root" else [])
            def folder(self, parent, name):
                self.made.append(name)
                raise AssertionError("Must not create a duplicate root")
        drive = Drive()
        self.assertEqual(layout.OnlinePublisher(drive)._existing_root(), "existing-123")
        self.assertFalse(drive.made)

    def test_two_visible_canonical_roots_stop_instead_of_merging(self):
        class Drive:
            def list_children(self, parent):
                return [{"id": str(i), "name": "XStageSong",
                         "mimeType": layout.FOLDER_MIME} for i in range(2)]
        with self.assertRaises(layout.PublishError):
            layout.OnlinePublisher(Drive())._existing_root()


if __name__ == "__main__":
    unittest.main()
