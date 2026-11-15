"""Regression tests for created Lyrics JSON normalization and filename-code options."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "songstudio-pc"


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


manager = load("created_json_manager")
registry = load("code_registry")


class FakeExport:
    def __init__(self, record):
        self.record = record

    def existing_records(self, root):
        return [self.record]

    def safe_media_path(self, root, value, directory):
        path = (root / value).resolve()
        if not path.is_relative_to(root.resolve()) or not value.startswith(directory + "/"):
            raise ValueError("path traversal")
        return path


class CreatedJsonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "lyrics" / "0").mkdir(parents=True)
        self.path = self.root / "lyrics" / "0" / "00001.json"
        self.record = {"code": "00001", "title": "เพลงทดสอบ", "artist": "ทดสอบ",
                       "lyrics": {"path": "lyrics/0/00001.json"}}
        self.export = FakeExport(self.record)
        self.document = {"rawLrc": "[00:01.00]ทดสอบ",
                         "lines": [{"text": "ทดสอบ", "endTime": 2.0, "startTime": 1.0}],
                         "songCode": "00001", "audioOffsetMs": 0, "schemaVersion": 1}
        self.path.write_text(json.dumps(self.document, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_dry_run_and_restore_do_not_change_lyrics(self):
        before = self.path.read_bytes()
        key = self.record["lyrics"]["path"]
        preview = manager.format_created(self.root, self.export, [key])
        self.assertEqual(preview["formatted"], 1)
        self.assertEqual(self.path.read_bytes(), before)
        result = manager.format_created(self.root, self.export, [key], dry_run=False)
        self.assertEqual(result["formatted"], 1)
        self.assertEqual(json.loads(self.path.read_text()), self.document)
        backup = result["results"][0]
        self.assertTrue((self.path.parent / backup["backup"]).is_file())
        restored = manager.restore_created(self.root, self.export, key, backup["backup"], backup["sha256"])
        self.assertTrue(restored["ok"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_mismatched_song_code_is_skipped(self):
        self.document["songCode"] = "wrong"
        self.path.write_text(json.dumps(self.document), encoding="utf-8")
        result = manager.format_created(self.root, self.export,
                                        [self.record["lyrics"]["path"]], dry_run=False)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(list(self.path.parent.glob("*.bak")), [])

    def test_no_time_guessing_for_bad_lines(self):
        self.document["lines"][0]["endTime"] = .1
        self.path.write_text(json.dumps(self.document), encoding="utf-8")
        result = manager.format_created(self.root, self.export,
                                        [self.record["lyrics"]["path"]], dry_run=False)
        self.assertEqual(result["skipped"], 1)


class CodeStyleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_numeric_padded_and_no_collisions(self):
        allocator = registry.CodeAllocator([{"code": "00001"}], [], self.root,
                                          code_style="numeric", code_length=5)
        self.assertEqual(allocator.assign_new("Track 1"), "00002")
        self.assertEqual(allocator.assign_new("Track 2"), "00003")

    def test_letters_and_alphanumeric_lengths(self):
        alpha = registry.CodeAllocator([], [], self.root, code_style="letters", code_length=4)
        self.assertEqual(alpha.assign_new("song"), "AAAB")
        mixed = registry.CodeAllocator([], [], self.root, code_style="alphanumeric", code_length=4)
        self.assertEqual(mixed.assign_new("song"), "0001")

    def test_existing_source_codes_unchanged_by_default(self):
        allocator = registry.CodeAllocator([], [], self.root)
        self.assertEqual(allocator.assign_new("MYSOUND"), "MYSOUND")


if __name__ == "__main__":
    unittest.main()
