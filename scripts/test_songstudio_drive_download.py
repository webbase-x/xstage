"""Regression tests: SONG, DB and ZIP downloads must never create Drive folders."""
from __future__ import annotations

import importlib.util
import hashlib
import json
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

    def test_upload_chunk_acks_drive_range_before_advancing(self):
        payload = b"M" * (8 * 1024 * 1024 + 1024)
        class Session:
            headers = {"Location":
                "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&upload_id=test"}
            def __enter__(self): return self
            def __exit__(self, *_): return False
        class MockDriveUpload:
            def __init__(self): self.calls=[]
            def __call__(self, session, mime_type, total, *, offset=0,
                         data=None, cancelled=None, on_progress=None):
                self.calls.append((offset, len(data) if data is not None else None))
                if len(self.calls) == 1:
                    return 308, f"bytes=0-{len(data)-1}", b""
                return 200, "", json.dumps(
                    {"id":"uploaded-123","md5Checksum":hashlib.md5(payload).hexdigest()}
                ).encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/"large.m4a"
            source.write_bytes(payload)
            fake=self.setup_drive()
            fake.token=lambda:"mock"
            uploaded=MockDriveUpload()
            with patch.object(drive.urllib.request,"urlopen",return_value=Session()), \
                 patch.object(drive.GoogleDrive,"_upload_session_request",
                              side_effect=uploaded):
                response=fake._resumable_put(source,"folder-id","large.m4a")
            self.assertEqual(response["id"],"uploaded-123")
            self.assertEqual(uploaded.calls,[(0,8*1024*1024),(8*1024*1024,1024)])

    def test_upload_interruption_asks_server_offset_before_resending(self):
        payload=b"M"*(512*1024)
        class Session:
            headers={"Location":"https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&upload_id=test"}
            def __enter__(self): return self
            def __exit__(self,*_): return False
        calls=[]
        def upload(session,mime_type,total,*,offset=0,data=None,**kwargs):
            calls.append(("probe" if data is None else "put",offset,
                          len(data) if data is not None else 0))
            if len(calls)==1:
                raise ConnectionResetError("simulated upload interrupt")
            if len(calls)==2:
                return 308,"bytes=0-262143",b""
            return 201,"",json.dumps({"id":"same-file-after-resume",
                    "md5Checksum":hashlib.md5(payload).hexdigest()}).encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/"source.m4a"
            source.write_bytes(payload)
            fake=self.setup_drive()
            fake.token=lambda:"mock"
            with patch.object(drive.urllib.request,"urlopen",return_value=Session()), \
                 patch.object(drive.GoogleDrive,"_upload_session_request",side_effect=upload), \
                 patch.object(drive.time,"sleep",return_value=None):
                answer=fake._resumable_put(source,"folder","source.m4a")
            self.assertEqual(answer["id"],"same-file-after-resume")
            self.assertEqual(calls,[("put",0,len(payload)),("probe",0,0),
                                    ("put",262144,262144)])

    def test_lost_upload_final_ack_does_not_create_second_remote_file(self):
        payload=b"unchanged M4A" * 300
        class Session:
            headers={"Location":"https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&upload_id=test"}
            def __enter__(self): return self
            def __exit__(self,*_): return False
        calls=[]
        def upload(*args,offset=0,data=None,**kwargs):
            calls.append("probe" if data is None else "put")
            if len(calls)==1:
                raise ConnectionResetError("lost final response, server committed")
            return 200,"",json.dumps({"id":"committed-once"}).encode()
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/"source.m4a"
            source.write_bytes(payload)
            fake=self.setup_drive()
            fake.token=lambda:"mock"
            with patch.object(drive.urllib.request,"urlopen",return_value=Session()), \
                 patch.object(drive.GoogleDrive,"_upload_session_request",side_effect=upload), \
                 patch.object(drive.time,"sleep",return_value=None):
                answer=fake._resumable_put(source,"folder","source.m4a")
            self.assertEqual(answer["id"],"committed-once")
            self.assertEqual(calls,["put","probe"])

    def test_upload_403_is_not_retried_or_published(self):
        class Session:
            headers={"Location":"https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&upload_id=test"}
            def __enter__(self): return self
            def __exit__(self,*_): return False
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/"source.m4a"
            source.write_bytes(b"M"*1024)
            fake=self.setup_drive()
            fake.token=lambda:"mock"
            with patch.object(drive.urllib.request,"urlopen",return_value=Session()), \
                 patch.object(drive.GoogleDrive,"_upload_session_request",
                              return_value=(403,"",b"forbidden")) as sent:
                with self.assertRaisesRegex(drive.GoogleError,"403"):
                    fake._resumable_put(source,"folder","source.m4a")
                sent.assert_called_once()

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
