from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import plus_core as core


class SQLiteUiResponsivenessTests(unittest.TestCase):
    def test_read_connection_does_not_wait_for_active_import_writer(self):
        with tempfile.TemporaryDirectory() as base:
            workspace=Path(base)/"workspace"
            core.init(workspace)
            path=core.db_path(workspace)
            with core.connect(workspace) as check:
                self.assertEqual(check.execute("PRAGMA journal_mode").fetchone()[0].lower(),"wal")

            # Simulate the importer holding an active write transaction.
            with core.connect(workspace) as writer:
                writer.execute("BEGIN IMMEDIATE")
                writer.execute(
                    "INSERT OR REPLACE INTO xstage_migrations(key,applied_at) VALUES (?,?)",
                    ("ui-responsiveness-test",core.now()))
                started=time.monotonic()
                with core.connect(workspace) as reader:
                    count=reader.execute("SELECT COUNT(*) FROM xstage_songs").fetchone()[0]
                elapsed=time.monotonic()-started
                self.assertEqual(count,0)
                self.assertLess(
                    elapsed,1.0,
                    f"UI read waited {elapsed:.3f}s behind active WAL writer")

    def test_normal_connections_do_not_execute_journal_mode_assignment(self):
        source=Path(core.__file__).read_text(encoding="utf-8")
        connect_block=source[source.index("@contextmanager\ndef connect"):
                             source.index('SCHEMA = """')]
        self.assertNotIn("journal_mode=WAL",connect_block)


if __name__=="__main__":
    unittest.main()
