"""Rollback must not overwrite live user data with a corrupt safety database."""
import tempfile
import unittest
from pathlib import Path
from karaoke import restore


class RollbackCorruptSnapshotTests(unittest.TestCase):
    def test_corrupt_later_sqlite_snapshot_does_not_change_earlier_live_file(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root) / 'data'
            safety = Path(root) / 'safety'
            data.mkdir()
            safety.mkdir()
            (data / 'settings.json').write_text('live', encoding='utf-8')
            (safety / 'settings.json').write_text('old', encoding='utf-8')
            (data / 'songs.sqlite3').write_bytes(b'live database sentinel')
            (safety / 'songs.sqlite3').write_bytes(b'corrupt sqlite')
            with self.assertRaises(Exception):
                restore.rollback(
                    data, safety,
                    ['settings.json', 'songs.sqlite3'],
                    ('settings.json', 'songs.sqlite3'),
                )
            self.assertEqual((data / 'settings.json').read_text(encoding='utf-8'), 'live')
            self.assertEqual((data / 'songs.sqlite3').read_bytes(), b'live database sentinel')


if __name__ == '__main__':
    unittest.main()
