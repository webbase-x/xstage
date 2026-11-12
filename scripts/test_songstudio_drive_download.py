"""Regression tests: SONG, DB and ZIP downloads must never create Drive folders."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "songstudio_google_drive_for_tests", ROOT / "songstudio-pc" / "google_drive.py")
drive = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(drive)


class ReadOnlyDriveDownloadTests(unittest.TestCase):
    def setup_drive(self, *, root=True, songs=True, files=None):
        instance = drive.GoogleDrive.__new__(drive.GoogleDrive)
        folders = {
            "root": ([{"id": "studio-folder", "name": drive.ROOT_NAME,
                       "mimeType": "application/vnd.google-apps.folder"}] if root else []),
            "studio-folder": ([{"id": "songs-folder", "name": "songs",
                               "mimeType": "application/vnd.google-apps.folder"}] if songs else []),
            "songs-folder": files if files is not None else [],
        }
        instance.list_children = Mock(side_effect=lambda parent: folders.get(parent, []))
        instance.folder = Mock(side_effect=AssertionError("Downloads must not create folders"))
        return instance

    def test_missing_root_is_read_only_for_all_download_types(self):
        for kind in ("songs", "db", "zip"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                g = self.setup_drive(root=False)
                with self.assertRaisesRegex(drive.GoogleError, "ไม่พบโฟลเดอร์"):
                    g.download_library(tmp, kind=kind)
                g.folder.assert_not_called()
                self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_missing_songs_is_read_only_for_all_download_types(self):
        for kind in ("songs", "db", "zip"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                g = self.setup_drive(songs=False)
                with self.assertRaisesRegex(drive.GoogleError, "songs"):
                    g.download_library(tmp, kind=kind)
                g.folder.assert_not_called()

    def test_empty_library_has_specific_message_and_does_not_create(self):
        for kind in ("songs", "db", "zip"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                g = self.setup_drive()
                with self.assertRaisesRegex(drive.GoogleError, "พบโฟลเดอร์คลังเพลง"):
                    g.download_library(tmp, kind=kind)
                g.folder.assert_not_called()


if __name__ == "__main__":
    unittest.main()
