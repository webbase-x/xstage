"""Guard the fresh-install V4 protocol; legacy PC Drive backup APIs cannot write."""
from __future__ import annotations

import importlib.util
import hashlib
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "xstage_google_v4", ROOT / "songstudio-pc" / "google_drive.py")
drive = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(drive)


class FakePrivateDrive(drive.GoogleDrive):
    """In-memory private Drive transport retained for V4 publisher tests."""
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


class NoWriteDrive(drive.GoogleDrive):
    def __init__(self, old_root=False):
        self.old_root = old_root
        self.calls = []

    def list_children(self, parent):
        self.calls.append(("list", parent))
        if parent == "root" and self.old_root:
            return [{"id": "unused", "name": "StageWeb",
                     "mimeType": "application/vnd.google-apps.folder"}]
        return []

    def folder(self, *args):
        raise AssertionError("Must not create legacy Drive folders")

    def upload_file(self, *args, **kwargs):
        raise AssertionError("Must not upload legacy backup files")


class StrictV4RoundTripTests(unittest.TestCase):
    def test_old_backup_uploader_is_disabled_without_io(self):
        fake = NoWriteDrive()
        with self.assertRaisesRegex(drive.GoogleError, "Layout V4"):
            fake.upload_library("any-folder", [{"audio": {"path": "audio/1.m4a"}}])
        self.assertEqual(fake.calls, [])
        self.assertFalse(hasattr(fake, "_tree_folder"))

    def test_empty_drive_does_not_invent_backup_or_create_output(self):
        fake = NoWriteDrive()
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / "restore"
            with self.assertRaisesRegex(drive.GoogleError, "XStageWeb Layout V4"):
                fake.download_library(dest, kind="songs")
            self.assertFalse(dest.exists())
        self.assertEqual(fake.calls, [("list", "root")])

    def test_unrelated_old_named_folder_is_ignored_not_read(self):
        fake = NoWriteDrive(old_root=True)
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / "restore"
            with self.assertRaisesRegex(drive.GoogleError, "XStageWeb Layout V4"):
                fake.download_library(dest, kind="db")
            self.assertFalse(dest.exists())
        self.assertEqual(fake.calls, [("list", "root")])


if __name__ == "__main__":
    unittest.main()
