"""P0.6: reject linked restore roots without touching any user files."""
import tempfile
import unittest
from pathlib import Path

from karaoke.restore import stage_restore, validate_backup


class RestoreRootSafetyTests(unittest.TestCase):
    def test_linked_backup_root_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            real = base / "real"
            real.mkdir()
            link = base / "backup-link"
            try:
                link.symlink_to(real, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation not permitted")
            with self.assertRaisesRegex(ValueError, "ลิงก์"):
                validate_backup(link)
            self.assertEqual(list(real.iterdir()), [])

    def test_linked_destination_rejected_before_staging(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            real = base / "data"
            real.mkdir()
            link = base / "data-link"
            try:
                link.symlink_to(real, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation not permitted")
            with self.assertRaises(ValueError):
                stage_restore(base / "nonexistent-backup", link)
            self.assertEqual(list(real.iterdir()), [])

    def test_missing_backup_root_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, "ไม่พบโฟลเดอร์"):
                validate_backup(Path(root) / "missing")


if __name__ == "__main__":
    unittest.main()
