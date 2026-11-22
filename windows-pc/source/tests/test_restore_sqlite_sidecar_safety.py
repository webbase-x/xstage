"""P0.6: never unlink unsafe SQLite WAL/SHM sidecars during restore."""
import tempfile
import unittest
from pathlib import Path
from karaoke.restore import validate_sqlite_sidecars, rollback


class SQLiteSidecarSafetyTests(unittest.TestCase):
    def test_regular_sidecars_allowed(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root)
            (data / 'songs.sqlite3-wal').write_bytes(b'')
            validate_sqlite_sidecars(data, ('songs.sqlite3',))

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
