"""P0.6: never unlink unsafe SQLite WAL/SHM sidecars during restore."""
import tempfile
import unittest
from pathlib import Path
from karaoke.restore import validate_sqlite_sidecars, rollback, copy_database


class SQLiteSidecarSafetyTests(unittest.TestCase):
    def test_regular_sidecars_allowed(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root)
            (data / 'songs.sqlite3-wal').write_bytes(b'')
            validate_sqlite_sidecars(data, ('songs.sqlite3',))

    def test_copy_database_rechecks_journal_before_open(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root)
            source = data / 'songs.sqlite3'
            source.write_bytes(b'not opened')
            journal = data / 'songs.sqlite3-journal'
            journal.mkdir()
            target = data / 'staged.sqlite3'
            with self.assertRaisesRegex(ValueError, 'SQLite journal'):
                copy_database(source, target)
            self.assertFalse(target.exists())
            self.assertTrue(journal.is_dir())
            self.assertEqual(source.read_bytes(), b'not opened')

    def test_copy_database_rejects_linked_source(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root)
            original = data / 'original.sqlite3'
            original.write_bytes(b'keep')
            source = data / 'songs.sqlite3'
            try:
                source.symlink_to(original)
            except (OSError, NotImplementedError):
                self.skipTest('symlinks unavailable on this Windows runner')
            target = data / 'staged.sqlite3'
            with self.assertRaisesRegex(ValueError, 'ไม่ปลอดภัย'):
                copy_database(source, target)
            self.assertFalse(target.exists())
            self.assertEqual(original.read_bytes(), b'keep')

    def test_directory_sidecar_rejected_without_removal(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root)
            sidecar = data / 'songs.sqlite3-shm'
            sidecar.mkdir()
            # Rollback now rejects an absent safety directory before inspecting
            # journals; create one to exercise the SQLite sidecar guard.
            (data / 'safety').mkdir()
            with self.assertRaisesRegex(ValueError, 'SQLite journal'):
                rollback(data, data / 'safety', [], ('songs.sqlite3',))
            self.assertTrue(sidecar.is_dir())

    def test_directory_rollback_journal_rejected_without_removal(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root)
            journal = data / 'songs.sqlite3-journal'
            journal.mkdir()
            (data / 'safety').mkdir()
            with self.assertRaisesRegex(ValueError, 'SQLite journal'):
                rollback(data, data / 'safety', [], ('songs.sqlite3',))
            self.assertTrue(journal.is_dir())

    def test_linked_rollback_journal_rejected_without_touching_target(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root)
            external = data / 'external'
            external.write_text('keep', encoding='utf-8')
            journal = data / 'songs.sqlite3-journal'
            try:
                journal.symlink_to(external)
            except (OSError, NotImplementedError):
                self.skipTest('symlinks unavailable on this Windows runner')
            with self.assertRaisesRegex(ValueError, 'SQLite journal'):
                validate_sqlite_sidecars(data, ('songs.sqlite3',))
            self.assertEqual(external.read_text(encoding='utf-8'), 'keep')
            self.assertTrue(journal.is_symlink())

    def test_symlink_sidecar_rejected_without_touching_target(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root)
            external = data / 'external'
            external.write_text('keep', encoding='utf-8')
            sidecar = data / 'songs.sqlite3-wal'
            try:
                sidecar.symlink_to(external)
            except (OSError, NotImplementedError):
                self.skipTest('symlinks unavailable on this Windows runner')
            with self.assertRaisesRegex(ValueError, 'SQLite journal'):
                validate_sqlite_sidecars(data, ('songs.sqlite3',))
            self.assertEqual(external.read_text(encoding='utf-8'), 'keep')
            self.assertTrue(sidecar.is_symlink())


if __name__ == '__main__':
    unittest.main()
