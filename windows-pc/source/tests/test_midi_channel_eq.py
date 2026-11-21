"""Verify isolated 31-band SoundFont EQ per MIDI channel (no live hardware)."""
import copy
import threading
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch, call

from karaoke.bass import BassSynth
from karaoke.graphic_eq import flat
from karaoke.midi_channel_eq import normalized, changed, get, apply_to_player
from karaoke.playback import MidiPlayer


class FakeOutput:
    def __init__(self):
        self.fx = []
    def send(self, data):
        pass
    def reset(self):
        pass
    def close(self):
        pass
    def set_channel_eq(self, channel, state):
        self.fx.append((channel, copy.deepcopy(state)))


class ChannelEQPresetTests(unittest.TestCase):
    def test_sparse_presets_and_stable_channel_lookup(self):
        self.assertEqual(normalized(None), {})
        state = flat()
        state['bands'][17]['gain_db'] = 6
        new = changed({}, 0, state)
        self.assertEqual(new['0'], state)
        self.assertEqual(get(new, 0)['bands'][17]['gain_db'], 6)
        self.assertEqual(get(new, 1), flat())
        empty = changed(new, 0, flat())
        self.assertEqual(empty, {})
        self.assertIn('0', new)

    def test_rejects_bad_channel_and_curve(self):
        for value in ([], {'16': flat()}, {'-1': flat()}, {'foo': flat()},
                      {'1': {}}, {True: flat()}):
            with self.subTest(data=value), self.assertRaises(ValueError):
                normalized(value)

    def test_channel_eq_reaches_only_selected_native_channel(self):
        state = flat()
        state['bands'][15]['gain_db'] = 4
        player = MidiPlayer(output=FakeOutput())
        apply_to_player(player, {'5': state})
        self.assertEqual(player.output.fx, [(5, state)])
        self.assertIsNone(player.channel_eq[4])
        self.assertEqual(player.channel_eq[5], state)
        player._reset_state()
        self.assertEqual(len(player.output.fx), 1, 'Seek must not reallocate FX')

    def test_windows_midi_does_not_claim_independent_eq(self):
        player = MidiPlayer(output=Mock(spec=['send','reset','close']))
        state = flat()
        state['output_db'] = -3
        with self.assertRaises(OSError):
            apply_to_player(player, {'0': state})
        self.assertEqual(player.channel_eq, [None] * 16)


