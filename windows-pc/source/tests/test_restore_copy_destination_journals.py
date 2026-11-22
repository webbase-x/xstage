"""Reject hostile destination SQLite journals before copying a backup."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from karaoke.restore import copy_database


class CopyDatabaseDestinationJournalTests(unittest.TestCase):
    def test_directory_journal_is_rejected_without_modifying_destination(self):
        for suffix in ('-wal', '-shm', '-journal'):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as root:
                root = Path(root)
                source = root / 'source.sqlite3'
                with closing(sqlite3.connect(source)) as db:
                    db.execute('CREATE TABLE songs (id INTEGER)')
                    db.commit()
                destination = root / 'destination.sqlite3'
                destination.write_bytes(b'existing destination sentinel')
                journal = root / ('destination.sqlite3' + suffix)
                journal.mkdir()
                with self.assertRaisesRegex(ValueError, 'SQLite journal'):
                    copy_database(source, destination)
                self.assertEqual(destination.read_bytes(), b'existing destination sentinel')
                self.assertTrue(journal.is_dir())

    def test_symlink_journal_does_not_modify_external_target(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / 'source.sqlite3'
            with closing(sqlite3.connect(source)) as db:
                db.execute('CREATE TABLE songs (id INTEGER)')
                db.commit()
            external = root / 'outside'
            external.write_bytes(b'keep')
            journal = root / 'destination.sqlite3-journal'
            try:
                journal.symlink_to(external)
            except (OSError, NotImplementedError):
                self.skipTest('symlinks unavailable on this Windows runner')
            with self.assertRaisesRegex(ValueError, 'SQLite journal'):
                copy_database(source, root / 'destination.sqlite3')
            self.assertEqual(external.read_bytes(), b'keep')
            self.assertTrue(journal.is_symlink())


if __name__ == '__main__':
    unittest.main()
