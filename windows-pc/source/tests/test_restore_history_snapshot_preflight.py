"""P0.6: a corrupt optional history must never cause partial rollback."""
import tempfile
import unittest
from pathlib import Path

from karaoke.restore import rollback


class HistoryRollbackPreflightTests(unittest.TestCase):
    def test_invalid_history_snapshot_preserves_earlier_live_settings(self):
        for invalid in ('42', '{"events": "not-a-list"}', '[42]'):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as root:
                data, safety = Path(root) / 'live', Path(root) / 'safety'
                data.mkdir()
                safety.mkdir()
                current = '{"title":"current"}'
                (data / 'settings.json').write_text(current, encoding='utf-8')
                (safety / 'settings.json').write_text('{"title":"old"}', encoding='utf-8')
                (data / 'history.json').write_text('[]', encoding='utf-8')
                (safety / 'history.json').write_text(invalid, encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'history.json'):
                    rollback(data, safety, ['settings.json', 'history.json'],
                             ('settings.json', 'history.json'))
                self.assertEqual((data / 'settings.json').read_text(encoding='utf-8'), current)
                self.assertEqual((data / 'history.json').read_text(encoding='utf-8'), '[]')


if __name__ == '__main__':
    unittest.main()
