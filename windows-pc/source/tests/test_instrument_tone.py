"""Regression tests for BASSMIDI channel/drum tone and persistence.

No system speakers, SoundFont or installer needed for these source tests.
"""
import copy
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call

from karaoke.bass import (
    BassSynth, MIDI_EVENT_CUTOFF, MIDI_EVENT_RESONANCE,
    MIDI_EVENT_DRUM_CUTOFF, MIDI_EVENT_DRUM_RESONANCE, MIDI_EVENT_DRUM_LEVEL
)
from karaoke.instrument_tone import (
    CHANNEL_DEFAULT, DRUM_DEFAULT, normalized, changed, get, apply_to_player
)
from karaoke.playback import MidiPlayer


class FakeSynth:
    def __init__(self):
        self.messages = []
        self.filters = []
        self.drums = []
    def send(self, data):
        self.messages.append(data)
    def reset(self):
        self.messages.append(b'RESET')
    def set_channel_tone(self, channel, **state):
        self.filters.append((channel, dict(state)))
    def set_drum_tone(self, note, **state):
        self.drums.append((note, dict(state)))
    def close(self):
        pass


class TonePresetTests(unittest.TestCase):
    def test_neutral_defaults_sparse_preset(self):
        self.assertEqual(normalized(None), {'channels': {}, 'drums': {}})
        self.assertEqual(get(None, 'channels', 2), CHANNEL_DEFAULT)
        self.assertEqual(get(None, 'drums', 38), DRUM_DEFAULT)
        self.assertFalse(apply_to_player(MidiPlayer(output=Mock(spec=['send','reset','close'])), None))

    def test_validate_rejects_corrupt_values(self):
        invalid = (
            [], 'settings', {'unknown': {}}, {'channels': []},
            {'channels': {'16': dict(CHANNEL_DEFAULT)}},
            {'channels': {'-1': dict(CHANNEL_DEFAULT)}},
            {'channels': {'0': {'cutoff': 80}}},
            {'drums': {'128': dict(DRUM_DEFAULT)}},
            {'drums': {'40': dict(DRUM_DEFAULT, level=True)}},
            {'channels': {'1': dict(CHANNEL_DEFAULT, cutoff=128)}},
            {'channels': {'1': dict(CHANNEL_DEFAULT, resonance=64.5)}},
        )
        for source in invalid:
            with self.subTest(source=source), self.assertRaises(ValueError):
                normalized(source)

    def test_changed_and_get_do_not_mutate_caller(self):
        before = {'channels': {}, 'drums': {}}
        after = changed(before, 'channels', 0, {'cutoff': 80, 'resonance': 40})
        self.assertEqual(before['channels'], {})
        state = get(after, 'channels', 0)
        state['cutoff'] = 0
        self.assertEqual(after['channels']['0']['cutoff'], 80)
        more = changed(after, 'drums', 38, {'cutoff': 35, 'resonance': 70, 'level': 90})
        self.assertEqual(more['drums']['38']['level'], 90)

    def test_saved_tone_applies_to_native_output_only(self):
        preset = {'channels': {'3': {'cutoff': 74, 'resonance': 40}},
                  'drums': {'36': {'cutoff': 45, 'resonance': 80, 'level': 92}}}
        out = FakeSynth()
        player = MidiPlayer(output=out)
        self.assertTrue(apply_to_player(player, preset))
        self.assertEqual(out.filters[-1], (3, preset['channels']['3']))
        self.assertEqual(out.drums[-1], (36, preset['drums']['36']))
        other = MidiPlayer(output=Mock(spec=['send','reset','close']))
        with self.assertRaises(OSError):
            apply_to_player(other, preset)
        self.assertEqual(other.channel_tone, [None]*16)

    def test_cc_filter_override_and_reset_restoration(self):
        output = FakeSynth()
        player = MidiPlayer(output=output)
        player.set_channel_tone(2, 80, 50)
        player.set_drum_tone(38, 70, 30, 90)
        player._send(bytes([0xB2, 74, 1]))  # CC cutoff from song
        player._send(bytes([0xB2, 71, 2]))  # CC resonance from song
        self.assertEqual(output.messages[-2:], [bytes([0xB2, 74, 80]), bytes([0xB2, 71, 50])])
        player._send(bytes([0xB2, 121, 0]))
        self.assertEqual(output.filters[-1][1], {'cutoff': 80, 'resonance': 50})
        before = len(output.drums)
        player._reset_state()  # Seek and new song restore every edited drum key.
        self.assertGreater(len(output.drums), before)
        self.assertEqual(output.drums[-1], (38, {'cutoff': 70, 'resonance': 30, 'level': 90}))
        player._send(bytes([0xB0, 74, 25]))  # Untouched channels stay untouched.
        self.assertEqual(output.messages[-1], bytes([0xB0, 74, 25]))

    def test_failed_native_filter_is_not_reported_as_applied(self):
        output = FakeSynth()
        output.set_channel_tone = Mock(side_effect=OSError('device unplugged'))
        player = MidiPlayer(output=output)
        with self.assertRaises(OSError):
            player.set_channel_tone(0, 80, 64)
        self.assertIsNone(player.channel_tone[0])


class NativeToneEventTests(unittest.TestCase):
    @staticmethod
    def fake():
        synth = BassSynth.__new__(BassSynth)
        synth.lock = threading.RLock()
        synth.stream = 66
        synth.midi = SimpleNamespace(BASS_MIDI_StreamEvent=Mock(return_value=1))
        synth.dll = SimpleNamespace(BASS_ErrorGetCode=Mock(return_value=5))
        return synth

    def test_channel_events_use_bassmidi_stream_event(self):
        synth = self.fake()
        synth.set_channel_tone(5, 92, 30)
        self.assertEqual(synth.midi.BASS_MIDI_StreamEvent.call_args_list, [
            call(66, 5, MIDI_EVENT_CUTOFF, 92),
            call(66, 5, MIDI_EVENT_RESONANCE, 30),
        ])

    def test_drum_events_address_individual_note_on_channel_ten(self):
        synth = self.fake()
        synth.set_drum_tone(38, 54, 77, 99)
        self.assertEqual(synth.midi.BASS_MIDI_StreamEvent.call_args_list, [
            call(66, 9, MIDI_EVENT_DRUM_CUTOFF, 38 | (54 << 8)),
            call(66, 9, MIDI_EVENT_DRUM_RESONANCE, 38 | (77 << 8)),
            call(66, 9, MIDI_EVENT_DRUM_LEVEL, 38 | (99 << 8)),
        ])

    def test_native_error_is_not_silent(self):
        synth = self.fake()
        synth.midi.BASS_MIDI_StreamEvent.return_value = 0
        with self.assertRaisesRegex(OSError, 'BASS 5'):
            synth.set_channel_tone(0, 64, 64)
        synth.midi.BASS_MIDI_StreamEvent.assert_called_once()

    def test_closed_native_stream_refuses_changes(self):
        synth = self.fake()
        synth.stream = 0
        with self.assertRaises(OSError):
            synth.set_drum_tone(36, 64, 64, 127)
        synth.midi.BASS_MIDI_StreamEvent.assert_not_called()


if __name__ == '__main__':
    unittest.main()