class ChannelEQNativeTests(unittest.TestCase):
    @staticmethod
    def fake():
        synth = BassSynth.__new__(BassSynth)
        synth.stream = 44
        synth.lock = threading.RLock()
        synth._channel_processors = {}
        synth._fx_library = object()
        synth._load_fx_library = Mock(return_value=synth._fx_library)
        synth.dll = NS(BASS_StreamFree=Mock(return_value=1),
                       BASS_ErrorGetCode=Mock(return_value=5))
        synth.midi = NS(BASS_MIDI_StreamGetChannel=Mock(return_value=77))
        return synth

    def test_fx_processor_installs_on_selected_midi_channel_only(self):
        synth = self.fake()
        state = flat()
        state['bands'][10]['gain_db'] = 5
        with patch('karaoke.parametric_eq.Processor') as processor:
            synth.set_channel_eq(6, state)
            synth.midi.BASS_MIDI_StreamGetChannel.assert_called_once_with(44, 6)
            args, kwargs = processor.call_args
            self.assertEqual(args[0].stream, 77)
            self.assertTrue(kwargs['graphic'])
            self.assertEqual(kwargs['rate_override'], 48000)
            processor.return_value.set.assert_called_once_with(state)
            again = copy.deepcopy(state)
            again['bands'][10]['gain_db'] = -6
            synth.set_channel_eq(6, again)
            synth.midi.BASS_MIDI_StreamGetChannel.assert_called_once()
            self.assertEqual(processor.return_value.set.call_count, 2)
            # Flat must remove FX/channel stream and free CPU.
            synth.set_channel_eq(6, flat())
            processor.return_value.close.assert_called_once()
            synth.dll.BASS_StreamFree.assert_called_once_with(77)
            self.assertEqual(synth._channel_processors, {})

    def test_bypass_unhooks_channel_but_keeps_stored_curve_outside_native(self):
        synth = self.fake()
        state = flat()
        state['bands'][0]['gain_db'] = 8
        with patch('karaoke.parametric_eq.Processor') as processor:
            synth.set_channel_eq(0, state)
            bypass = copy.deepcopy(state)
            bypass['bypass'] = True
            synth.set_channel_eq(0, bypass)
            processor.return_value.close.assert_called_once()
            self.assertEqual(synth._channel_processors, {})
            self.assertEqual(synth.dll.BASS_StreamFree.call_count, 1)

    def test_native_failure_releases_stream_and_does_not_cache(self):
        synth = self.fake()
        state = flat()
        state['bands'][0]['gain_db'] = 8
        with patch('karaoke.parametric_eq.Processor', side_effect=OSError('bad FX')):
            with self.assertRaisesRegex(OSError, 'bad FX'):
                synth.set_channel_eq(1, state)
        synth.dll.BASS_StreamFree.assert_called_once_with(77)
        self.assertEqual(synth._channel_processors, {})

    def test_no_stream_created_for_default_flat_eq(self):
        synth = self.fake()
        synth.set_channel_eq(2, flat())
        synth._load_fx_library.assert_not_called()
        synth.midi.BASS_MIDI_StreamGetChannel.assert_not_called()

    def test_close_releases_all_resources_after_fx_failure(self):
        synth = self.fake()
        synth.fonts = [11, 12]
        synth.initialized = True
        synth._device_key = ('test', False)
        synth.dll_directory = NS(close=Mock())
        synth.midi.BASS_MIDI_FontFree = Mock(return_value=1)
        synth._channel_processors[3] = (77, NS(close=Mock(side_effect=OSError('FX teardown failed'))))
        with patch('karaoke.audio_device.release') as release:
            with self.assertRaisesRegex(OSError, 'FX teardown failed'):
                synth.close()
            synth.dll.BASS_StreamFree.assert_any_call(77)
            synth.dll.BASS_StreamFree.assert_any_call(44)
            self.assertEqual(synth.midi.BASS_MIDI_FontFree.call_args_list, [call(11), call(12)])
            release.assert_called_once_with(synth.dll, ('test', False))
            self.assertEqual(synth.stream, 0)
            self.assertEqual(synth.fonts, [])
            self.assertFalse(synth.initialized)
            self.assertIsNone(synth.dll_directory)
            self.assertEqual(synth._channel_processors, {})
            synth.close()
            release.assert_called_once()


    def test_close_releases_other_eq_channels_after_first_processor_fails(self):
        synth = self.fake()
        synth.fonts = []
        synth.initialized = False
        synth.dll_directory = None
        first = Mock()
        first.close.side_effect = OSError('first EQ failed')
        second = Mock()
        synth._channel_processors = {1: (71, first), 2: (72, second)}
        with self.assertRaisesRegex(OSError, 'first EQ failed'):
            synth.close()
        first.close.assert_called_once()
        second.close.assert_called_once()
        self.assertEqual(synth.dll.BASS_StreamFree.call_args_list,
                         [call(71), call(72), call(44)])
        self.assertEqual(synth._channel_processors, {})

    def test_close_continues_after_stream_and_font_cleanup_errors(self):
        synth = self.fake()
        synth.fonts = [11, 12]
        synth.initialized = True
        synth._device_key = ('test', False)
        synth.dll_directory = NS(close=Mock())
        synth.midi.BASS_MIDI_FontFree = Mock(side_effect=[OSError('font failed'), 1])
        synth.dll.BASS_StreamFree.side_effect = OSError('stream failed')
        with patch('karaoke.audio_device.release') as release:
            with self.assertRaisesRegex(OSError, 'stream failed'):
                synth.close()
            self.assertEqual(synth.dll.BASS_StreamFree.call_args_list, [call(44)])
            self.assertEqual(synth.midi.BASS_MIDI_FontFree.call_args_list, [call(11), call(12)])
            release.assert_called_once_with(synth.dll, ('test', False))
            self.assertIsNone(synth.dll_directory)
            self.assertEqual(synth.fonts, [])
            self.assertEqual(synth.stream, 0)
            self.assertFalse(synth.initialized)



if __name__ == '__main__':
    unittest.main()
