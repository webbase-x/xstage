"""Reject ambiguous MIDI channel identifiers before routing."""
import unittest
from karaoke.audio_bus import plan_from_mapping


class AudioBusChannelKeyTests(unittest.TestCase):
    def test_non_integer_channel_keys_rejected(self):
        for invalid in (False, True, 0.0, 1.0):
            with self.subTest(invalid=invalid, kind=type(invalid)):
                mapping = {ch: ch % 4 for ch in range(16)}
                del mapping[int(invalid)]
                mapping[invalid] = 0
                with self.assertRaises(ValueError):
                    plan_from_mapping(4, mapping)

    def test_integer_channels_preserve_routing(self):
        for count in (2, 4, 8, 16):
            plan = plan_from_mapping(count, {ch: ch % count for ch in range(16)})
            self.assertEqual([plan.bus_for_channel(ch) for ch in range(16)], [ch % count for ch in range(16)])
