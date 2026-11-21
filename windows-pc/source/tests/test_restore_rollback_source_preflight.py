"""P0.6: a damaged later safety source must not cause partial rollback."""
import tempfile
import unittest
from pathlib import Path

from karaoke.restore import rollback


class RollbackSourcePreflightTests(unittest.TestCase):
    def test_missing_later_safety_file_leaves_earlier_live_file_untouched(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root) / "live"
            safety = Path(root) / "safety"
            data.mkdir()
            safety.mkdir()
            (data / "settings.json").write_text("current", encoding="utf-8")
            (data / "queue.json").write_text("current-queue", encoding="utf-8")
            (safety / "settings.json").write_text("old", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "queue.json"):
                rollback(data, safety, ["settings.json", "queue.json"],
                         ("settings.json", "queue.json"))
            self.assertEqual((data / "settings.json").read_text(encoding="utf-8"), "current")
            self.assertEqual((data / "queue.json").read_text(encoding="utf-8"), "current-queue")

    def test_linked_later_safety_file_does_not_mutate_live_files(self):
        with tempfile.TemporaryDirectory() as root:
            data, safety = Path(root) / "live", Path(root) / "safety"
            data.mkdir()
            safety.mkdir()
            for name in ("settings.json", "queue.json"):
                (data / name).write_text("current", encoding="utf-8")
            (safety / "settings.json").write_text("old", encoding="utf-8")
            external = Path(root) / "external.json"
            external.write_text("outside", encoding="utf-8")
            try:
                (safety / "queue.json").symlink_to(external)
            except (OSError, NotImplementedError):
                self.skipTest("Symlink creation unavailable on this host")
            with self.assertRaisesRegex(ValueError, "queue.json"):
                rollback(data, safety, ["settings.json", "queue.json"],
                         ("settings.json", "queue.json"))
            self.assertEqual((data / "settings.json").read_text(encoding="utf-8"), "current")
            self.assertEqual(external.read_text(encoding="utf-8"), "outside")


if __name__ == "__main__":
    unittest.main()
