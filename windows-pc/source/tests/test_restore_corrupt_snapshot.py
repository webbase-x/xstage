"""Rollback must not overwrite live user data with a corrupt safety database."""
import sqlite3
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
            (data / 'settings.json').write_text('{"title":"live"}', encoding='utf-8')
            (safety / 'settings.json').write_text('{"title":"old"}', encoding='utf-8')
            (data / 'songs.sqlite3').write_bytes(b'live database sentinel')
            (safety / 'songs.sqlite3').write_bytes(b'corrupt sqlite')
            with self.assertRaises(sqlite3.DatabaseError):
                restore.rollback(
                    data, safety,
                    ['settings.json', 'songs.sqlite3'],
                    ('settings.json', 'songs.sqlite3'),
                )
            self.assertEqual((data / 'settings.json').read_text(encoding='utf-8'), '{"title":"live"}')
            self.assertEqual((data / 'songs.sqlite3').read_bytes(), b'live database sentinel')


    def test_corrupt_second_database_preserves_first_live_database(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root) / 'data'
            safety = Path(root) / 'safety'
            data.mkdir()
            safety.mkdir()
            for folder, value in ((data, 'live'), (safety, 'old')):
                with sqlite3.connect(folder / 'songs.sqlite3') as db:
                    db.execute('CREATE TABLE marker (value TEXT)')
                    db.execute('INSERT INTO marker VALUES (?)', (value,))
            (data / 'play_stats.sqlite3').write_bytes(b'live stats sentinel')
            (safety / 'play_stats.sqlite3').write_bytes(b'corrupt stats sqlite')
            with self.assertRaises(sqlite3.DatabaseError):
                restore.rollback(
                    data, safety,
                    ['songs.sqlite3', 'play_stats.sqlite3'],
                    ('songs.sqlite3', 'play_stats.sqlite3'),
                )
            with sqlite3.connect(data / 'songs.sqlite3') as db:
                self.assertEqual(db.execute('SELECT value FROM marker').fetchone()[0], 'live')
            self.assertEqual(
                (data / 'play_stats.sqlite3').read_bytes(), b'live stats sentinel'
            )

if __name__ == '__main__':
    unittest.main()
