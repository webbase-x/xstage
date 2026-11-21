"""P0.6: unsafe restore journal links must be rejected before any mutation."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from karaoke.restore import apply_pending


class RestoreLinkedJournalTests(unittest.TestCase):
    def test_missing_journal_fails_without_mutating_pending(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root)
            pending = data / 'restore-pending'
            pending.mkdir()
            with self.assertRaisesRegex(ValueError, 'สถานะกู้คืน'):
                apply_pending(data)
            self.assertTrue(pending.is_dir())

    def test_linked_journal_fails_without_mutating_pending(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root)
            pending = data / 'restore-pending'
            pending.mkdir()
            external = data / 'external.json'
            external.write_text('{"status":"prepared"}', encoding='utf-8')
            journal = pending / 'state.json'
            try:
                journal.symlink_to(external)
            except (OSError, NotImplementedError):
                self.skipTest('symlink privilege unavailable')
            with self.assertRaisesRegex(ValueError, 'สถานะกู้คืน'):
                apply_pending(data)
            self.assertTrue(journal.is_symlink())
            self.assertEqual(external.read_text(encoding='utf-8'), '{"status":"prepared"}')

    def test_linked_data_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            real = Path(root) / 'real'
            real.mkdir()
            linked = Path(root) / 'linked'
            try:
                linked.symlink_to(real, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest('symlink privilege unavailable')
            with self.assertRaisesRegex(ValueError, 'ปลายทาง'):
                apply_pending(linked)


if __name__ == '__main__':
    unittest.main()
