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
        self.root = (Path(self.tmp.name) / "input").resolve()
        self.root.mkdir()
        self.output = (Path(self.tmp.name) / "quarantine").resolve()
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

    def test_move_ncn_media_and_mirrored_lyr_cur_as_one_bundle(self):
        original = self.put("MIDI/NCN/SONG/A/00001.mid", b"midi" * 500)
        self.put("MIDI/NCN/LYR/A/00001.lyr", b"lyrics 00001")
        self.put("MIDI/NCN/CUR/A/00001.cur", b"cursor 00001")
        moved = self.put("MIDI/NCN/SONG/B/00002.mid", original.read_bytes())
        lyric = self.put("MIDI/NCN/LYR/B/00002.lyr", b"lyrics 00002")
        cursor = self.put("MIDI/NCN/CUR/B/00002.cur", b"cursor 00002")
        report = self.found()
        group = self.registry.page()["groups"][0]
        other = next(file for file in group["files"] if file["path"] == str(moved))
        plan = self.registry.plan(scan_id=report["scanId"],
                                  selected=[other["id"]],
                                  operation="move", destination=str(self.output))
        self.assertEqual(plan["mediaCount"], 1)
        self.assertEqual(plan["companionCount"], 2)
        self.assertEqual(plan["totalFiles"], 3)
        self.registry.apply(scan_id=report["scanId"], selected=[other["id"]],
                            operation="move", destination=str(self.output),
                            preview_id=plan["previewId"], confirmed=True)
        for path in (moved, lyric, cursor):
            self.assertFalse(path.exists())
            self.assertTrue((self.output / path.relative_to(self.root)).exists())
        self.assertTrue(original.exists())
        self.assertTrue((self.root / "MIDI/NCN/LYR/A/00001.lyr").exists())

    def test_keep_a_different_file_instead_of_default_original(self):
        first = self.put("A/1.mp3", b"same" * 200)
        second = self.put("B/2.m4a", first.read_bytes())
        report = self.found()
        group = self.registry.page()["groups"][0]
        first_id = next(x["id"] for x in group["files"] if x["path"] == str(first))
        second_id = next(x["id"] for x in group["files"] if x["path"] == str(second))
        keepers = {group["id"]: second_id}
        plan = self.registry.plan(scan_id=report["scanId"],
                                  selected=[first_id], keeper_by_group=keepers,
                                  operation="move", destination=str(self.output))
        result = self.registry.apply(scan_id=report["scanId"], selected=[first_id],
                                     keeper_by_group=keepers, operation="move",
                                     destination=str(self.output),
                                     preview_id=plan["previewId"], confirmed=True)
        self.assertEqual(result["processed"], 1)
        self.assertFalse(first.exists())
        self.assertTrue(second.exists())
        self.assertTrue((self.output / "A/1.mp3").exists())

    def test_format_preference_keeps_requested_type(self):
        one = self.put("A/01.mid", b"binary" * 100)
        self.put("B/02.xsk", one.read_bytes())
        report = self.found()
        group = self.registry.page(preferred_extension=".xsk")["groups"][0]
        keeper = next(x for x in group["files"] if x["keep"])
        self.assertEqual(keeper["extension"], ".xsk")
        self.assertEqual(keeper["path"], str(self.root / "B/02.xsk"))
        selected = next(x["id"] for x in group["files"] if not x["keep"])
        plan = self.registry.plan(scan_id=report["scanId"], selected=[selected],
                                  preferred_extension=".xsk", operation="move",
                                  destination=str(self.output))
        self.assertIn(".xsk", plan["keepers"][0]["type"])

    def test_same_code_different_encoding_needs_manual_ack(self):
        one = self.put("Album/00001.mp3", b"music A" * 200)
        two = self.put("Album/00001.m4a", b"music B" * 150)
        self.put("Album/00001.json", b'{"lines":[]}')
        report = self.registry.scan(str(self.root), mode="code")
        self.assertEqual(report["groupCount"], 1)
        group = self.registry.page(preferred_extension=".m4a")["groups"][0]
        self.assertEqual(group["match"], "code")
        self.assertEqual(next(x for x in group["files"] if x["keep"])["extension"], ".m4a")
        first = next(x for x in group["files"] if x["extension"] == ".mp3")
        with self.assertRaisesRegex(ValueError, "ยืนยัน"):
            self.registry.plan(scan_id=report["scanId"], selected=[first["id"]],
                               operation="move", destination=str(self.output),
                               preferred_extension=".m4a")
        plan = self.registry.plan(scan_id=report["scanId"], selected=[first["id"]],
                                  operation="move", destination=str(self.output),
                                  preferred_extension=".m4a",
                                  same_song_confirmed=True)
        self.assertEqual(plan["companionCount"], 0) # JSON shared with M4A keeper
        self.assertTrue(plan["warnings"])
        result = self.registry.apply(scan_id=report["scanId"], selected=[first["id"]],
                                     operation="move", destination=str(self.output),
                                     preferred_extension=".m4a", same_song_confirmed=True,
                                     preview_id=plan["previewId"], confirmed=True)
        self.assertEqual(result["processed"], 1)
        self.assertFalse(one.exists())
        self.assertTrue(two.exists())
        self.assertTrue((self.root / "Album/00001.json").exists())

    def test_same_code_parallel_song_roles_match_but_artist_namespaces_do_not(self):
        self.put("MIDI/NCN/SONG/0/00550.mid", b"midi note" * 50)
        self.put("AUDIO/MP3/SONG/0/00550.mp3", b"audio track" * 50)
        self.put("ArtistOne/MIDI/SONG/1/00330.mid", b"one" * 80)
        self.put("ArtistTwo/AUDIO/SONG/1/00330.mp3", b"two" * 80)
        report = self.registry.scan(str(self.root), mode="code")
        self.assertEqual(report["groupCount"], 1)
        paths = {Path(x["path"]).suffix.lower()
                 for x in self.registry.page()["groups"][0]["files"]}
        self.assertEqual(paths, {".mid", ".mp3"})

    def test_same_code_unrelated_folders_not_grouped(self):
        self.put("ArtistOne/00001.mp3", b"A" * 500)
        self.put("ArtistTwo/00001.m4a", b"B" * 500)
        report = self.registry.scan(str(self.root), mode="code")
        self.assertEqual(report["groupCount"], 0)

    def test_preview_token_and_dest_are_immutable(self):
        self.put("A/1.mid", b"same" * 100)
        self.put("B/2.mid", b"same" * 100)
        report = self.found()
        selected = self.registry.page()["groups"][0]["files"][1]["id"]
        plan = self.registry.plan(scan_id=report["scanId"], selected=[selected],
                                  operation="move", destination=str(self.output))
        with self.assertRaisesRegex(ValueError, "แผน"):
            self.registry.apply(scan_id=report["scanId"], selected=[selected],
                                operation="move", destination=str(self.output),
                                preview_id="wrong", confirmed=True)
        self.assertIsNotNone(plan["previewId"])
        self.assertTrue((self.root / "B/2.mid").exists())

    @unittest.skipUnless(os.name == "nt", "Windows Recycle Bin only")
    def test_recycle_media_and_json_with_confirmation(self):
        self.put("A/00001.mp3", b"same" * 150)
        song = self.put("B/00002.mp3", b"same" * 150)
        lyric = self.put("B/00002.json", b'{"schemaVersion":1}')
        report = self.found()
        group = self.registry.page()["groups"][0]
        fid = next(x["id"] for x in group["files"] if x["path"] == str(song))
        plan = self.registry.plan(scan_id=report["scanId"], selected=[fid],
                                  operation="recycle")
        self.assertEqual(plan["companionCount"], 1)
        with patch.object(duplicates, "_recycle_windows",
                          side_effect=lambda path: path.unlink()) as recycle:
            self.registry.apply(scan_id=report["scanId"], selected=[fid],
                                operation="recycle", preview_id=plan["previewId"],
                                confirmed=True)
        self.assertEqual(recycle.call_count, 2)
        self.assertFalse(song.exists())
        self.assertFalse(lyric.exists())
        self.assertTrue((self.root / "A/00001.mp3").exists())

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
