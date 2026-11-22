"""P0.6: malformed saved queue envelopes must never partially roll back user data."""
import tempfile
import unittest
from pathlib import Path

from karaoke.restore import rollback


class RollbackQueueEnvelopeTests(unittest.TestCase):
    def test_invalid_queue_envelope_preserves_earlier_settings(self):
        invalid = (
            '{"format":"unknown.playlist","tracks":[]}',
            '{"format":"xstage.playlist","tracks":null}',
            '{"format":"newKaraoke.playlist","tracks":[42]}',
            '{"format":"xstage.playlist"}',
            '{"tracks":[]}',
            '[null]',
        )
        for payload in invalid:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as root:
                data, safety = Path(root) / 'data', Path(root) / 'safety'
                data.mkdir()
                safety.mkdir()
                (data / 'settings.json').write_text('{"version":"live"}', encoding='utf-8')
                (safety / 'settings.json').write_text('{"version":"old"}', encoding='utf-8')
                (data / 'queue.json').write_text('[]', encoding='utf-8')
                (safety / 'queue.json').write_text(payload, encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'queue.json'):
                    rollback(data, safety, ['settings.json', 'queue.json'],
                             ('settings.json', 'queue.json'))
                self.assertEqual((data / 'settings.json').read_text(encoding='utf-8'),
                                 '{"version":"live"}')
                self.assertEqual((data / 'queue.json').read_text(encoding='utf-8'), '[]')

    def test_valid_legacy_queue_envelopes_are_preserved(self):
        for format_name in ('xstage.playlist', 'newKaraoke.playlist'):
            with self.subTest(format_name=format_name), tempfile.TemporaryDirectory() as root:
                data, safety = Path(root) / 'data', Path(root) / 'safety'
                data.mkdir()
                safety.mkdir()
                (data / 'queue.json').write_text('[]', encoding='utf-8')
                payload = '{"format":"' + format_name + '","tracks":[]}'
                (safety / 'queue.json').write_text(payload, encoding='utf-8')
                rollback(data, safety, ['queue.json'], ('queue.json',))
                self.assertEqual((data / 'queue.json').read_text(encoding='utf-8'), payload)


if __name__ == '__main__':
    unittest.main()
