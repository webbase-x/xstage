"""Prevent predictable restore temp filenames from redirecting writes."""
import tempfile
import unittest
from pathlib import Path
from karaoke.restore import replace_file


class RestoreTempSafetyTests(unittest.TestCase):
    def test_stale_temp_symlink_does_not_receive_backup_data(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            source, target, outside = (base / name for name in ('source', 'target', 'outside'))
            source.write_bytes(b'new')
            target.write_bytes(b'old')
            outside.write_bytes(b'outside')
            stale = base / 'target.restore-tmp'
            try:
                stale.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest('symlinks unavailable on this host')
            replace_file(source, target)
            self.assertEqual(target.read_bytes(), b'new')
            self.assertEqual(outside.read_bytes(), b'outside')
            self.assertTrue(stale.is_symlink())

    def test_target_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            source, target, outside = (base / name for name in ('source', 'target', 'outside'))
            source.write_bytes(b'new')
            outside.write_bytes(b'outside')
            try:
                target.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest('symlinks unavailable on this host')
            with self.assertRaises(ValueError):
                replace_file(source, target)
            self.assertEqual(outside.read_bytes(), b'outside')

    def test_normal_replace_and_no_temp_leak(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            source, target = base / 'source', base / 'target'
            source.write_bytes(b'new')
            target.write_bytes(b'old')
            replace_file(source, target)
            self.assertEqual(target.read_bytes(), b'new')
            self.assertEqual(sorted(p.name for p in base.iterdir()), ['source', 'target'])


if __name__ == '__main__':
    unittest.main()
