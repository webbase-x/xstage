"""Regression: diagnostics must never prevent a safe BASS startup fallback."""
import unittest

from karaoke.asio_backend import create_midi_output


class AsioStartupNoticeSafetyTests(unittest.TestCase):
    def test_notice_exception_does_not_block_bass_fallback(self):
        created = []
        def bass_factory(native, *, settings):
            output = object()
            created.append(output)
            return output
        def asio_factory(*args, **kwargs):
            raise OSError('driver unavailable')
        def broken_notice(message):
            raise RuntimeError('UI already closed')

        with self.assertLogs(level='WARNING') as captured:
            output = create_midi_output(
                'native', {'asio_output': {'enabled': True, 'device': 0}},
                notify=broken_notice, bass_factory=bass_factory,
                asio_factory=asio_factory)
        self.assertEqual(len(captured.records), 1)
        self.assertEqual(captured.records[0].levelname, 'WARNING')
        self.assertFalse(captured.records[0].exc_info)
        self.assertIn('Unable to surface ASIO', captured.records[0].getMessage())
        self.assertIs(output, created[0])
        self.assertEqual(len(created), 1)

    def test_invalid_device_with_broken_notice_still_uses_bass(self):
        fallback = object()
        output = create_midi_output(
            'native', {'asio_output': {'enabled': True, 'device': -1}},
            notify=lambda message: (_ for _ in ()).throw(ValueError('closed')),
            bass_factory=lambda native, *, settings: fallback,
            asio_factory=lambda *args, **kwargs: self.fail('ASIO must not start'))
        self.assertIs(output, fallback)


if __name__ == '__main__':
    unittest.main()
