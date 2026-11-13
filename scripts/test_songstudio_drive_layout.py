"""Regression tests for private XStageWeb v2 Drive layout and legacy safety."""
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
        self.assertEqual(layout.LEGACY_ONLINE_ROOT, "StageWeb")
        self.assertEqual(layout.LAYOUT_VERSION, 2)

    def test_audio_buckets_by_code_not_local_folder(self):
        self.assertEqual(str(layout.media_drive_path(
            "audio/8/My Song.m4a", code="A205")),
            "AUDIO/M4A/Songs/A/My Song.m4a")
        self.assertEqual(str(layout.media_drive_path(
            "audio/_/Song.mp3", code="9012")),
            "AUDIO/MP3/Songs/9/Song.mp3")
        self.assertEqual(str(layout.media_drive_path(
            "audio/4/Track.m4a", code="Z101")),
            "AUDIO/M4A/Songs/Z/Track.m4a")

    def test_lyrics_follow_code_bucket(self):
        self.assertEqual(str(layout.media_drive_path(
            "lyrics/_/Track.json", code="B88")),
            "AUDIO/M4A/Lyrics/B/Track.json")
        self.assertEqual(str(layout.media_drive_path(
            "lyrics/0/Track.lrc", code="05")),
            "AUDIO/M4A/Lyrics/0/Track.lrc")

    def test_unknown_code_does_not_lose_file(self):
        self.assertEqual(str(layout.media_drive_path(
            "audio/_/เพลง.m4a", code="เพลง")),
            "AUDIO/M4A/Songs/_/เพลง.m4a")

    def test_traversal_and_unhandled_types_fail_closed(self):
        for name in ("audio/../../secret.m4a", "/absolute.m4a",
                     "audio/a/movie.avi", "lyrics/3/a.exe"):
            with self.subTest(name=name):
                with self.assertRaises(layout.PublishError):
                    layout.media_drive_path(name, code="123")

    def test_existing_legacy_root_reused_without_new_root(self):
        class Drive:
            def __init__(self):
                self.made = []
            def list_children(self, parent):
                return ([{"id": "old-123", "name": "StageWeb",
                          "mimeType": layout.FOLDER_MIME}]
                        if parent == "root" else [])
            def folder(self, parent, name):
                self.made.append(name)
                raise AssertionError("Must not create a duplicate root")
        drive = Drive()
        self.assertEqual(layout.OnlinePublisher(drive)._existing_root(), "old-123")
        self.assertFalse(drive.made)

    def test_two_visible_roots_stop_instead_of_merging(self):
        class Drive:
            def list_children(self, parent):
                return [{"id": str(i), "name": name,
                         "mimeType": layout.FOLDER_MIME}
                        for i, name in enumerate(("StageWeb", "XStageWeb"))]
        with self.assertRaises(layout.PublishError):
            layout.OnlinePublisher(Drive())._existing_root()


if __name__ == "__main__":
    unittest.main()
