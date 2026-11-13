"""Regression tests for gap-first, two-source code allocation and safe catalog remap."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, REPO / path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


codes = load_module("xstage_code_registry_test", "songstudio-pc/code_registry.py")
export = load_module("xstage_song_export_registry_test", "songstudio-pc/song_export.py")


class CodeRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "songs"
        self.root.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def song(self, code, ident, audio, *, lyric="เพลง", original=None):
        b = ident[0]
        audio_path = self.root / "audio" / b / (ident + ".m4a")
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(audio * 1100)
        lyric_path = self.root / "lyrics" / b / (ident + ".json")
        lyric_path.parent.mkdir(parents=True, exist_ok=True)
        export.atomic_json(lyric_path, export.lrc_to_json("[00:01.00]" + lyric, code))
        (lyric_path.with_suffix(".lrc")).write_text(
            "[00:01.00]" + lyric, encoding="utf-8")
        return {
            "webSongId": "audio/" + b + "/" + ident,
            "code": code, "originalCode": original or code,
            "title": lyric, "artist": "test",
            "sourceFormat": "MIDI",
            "audio": {"path": audio_path.relative_to(self.root).as_posix()},
            "lyrics": {"path": lyric_path.relative_to(self.root).as_posix()},
            "bucket": b,
        }

    def remote(self, code, sound, web_id=None):
        return {
            "webSongId": web_id or "remote-" + code,
            "code": code,
            "audio": {"md5Checksum": codes.hashlib.md5(sound * 1100).hexdigest()},
        }

    def test_drive_code_wins_and_reassignment_fills_gap_in_union(self):
        old = self.song("000100", "000100", b"B")
        remote = [self.remote("000100", b"A"), self.remote("000102", b"C")]
        allocator = codes.CodeAllocator([old], remote, self.root)
        changes = allocator.reconcile_existing()
        self.assertEqual([(x["code"], y) for x, y in changes],
                         [("000100", "000101")])
        self.assertEqual(allocator.assign_new("000101"), "000103")

    def test_matching_audio_with_same_code_preserves_local(self):
        old = self.song("001234", "001234", b"A")
        allocator = codes.CodeAllocator([old], [self.remote("001234", b"A")], self.root)
        self.assertEqual(allocator.reconcile_existing(), [])
        self.assertEqual(allocator.assign_new("001235"), "001235")

    def test_new_code_uses_hole_then_appends(self):
        old = self.song("050000", "050000", b"A")
        allocator = codes.CodeAllocator([old],
            [self.remote("050002", b"Z")], self.root)
        self.assertEqual(allocator.assign_new("050000"), "050001")
        self.assertEqual(allocator.assign_new("050000"), "050003")

    def test_existing_local_duplicate_different_audio_remapped(self):
        first = self.song("000100", "000100", b"A")
        second = self.song("000100", "000199", b"B")
        allocator = codes.CodeAllocator([first, second],
            [self.remote("000101", b"Z")], self.root)
        changes = allocator.reconcile_existing()
        self.assertEqual(len(changes), 1)
        self.assertIs(changes[0][0], second)
        self.assertEqual(changes[0][1], "000102")

    def test_existing_local_identical_audio_does_not_reassign(self):
        first = self.song("000100", "000100", b"A")
        second = self.song("000100", "000199", b"A")
        allocator = codes.CodeAllocator([first, second], [], self.root)
        self.assertEqual(allocator.reconcile_existing(), [])

    def test_renaming_catalog_preserves_original_m4a_and_lyrics(self):
        old = self.song("000100", "000100", b"B")
        remote = [self.remote("000100", b"A"), self.remote("000102", b"C")]
        original_audio = (self.root / old["audio"]["path"]).read_bytes()
        original_lyrics = (self.root / old["lyrics"]["path"]).read_bytes()
        export.publish_batch(self.root, [old])
        allocator = codes.CodeAllocator(export.existing_records(self.root), remote, self.root)
        changes = allocator.reconcile_existing()
        self.assertEqual(codes.apply_changes(self.root, changes, export), 1)
        pointer, _ = export._read_current(self.root)
        self.assertEqual(pointer["songCount"], 1)
        record = export.existing_records(self.root)[0]
        self.assertEqual(record["code"], "000101")
        self.assertEqual(record["originalCode"], "000100")
        self.assertEqual(record["sourceFormat"], "MIDI")
        self.assertTrue(export.record_is_complete(self.root, record))
        self.assertEqual((self.root / old["audio"]["path"]).read_bytes(), original_audio)
        self.assertEqual((self.root / old["lyrics"]["path"]).read_bytes(), original_lyrics)
        fresh = json.loads((self.root / record["lyrics"]["path"]).read_text(encoding="utf-8"))
        self.assertEqual(fresh["songCode"], "000101")
        self.assertEqual(len(list((self.root / "audio").rglob("*.m4a"))), 1)
        self.assertEqual(codes.apply_changes(self.root, [], export), 0)
        self.assertEqual(len(export.existing_records(self.root)), 1)

    def test_two_remote_songs_one_same_local_audio_keep_matching_code(self):
        old = self.song("000101", "000101", b"A")
        remote = [self.remote("000101", b"A"), self.remote("000102", b"B")]
        allocator = codes.CodeAllocator([old], remote, self.root)
        self.assertFalse(allocator.reconcile_existing())

    def test_alphanumeric_conflict_uses_numeric_namespace(self):
        old = self.song("ABC123", "000100", b"A")
        allocator = codes.CodeAllocator([old], [self.remote("ABC123", b"Z")], self.root)
        self.assertEqual(allocator.reconcile_existing()[0][1], "000001")


if __name__ == "__main__":
    unittest.main()
