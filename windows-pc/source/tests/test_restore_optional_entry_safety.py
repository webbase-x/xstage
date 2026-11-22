"""P0.6: malformed optional backup entries must fail before any restore staging."""
import tempfile
import unittest
from pathlib import Path

from karaoke.restore import validate_backup


class OptionalBackupEntrySafetyTests(unittest.TestCase):
    def test_optional_directories_are_rejected_before_database_open(self):
        for name in ("history.json", "play_stats.sqlite3"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as root:
                backup = Path(root)
                (backup / name).mkdir()
                with self.assertRaisesRegex(ValueError, name):
                    validate_backup(backup)

    def test_absent_optional_entries_preserve_required_file_validation(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, "songs.sqlite3"):
                validate_backup(root)


if __name__ == "__main__":
    unittest.main()
