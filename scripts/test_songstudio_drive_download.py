"""Regression tests: SONG, DB and ZIP downloads must never create Drive folders."""
from __future__ import annotations

import importlib.util
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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

    def test_network_drop_recovers_with_verified_http_range(self):
        payload = b"audio-block-" * 17
        digest = hashlib.md5(payload).hexdigest()
        calls = []
        class FailingResponse(io.BytesIO):
            status = 200
            headers = {}
            def read(self, count=-1):
                if self.tell() >= 12:
                    raise ConnectionResetError("simulated Wi-Fi interruption")
                return super().read(min(count, 12))
        class PartialResponse(io.BytesIO):
            status = 206
            headers = {"Content-Range": "bytes 12-" +
                       str(len(payload)-1) + "/" + str(len(payload))}
        def request(url, *, headers=None, **kwargs):
            calls.append(dict(headers or {}))
            return (FailingResponse(payload) if len(calls) == 1 else
                    PartialResponse(payload[12:]))
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "song.m4a"
            fake = self.setup_drive()
            fake.token = lambda: "only-for-mock"
            with patch.object(drive, "_request", side_effect=request), \
                 patch.object(drive.time, "sleep", return_value=None):
                fake._download_verified(
                    {"id":"file-1","md5Checksum":digest}, destination, rel="audio/1/song.m4a")
            self.assertEqual(destination.read_bytes(), payload)
            self.assertEqual(len(calls), 2)
            self.assertNotIn("Range", calls[0])
            self.assertEqual(calls[1]["Range"], "bytes=12-")
            self.assertFalse(list(Path(folder).glob("*.xstagepart")))

    def test_range_ignored_restarts_instead_of_appending(self):
        payload = b"m4a-safe-to-restore" * 13
        digest = hashlib.md5(payload).hexdigest()
        class IgnoredRange(io.BytesIO):
            status = 200
            headers = {}
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "song.m4a"
            partial = Path(folder) / (
                ".song.m4a." + digest[:16] + ".xstagepart")
            partial.write_bytes(payload[:10])
            fake = self.setup_drive()
            fake.token = lambda: "mock"
            calls = []
            def request(url, *, headers=None, **kwargs):
                calls.append(dict(headers or {}))
                return IgnoredRange(payload)
            with patch.object(drive,"_request",side_effect=request):
                fake._download_verified(
                    {"id":"file-2","md5Checksum":digest}, destination)
            self.assertEqual(destination.read_bytes(),payload)
            self.assertEqual(calls[0]["Range"],"bytes=10-")
            self.assertFalse(partial.exists())

    def test_corrupt_md5_does_not_publish_song_or_keep_corrupt_part(self):
        payload = b"incorrect media bytes"
        digest = hashlib.md5(b"expected bytes").hexdigest()
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "song.m4a"
            fake = self.setup_drive()
            fake.token = lambda: "mock"
            with patch.object(drive, "_request", return_value=io.BytesIO(payload)):
                with self.assertRaisesRegex(drive.GoogleError,"MD5"):
                    fake._download_verified(
                        {"id":"file-3","md5Checksum":digest}, destination,
                        rel="audio/3/song.m4a")
            self.assertFalse(destination.exists())
            self.assertFalse(list(Path(folder).glob("*.xstagepart")))

    def test_cancel_preserves_partial_file_for_resume(self):
        payload = b"1234" * 25
        digest = hashlib.md5(payload).hexdigest()
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "song.m4a"
            event = __import__("threading").Event()
            partial = Path(folder) / (
                ".song.m4a." + digest[:16] + ".xstagepart")
            partial.write_bytes(payload[:12])
            event.set()
            fake = self.setup_drive()
            fake.token = lambda: "mock"
            with patch.object(drive, "_request", side_effect=AssertionError("must not transfer")):
                with self.assertRaisesRegex(drive.GoogleError,"ยกเลิก"):
                    fake._download_verified(
                        {"id":"file-4","md5Checksum":digest}, destination,
                        cancelled=event)
            self.assertEqual(partial.read_bytes(),payload[:12])
            self.assertFalse(destination.exists())

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
