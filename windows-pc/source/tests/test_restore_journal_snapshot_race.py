"""P0.6: a journal appearing during snapshot must never be removed."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from karaoke import restore


class JournalRaceTests(unittest.TestCase):
    def test_snapshot_rejects_redirected_destination(self):
        import sqlite3
        from contextlib import closing
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            source = base / "source.sqlite3"
            with closing(sqlite3.connect(source)) as db:
                db.execute("CREATE TABLE marker (id INTEGER)")
                db.commit()
            external = base / "external.sqlite3"
            external.write_bytes(b"preserve")
            destination = base / "snapshot.sqlite3"
            try:
                destination.symlink_to(external)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            with self.assertRaisesRegex(ValueError, "SQLite"):
                restore.copy_database(source, destination)
            self.assertEqual(external.read_bytes(), b"preserve")
            self.assertTrue(destination.is_symlink())

    def test_snapshot_rejects_directory_destination(self):
        import sqlite3
        from contextlib import closing
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            source = base / "source.sqlite3"
            with closing(sqlite3.connect(source)) as db:
                db.execute("CREATE TABLE marker (id INTEGER)")
                db.commit()
            destination = base / "snapshot.sqlite3"
            destination.mkdir()
            with self.assertRaisesRegex(ValueError, "SQLite"):
                restore.copy_database(source, destination)
            self.assertTrue(destination.is_dir())

    def test_new_directory_sidecar_is_not_deleted_during_apply(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root)
            pending = data / "restore-pending"
            pending.mkdir()
            (pending / "state.json").write_text('{"status":"prepared"}', encoding="utf-8")
            (data / "songs.sqlite3").write_bytes(b"original")
            sidecar = data / "songs.sqlite3-wal"
            original_copy = restore.copy_database

            def snapshot_with_race(source, target):
                # Inject the unsafe journal after initial preflight, while
                # creating the safety snapshot, before live replacement.
                Path(target).write_bytes(b"snapshot")
                sidecar.mkdir()

            with patch.object(restore, "validate_backup", return_value={
                "songs": 0, "queue": [], "settings": {}
            }), patch.object(restore, "copy_database", side_effect=snapshot_with_race), \
                    patch.object(restore, "replace_file") as replace:
                with self.assertRaisesRegex(ValueError, "journal"):
                    restore.apply_pending(data)
                replace.assert_not_called()
            self.assertTrue(sidecar.is_dir())
            self.assertEqual((data / "songs.sqlite3").read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
