"""Safe exact-media duplicate scan and action regression suite."""
from __future__ import annotations

import importlib.util
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "song_duplicates", ROOT / "songstudio-pc" / "song_duplicate.py")
duplicates = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(duplicates)


class DuplicateMediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "input"
        self.root.mkdir()
        self.output = Path(self.tmp.name) / "quarantine"
        self.output.mkdir()
        self.registry = duplicates.DuplicateMediaRegistry()

    def put(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def found(self):
        return self.registry.scan(str(self.root))

    def test_exact_bytes_only_across_names_and_formats(self):
        binary = b"same exact binary bytes" * 120
        self.put("a/song-one.mp3", binary)
        self.put("b/completely-different-name.flac", binary)
        self.put("c/same-length.mp3", b"x" * len(binary))
        self.put("d/song.lyr", binary)
        self.put("d/song.json", binary)
        self.put("d/song.lrc", binary)
        self.put("d/font.sf2", binary)
        report = self.found()
        self.assertEqual(report["fileCount"], 3)
        self.assertEqual(report["groupCount"], 1, msg=repr(report))
        self.assertEqual(report["duplicateFiles"], 1)
        page = self.registry.page()
        self.assertTrue(page["ready"])
        self.assertEqual(len(page["groups"][0]["files"]), 2)
        self.assertTrue(page["groups"][0]["files"][0]["keep"])
        self.assertFalse(page["groups"][0]["files"][1]["keep"])

    def test_same_beginning_end_different_middle_is_not_duplicate(self):
        prefix, suffix = b"P" * 65536, b"E" * 65536
        self.put("a.mid", prefix + b"A" * 4096 + suffix)
        self.put("b.mid", prefix + b"B" * 4096 + suffix)
        report = self.found()
        self.assertEqual(report["groupCount"], 0)

    def test_move_one_copy_only_and_keep_original(self):
        content = b"test" * 1000
        self.put("A/00001.mid", content)
        self.put("B/00002.kar", content)
        report = self.found()
        group = self.registry.page()["groups"][0]
        keeper, copy = group["files"]
        outcome = self.registry.apply(
            scan_id=report["scanId"], selected=[copy["id"]],
            operation="move", confirmed=True, destination=str(self.output))
        self.assertEqual(outcome["processed"], 1)
        self.assertTrue(Path(keeper["path"]).is_file())
        self.assertFalse(Path(copy["path"]).exists())
        self.assertTrue(list(self.output.rglob("*.kar")) or
                        list(self.output.rglob("*.mid")))
        self.assertEqual(self.registry.page()["groupCount"], 0)

    def test_cannot_move_keeper_or_all_copies(self):
        payload = b"same" * 100
        self.put("A/1.mp3", payload)
        self.put("B/2.mp3", payload)
        report = self.found()
        ids = [x["id"] for x in self.registry.page()["groups"][0]["files"]]
        for selected in ([ids[0]], ids):
            with self.assertRaisesRegex(ValueError, "เก็บไฟล์หลัก"):
                self.registry.apply(
                    scan_id=report["scanId"], selected=selected,
                    operation="move", confirmed=True,
                    destination=str(self.output))

    def test_stale_file_and_scan_id_fail_without_mutation(self):
        payload = b"binary" * 150
        self.put("A/1.mp3", payload)
        self.put("B/2.mp3", payload)
        report = self.found()
        group = self.registry.page()["groups"][0]
        copy = Path(group["files"][1]["path"])
        file_id = group["files"][1]["id"]
        with self.assertRaisesRegex(ValueError, "หมดอายุ"):
            self.registry.apply(
                scan_id="old", selected=[file_id], operation="move",
                confirmed=True, destination=str(self.output))
        copy.write_bytes(b"new" * 200)
        with self.assertRaisesRegex(ValueError, "เปลี่ยน"):
            self.registry.apply(
                scan_id=report["scanId"], selected=[file_id],
                operation="move", confirmed=True, destination=str(self.output))
        self.assertTrue(copy.is_file())

    def test_no_move_to_same_or_nested_scan_folder(self):
        payload = b"same-data" * 100
        self.put("A/1.mp3", payload)
        self.put("B/2.mp3", payload)
        report = self.found()
        copy = self.registry.page()["groups"][0]["files"][1]
        with self.assertRaisesRegex(ValueError, "แยกจาก"):
            self.registry.apply(
                scan_id=report["scanId"], selected=[copy["id"]],
                operation="move", confirmed=True, destination=str(self.root))
        self.assertTrue(Path(copy["path"]).exists())

    def test_live_xstagesong_files_are_protected(self):
        binary = b"original" * 100
        self.put("XStageSong/AUDIO/SONG/1.mp3", binary)
        self.put("XStageSong/AUDIO/SONG/2.mp3", binary)
        report = self.found()
        dup = self.registry.page()["groups"][0]["files"][1]
        self.assertTrue(dup["protected"])
        with self.assertRaisesRegex(ValueError, "XStageSong"):
            self.registry.apply(
                scan_id=report["scanId"], selected=[dup["id"]],
                operation="move", confirmed=True, destination=str(self.output))

    def test_explicit_confirmation_and_cancel(self):
        binary = b"sound" * 100
        self.put("1.mp3", binary)
        self.put("2.mp3", binary)
        report = self.found()
        fid = self.registry.page()["groups"][0]["files"][1]["id"]
        with self.assertRaisesRegex(ValueError, "ยืนยัน"):
            self.registry.apply(scan_id=report["scanId"], selected=[fid],
                                operation="move", destination=str(self.output))
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaisesRegex(RuntimeError, "ยกเลิก"):
            self.registry.apply(scan_id=report["scanId"], selected=[fid],
                                operation="move", destination=str(self.output),
                                confirmed=True, cancelled=cancelled)

    def test_scan_cancel_keeps_previous_report(self):
        self.put("a.mp3", b"song" * 40)
        self.put("b.mp3", b"song" * 40)
        report = self.found()
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(RuntimeError):
            self.registry.scan(str(self.root), cancelled=cancelled)
        self.assertEqual(self.registry.page()["scanId"], report["scanId"])

    @unittest.skipUnless(os.name == "nt", "Windows Recycle Bin only")
    def test_recycle_action_only_on_verified_selected_duplicate(self):
        self.put("a.mp3", b"same" * 100)
        self.put("b.mp3", b"same" * 100)
        report = self.found()
        group = self.registry.page()["groups"][0]
        copy = group["files"][1]
        # Never affect the runner's actual Recycle Bin.
        with patch.object(duplicates, "_recycle_windows",
                          side_effect=lambda path: path.unlink()) as recycle:
            result = self.registry.apply(
                scan_id=report["scanId"], selected=[copy["id"]],
                operation="recycle", confirmed=True)
        self.assertEqual(result["processed"], 1)
        recycle.assert_called_once()
        self.assertTrue(Path(group["files"][0]["path"]).exists())
        self.assertFalse(Path(copy["path"]).exists())


if __name__ == "__main__":
    unittest.main()
