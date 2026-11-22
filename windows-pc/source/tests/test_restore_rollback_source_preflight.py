"""P0.6: a damaged later safety source must not cause partial rollback."""
import tempfile
import unittest
from pathlib import Path

from karaoke.restore import rollback


class RollbackSourcePreflightTests(unittest.TestCase):
    def test_linked_safety_directory_never_changes_live_file(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            data, real_safety = base / "live", base / "real-safety"
            data.mkdir()
            real_safety.mkdir()
            (data / "settings.json").write_text('{"title":"live"}', encoding="utf-8")
            (real_safety / "settings.json").write_text('{"title":"old"}', encoding="utf-8")
            linked_safety = base / "safety-link"
            try:
                linked_safety.symlink_to(real_safety, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Directory symlinks unavailable on this host")
            with self.assertRaisesRegex(ValueError, "safety"):
                rollback(data, linked_safety, ["settings.json"], ("settings.json",))
            self.assertEqual((data / "settings.json").read_text(encoding="utf-8"),
                             '{"title":"live"}')

    def test_linked_live_directory_never_changes_external_file(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            real_data, safety = base / "real-live", base / "safety"
            real_data.mkdir()
            safety.mkdir()
            (real_data / "settings.json").write_text('{"title":"live"}', encoding="utf-8")
            (safety / "settings.json").write_text('{"title":"old"}', encoding="utf-8")
            linked_data = base / "live-link"
            try:
                linked_data.symlink_to(real_data, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Directory symlinks unavailable on this host")
            with self.assertRaisesRegex(ValueError, "data"):
                rollback(linked_data, safety, ["settings.json"], ("settings.json",))
            self.assertEqual((real_data / "settings.json").read_text(encoding="utf-8"),
                             '{"title":"live"}')

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

    def test_corrupt_later_json_snapshot_does_not_mutate_earlier_live_file(self):
        with tempfile.TemporaryDirectory() as root:
            data, safety = Path(root) / "live", Path(root) / "safety"
            data.mkdir()
            safety.mkdir()
            (data / "settings.json").write_text('{"title":"current"}', encoding="utf-8")
            (data / "queue.json").write_text('[]', encoding="utf-8")
            (safety / "settings.json").write_text('{"title":"old"}', encoding="utf-8")
            (safety / "queue.json").write_text('{"broken":', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "queue.json"):
                rollback(data, safety, ["settings.json", "queue.json"],
                         ("settings.json", "queue.json"))
            self.assertEqual((data / "settings.json").read_text(encoding="utf-8"),
                             '{"title":"current"}')
            self.assertEqual((data / "queue.json").read_text(encoding="utf-8"), '[]')

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
