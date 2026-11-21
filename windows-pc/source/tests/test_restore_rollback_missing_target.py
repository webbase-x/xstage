"""Rollback must not remove unexpected links or directories for absent files."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from karaoke.restore import rollback


class RollbackAbsentTargetTests(unittest.TestCase):
    def test_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root) / "data"
            safety = Path(root) / "safety"
            data.mkdir()
            safety.mkdir()
            target = data / "queue.json"
            target.mkdir()
            with self.assertRaisesRegex(ValueError, "ไม่ปลอดภัย"):
                rollback(data, safety, [], ("queue.json",))
            self.assertTrue(target.is_dir())

    def test_symlink_is_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root) / "data"
            safety = Path(root) / "safety"
            data.mkdir()
            safety.mkdir()
            external = Path(root) / "external"
            external.write_text("sentinel", encoding="utf-8")
            target = data / "queue.json"
            try:
                target.symlink_to(external)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            with self.assertRaisesRegex(ValueError, "ไม่ปลอดภัย"):
                rollback(data, safety, [], ("queue.json",))
            self.assertTrue(target.is_symlink())
            self.assertEqual(external.read_text(encoding="utf-8"), "sentinel")

    def test_preflight_prevents_partial_rollback(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root) / "data"
            safety = Path(root) / "safety"
            data.mkdir()
            safety.mkdir()
            (data / "settings.json").write_text("live", encoding="utf-8")
            (safety / "settings.json").write_text("old", encoding="utf-8")
            (data / "queue.json").mkdir()
            with self.assertRaises(ValueError):
                rollback(data, safety, ["settings.json"], ("settings.json", "queue.json"))
            self.assertEqual((data / "settings.json").read_text(encoding="utf-8"), "live")


if __name__ == "__main__":
    unittest.main()
