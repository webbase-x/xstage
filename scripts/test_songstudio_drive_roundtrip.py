"""Offline Google Drive upload/download round-trip contract tests.

Uses an in-memory private Drive provider. Does not claim live Google auth or
network access; verifies the complete app-side file/tree/dedup/checksum flow.
"""
from __future__ import annotations

import hashlib
import io
import importlib.util
import json
import tempfile
import unittest
import urllib.parse
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "songstudio_drive_roundtrip", ROOT / "songstudio-pc" / "google_drive.py")
drive = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(drive)


class FakePrivateDrive(drive.GoogleDrive):
    def __init__(self):
        self.items = {}
        self.upload_order = []
        self.nextid = 0
        self.locked = False

    def _newid(self):
        self.nextid += 1
        return "f" + str(self.nextid)

    def list_children(self, parent):
        return [dict(record["metadata"]) for record in self.items.values()
                if record["parent"] == parent]

    def folder(self, parent, name):
        for record in self.items.values():
            m = record["metadata"]
            if record["parent"] == parent and m["name"] == name and (
                    m["mimeType"] == "application/vnd.google-apps.folder"):
                return m["id"]
        ident = self._newid()
        self.items[ident] = {
            "parent": parent, "body": b"",
            "metadata": {"id": ident, "name": name,
                         "mimeType": "application/vnd.google-apps.folder"}}
        return ident

    def _resumable_put(self, path, parent, filename, replacing=None,
                       cancelled=None, on_progress=None):
        """Mock only remote transport; real upload_file performs SHA/MD5 logic."""
        if self.locked:
            raise AssertionError("Download attempted a Drive write")
        self.upload_order.append(filename)
        body = Path(path).read_bytes()
        md5 = hashlib.md5(body).hexdigest()
        if replacing:
            record = self.items[replacing]
            record["body"] = body
            record["metadata"]["md5Checksum"] = md5
            return dict(record["metadata"])
        ident = self._newid()
        meta = {"id": ident, "name": filename,
                "mimeType": "application/octet-stream",
                "md5Checksum": md5, "size": str(len(body))}
        self.items[ident] = {"parent": parent, "body": body, "metadata": meta}
        if on_progress:
            on_progress(len(body), len(body))
        return dict(meta)

    def token(self):
        return "test-only-token"


class DriveRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.songs = self.root / "songs"
        for directory in ("audio/0", "lyrics/0", "catalogs"):
            (self.songs / directory).mkdir(parents=True)
        (self.songs / "audio/0/a.m4a").write_bytes(b"A" * 5200)
        (self.songs / "lyrics/0/a.json").write_text(
            '{"lines":[{"text":"ทดสอบ","startTime":1.0}]}', encoding="utf-8")
        (self.songs / "lyrics/0/a.lrc").write_text(
            "[00:01.00]ทดสอบ", encoding="utf-8")
        (self.songs / "catalogs/0.json").write_text('{"songs":[]}', encoding="utf-8")
        (self.songs / "current.json").write_text('{"songCount":1}', encoding="utf-8")
        self.records = [{"audio":{"path":"audio/0/a.m4a"},
                         "lyrics":{"path":"lyrics/0/a.json"}}]
        self.g = FakePrivateDrive()

    def tearDown(self):
        self.tmp.cleanup()

    def _fake_request(self, url, **kwargs):
        route = urllib.parse.urlsplit(url).path
        ident = route.rsplit("/", 1)[-1]
        return io.BytesIO(self.g.items[ident]["body"])

    def test_upload_dedup_pointer_last_and_download_all_formats(self):
        first = self.g.upload_library(self.songs, self.records)
        self.assertEqual(first, {"created":5,"skipped":0,"updated":0})
        self.assertEqual(self.g.upload_order[-1], "current.json")
        self.assertIn("lyrics/0/a.lrc", [
            "lyrics/0/a.lrc" for item in self.g.items.values()
            if item["metadata"]["name"] == "a.lrc"])
        second = self.g.upload_library(self.songs, self.records)
        self.assertEqual(second, {"created":0,"skipped":5,"updated":0})
        self.g.locked = True
        with patch.object(drive, "_request", side_effect=self._fake_request):
            result = self.g.download_library(self.root / "restore", kind="songs")
            self.assertEqual(result["files"], 5)
            restored = Path(result["path"])
            self.assertEqual((restored / "audio/0/a.m4a").read_bytes(),
                             (self.songs / "audio/0/a.m4a").read_bytes())
            self.assertEqual((restored / "lyrics/0/a.lrc").read_bytes(),
                             (self.songs / "lyrics/0/a.lrc").read_bytes())
            db = self.g.download_library(self.root / "database", kind="db")
            self.assertEqual(db["files"], 2)
            self.assertTrue((Path(db["path"]) / "catalogs/0.json").is_file())
            self.assertFalse((Path(db["path"]) / "audio/0/a.m4a").exists())
            archived = self.g.download_library(self.root / "zip-out", kind="zip")
            with zipfile.ZipFile(archived["path"]) as archive:
                self.assertIn("songs/current.json", archive.namelist())
                self.assertIn("songs/audio/0/a.m4a", archive.namelist())

    def test_upload_collision_and_local_restore_conflict_fail_closed(self):
        self.g.upload_library(self.songs, self.records)
        original = (self.songs / "audio/0/a.m4a")
        original.write_bytes(b"new-content" * 600)
        with self.assertRaisesRegex(drive.GoogleError, "เนื้อหาต่างกัน"):
            self.g.upload_library(self.songs, self.records)
        self.g.locked = True
        target = self.root / "already-exists"
        dest = target / "X-Stage Song Studio" / "songs" / "audio/0/a.m4a"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"do-not-overwrite")
        with patch.object(drive, "_request", side_effect=self._fake_request):
            with self.assertRaisesRegex(drive.GoogleError, "ต่างเนื้อหา"):
                self.g.download_library(target, kind="songs")
        self.assertEqual(dest.read_bytes(), b"do-not-overwrite")

    def test_partial_drive_library_without_pointer_is_rejected(self):
        self.g.upload_library(self.songs, self.records)
        for ident, item in list(self.g.items.items()):
            if item["metadata"]["name"] == "current.json":
                self.g.items.pop(ident)
        self.g.locked = True
        with patch.object(drive, "_request", side_effect=self._fake_request):
            with self.assertRaisesRegex(drive.GoogleError, "current.json"):
                self.g.download_library(self.root / "partial", kind="songs")
        self.assertFalse((self.root / "partial").exists())

    def test_missing_remote_md5_cannot_publish_unverified_restore(self):
        self.g.upload_library(self.songs, self.records)
        for item in self.g.items.values():
            if item["metadata"]["name"] == "a.m4a":
                item["metadata"].pop("md5Checksum", None)
        self.g.locked = True
        with patch.object(drive, "_request", side_effect=self._fake_request):
            with self.assertRaisesRegex(drive.GoogleError, "MD5"):
                self.g.download_library(self.root / "unverified", kind="songs")

    def test_corrupt_remote_download_rejected_by_md5(self):
        self.g.upload_library(self.songs, self.records)
        for item in self.g.items.values():
            if item["metadata"]["name"] == "a.m4a":
                item["body"] = b"tampered"
        self.g.locked = True
        with patch.object(drive, "_request", side_effect=self._fake_request):
            with self.assertRaisesRegex(drive.GoogleError, "MD5"):
                self.g.download_library(self.root / "restore", kind="songs")


if __name__ == "__main__":
    unittest.main()
