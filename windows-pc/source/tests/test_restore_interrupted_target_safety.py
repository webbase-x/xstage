"""P0.6: interrupted restore must not overwrite an untrusted live target."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from karaoke import restore
from karaoke.library import write_json


class InterruptedTargetSafetyTests(unittest.TestCase):
    def test_linked_live_target_rejected_before_rollback(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            data = base / "data"
            pending = data / "restore-pending"
            safety = data / "restore-safety-test"
            pending.mkdir(parents=True)
            safety.mkdir()
            outside = base / "outside.json"
            outside.write_text('{"untouched":true}', encoding="utf-8")
            live = data / "settings.json"
            try:
                live.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            (safety / "settings.json").write_text('{"restored":true}', encoding="utf-8")
            write_json(pending / "state.json", {
                "status": "applying", "safety": safety.name,
                "existed": ["settings.json"], "replaced": ["settings.json"],
            })
            with patch.object(restore, "rollback") as rollback:
                with self.assertRaisesRegex(ValueError, "ปลายทางย้อนคืนไม่ปลอดภัย"):
                    restore.apply_pending(data)
                rollback.assert_not_called()
            self.assertEqual(outside.read_text(encoding="utf-8"), '{"untouched":true}')
            self.assertTrue(pending.exists())

    def test_directory_live_target_rejected_before_rollback(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root)
            pending = data / "restore-pending"
            safety = data / "restore-safety-test"
            pending.mkdir()
            safety.mkdir()
            (data / "settings.json").mkdir()
            (safety / "settings.json").write_text("{}", encoding="utf-8")
            write_json(pending / "state.json", {
                "status": "applying", "safety": safety.name,
                "existed": ["settings.json"], "replaced": ["settings.json"],
            })
            with patch.object(restore, "rollback") as rollback:
                with self.assertRaisesRegex(ValueError, "ปลายทางย้อนคืนไม่ปลอดภัย"):
                    restore.apply_pending(data)
                rollback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
