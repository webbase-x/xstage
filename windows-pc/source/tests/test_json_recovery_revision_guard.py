"""P0.6 regression: recovery must not overwrite concurrently changed data."""
import tempfile
import unittest
from pathlib import Path

from karaoke.json_recovery import restore_json, target_revision


class JsonRecoveryRevisionGuardTests(unittest.TestCase):
    def test_changed_target_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "queue.json"
            candidate = root / "queue.bak"
            target.write_text("[]", encoding="utf-8")
            candidate.write_text("[]", encoding="utf-8")
            old_revision = target_revision(target)
            target.write_text('[{"sentinel":"new"}]', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "เปลี่ยน"):
                restore_json(target, candidate, expected_target=old_revision)
            self.assertEqual(target.read_text(encoding="utf-8"), '[{"sentinel":"new"}]')

    def test_changed_candidate_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "queue.json"
            candidate = root / "queue.bak"
            target.write_text("[]", encoding="utf-8")
            candidate.write_text("[]", encoding="utf-8")
            candidate.write_text("[ ]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "เปลี่ยน"):
                restore_json(target, candidate, expected=b"[]")
            self.assertEqual(target.read_bytes(), b"[]")


if __name__ == "__main__":
    unittest.main()
