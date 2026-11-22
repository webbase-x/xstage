"""Rollback must not partially mutate live files when a later JSON snapshot is corrupt."""
import tempfile
import unittest
from pathlib import Path

from karaoke.restore import rollback


class RollbackJsonPreflightTests(unittest.TestCase):
    def test_corrupt_later_json_snapshot_preserves_all_live_targets(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root) / 'data'
            safety = Path(root) / 'safety'
            data.mkdir()
            safety.mkdir()
            (data / 'settings.json').write_text('{"live": 1}', encoding='utf-8')
            (data / 'queue.json').write_text('{"live": 2}', encoding='utf-8')
            (safety / 'settings.json').write_text('{"saved": 1}', encoding='utf-8')
            (safety / 'queue.json').write_text('{"broken":', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'JSON'):
                rollback(data, safety, ['settings.json', 'queue.json'],
                         ('settings.json', 'queue.json'))
            self.assertEqual((data / 'settings.json').read_text(encoding='utf-8'), '{"live": 1}')
            self.assertEqual((data / 'queue.json').read_text(encoding='utf-8'), '{"live": 2}')

    def test_valid_json_snapshot_still_restores(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root) / 'data'
            safety = Path(root) / 'safety'
            data.mkdir()
            safety.mkdir()
            (data / 'settings.json').write_text('{"live": true}', encoding='utf-8')
            (safety / 'settings.json').write_text('{"saved": true}', encoding='utf-8')
            rollback(data, safety, ['settings.json'], ('settings.json',))
            self.assertEqual((data / 'settings.json').read_text(encoding='utf-8'), '{"saved": true}')


if __name__ == '__main__':
    unittest.main()
