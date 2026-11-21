"""ASIO preference and BASS fallback; no physical device required."""
import unittest
from karaoke.asio_backend import create_midi_output


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.bass = lambda native, settings: ('bass', native)

    def test_default_is_bass(self):
        result = create_midi_output('native', {}, bass_factory=self.bass)
        self.assertEqual(result, ('bass', 'native'))

    def test_explicit_asio(self):
        result = create_midi_output(
            'native', {'asio_output': {'enabled': True, 'device': 2, 'channel': 0}},
            bass_factory=self.bass,
            asio_factory=lambda native, device, channel, settings: ('asio', device, channel))
        self.assertEqual(result, ('asio', 2, 0))

    def test_failed_asio_falls_back_and_reports(self):
        def failed(**kwargs):
            raise OSError('driver unavailable')
        result = create_midi_output(
            'native', {'asio_output': {'enabled': True, 'device': 0}},
            notify=self.events.append, bass_factory=self.bass,
            asio_factory=lambda *args, **kwargs: failed(**kwargs))
        self.assertEqual(result[0], 'bass')
        self.assertIn('driver unavailable', self.events[0])

    def test_invalid_device_falls_back(self):
        result = create_midi_output(
            'native', {'asio_output': {'enabled': True, 'device': '0'}},
            notify=self.events.append, bass_factory=self.bass)
        self.assertEqual(result[0], 'bass')
        self.assertTrue(self.events)


if __name__ == '__main__':
    unittest.main()
