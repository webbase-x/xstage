"""Regression for live import observability and version reporting."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import plus_core as core
import pro_updater as updater


class ImportObservabilityTests(unittest.TestCase):
    def test_progress_is_logged_and_private_throttle_state_is_hidden(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(core, "interrupted_import", return_value=None):
                state = app.State(folder)
            job = {
                "id": "thai-song-test", "kind": "import",
                "started_at": time.monotonic(), "updated_at": time.time(),
                "progress": {}, "message": "", "revision": 0,
                "status": "running",
            }
            state.update(job, {"files_seen": 1, "files_new": 1}, "ทดสอบเพลง.mid")
            state.jobs[job["id"]] = job
            snapshot = state.jobs_snapshot()[0]
            self.assertGreaterEqual(snapshot["progress_age"], 0)
            self.assertNotIn("_progress_logged_at", snapshot)
            self.assertEqual(snapshot["progress"]["files_seen"], 1)
            events = [
                json.loads(line) for line in state.log_path.read_text(
                    encoding="utf-8").splitlines()
            ]
            self.assertTrue(any(item["event"] == "job.progress" and
                                item["files_seen"] == 1 for item in events))
            before = len(events)
            state.update(job, {"files_seen": 2}, "ทดสอบเพลง 2.mid")
            after = len(state.log_path.read_text(
                encoding="utf-8").splitlines())
            self.assertEqual(after, before, "progress log must be throttled")

    def test_session_is_canonical_updater_version(self):
        from inspect import getsource
        self.assertIn('"version":updater.VERSION', getsource(app.Handler.handle_get))
        self.assertEqual(updater.VERSION, "0.1.35")


if __name__ == "__main__":
    unittest.main()
