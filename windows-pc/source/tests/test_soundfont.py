import ctypes
import math
import os
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call
from karaoke.soundfont import normalize_audio, inspect_font
from karaoke.playback import MidiPlayer, can_autoplay_search
from karaoke.bass import BassSynth, BASS_ATTRIB_MIDI_SRC, BASS_ATTRIB_MIDI_VOICES, BASS_SAMPLE_FLOAT
from soundfont_fixture import make_font


class SoundFontTests(unittest.TestCase):
    def test_legacy_migrates_and_defaults_leave_headroom(self):
        result = normalize_audio({'soundfont': 'D:/เสียง/ชุดเสียง.sf2'})
        self.assertEqual(result['fonts'], [{'path': str(Path('D:/เสียง/ชุดเสียง.sf2')), 'gain_db': -6.0}])
        self.assertEqual((result['quality'], result['voices'], result['buffer_ms']), (2, 512, 80))
        self.assertEqual(result['effects_mode'], 'song')

    def test_invalid_settings_fail_before_native_audio(self):
        for field, values in {'quality': [-1, 3, .5], 'voices': [0, 1025], 'buffer_ms': [0, 201], 'reverb': [-1, 128, float('nan')], 'chorus': ['abc', float('inf')]}.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    normalize_audio({'soundfont_audio': {field: value}})
        with self.assertRaises(ValueError):
            normalize_audio({'soundfont_audio': {'fonts': [{'path': 'a.sf2', 'gain_db': 5}]}})
        with self.assertRaises(ValueError):
            normalize_audio({'soundfont_audio': {'fonts': [{'path': 'A.sf2'}, {'path': 'a.sf2'}]}})

    def test_metadata_preserves_unicode_paths_and_rejects_truncation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = make_font(Path(folder)/'เสียงทดสอบ.sf2')
            info = inspect_font(path)
            self.assertIn('GM 1/128', info['summary'])
            self.assertEqual(info['presets'][0][:2], (0, 0))
            path.write_bytes(path.read_bytes()[:-10])
            with self.assertRaises(ValueError):
                inspect_font(path)

    def test_enter_preserves_loaded_song_even_with_empty_waiting_queue(self):
        for playing, position in [(True, 12), (False, 12), (False, 0)]:
            engine = SimpleNamespace(playing=playing, position=position, duration=120)
            self.assertFalse(can_autoplay_search(engine, []))
        self.assertTrue(can_autoplay_search(None, []))
        self.assertFalse(can_autoplay_search(None, [1]))
        self.assertTrue(can_autoplay_search(SimpleNamespace(playing=False, position=120, duration=120), []))

    def test_actual_search_handler_adds_once_and_does_not_restart_loaded_song(self):
        from karaoke.performer import PlaybackApp
        for playing, position in [(True, 12), (False, 12), (False, 0)]:
            app = PlaybackApp.__new__(PlaybackApp)
            app.search_pending = False
            app.search_revision = app.search_result_revision = 1
            app.songs = Mock()
            app.songs.selection.return_value = ('20120',)
            app.library = Mock()
            app.library.get.return_value = {'id': 20120, 'playable': True, 'title': 'รักน้องพร', 'path':'song.mid'}
            app.engine = SimpleNamespace(playing=playing, position=position, duration=120)
            engine = app.engine
            app.song_queue = SimpleNamespace(items=[])
            app.song_queue.add = app.song_queue.items.append
            app.status_var = Mock()
            app.start_song = Mock()
            app.refresh_queue = Mock()
            app.remember_search = Mock()
            app.hide_search = Mock()
            self.assertEqual(app.confirm_search(), 'break')
            self.assertEqual([item.song_id for item in app.song_queue.items], [20120])
            self.assertIs(app.engine, engine)
            self.assertEqual((engine.playing, engine.position), (playing, position))
            app.start_song.assert_not_called()

    def fake_api(self, fail_font=0, init_success=1):
        dll, midi = Mock(), Mock()
        for name in ('BASS_SetConfig', 'BASS_Init', 'BASS_GetDevice', 'BASS_SetDevice', 'BASS_Free', 'BASS_ChannelPlay', 'BASS_StreamFree', 'BASS_ChannelSetAttribute', 'BASS_ChannelGetData'):
            getattr(dll, name).return_value = 1
        dll.BASS_Init.return_value = init_success
        dll.BASS_ErrorGetCode.return_value = 14 if not init_success else 41
        midi.BASS_MIDI_StreamCreate.return_value = 50
        midi.BASS_MIDI_FontInit.side_effect = [101, 0 if fail_font else 102]
        midi.BASS_MIDI_FontFree.return_value = 1
        midi.BASS_MIDI_FontSetVolume.return_value = 1
        midi.BASS_MIDI_StreamSetFonts.return_value = 1
        def events(handle, flags, data, length):
            self.messages.append(ctypes.string_at(data, length))
            return length
        self.messages = []
        midi.BASS_MIDI_StreamEvents.side_effect = events
        return dll, midi

    def test_stack_order_gain_float_quality_and_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [make_font(Path(folder)/f'{i}.sf2') for i in (1, 2)]
            dll, midi = self.fake_api()
            settings = {'soundfont_audio': {'fonts': [{'path': str(p), 'gain_db': gain} for p, gain in zip(paths, (-6, -12))]}}
            synth = BassSynth(Path(folder), settings=settings, bindings=(dll, midi))
            self.assertEqual(midi.BASS_MIDI_StreamCreate.call_args.args, (16, BASS_SAMPLE_FLOAT, 48000))
            config = midi.BASS_MIDI_StreamSetFonts.call_args.args[1]
            self.assertEqual([row.font for row in config], [101, 102])
            dll.BASS_ChannelSetAttribute.assert_any_call(50, BASS_ATTRIB_MIDI_SRC, 2)
            dll.BASS_ChannelSetAttribute.assert_any_call(50, BASS_ATTRIB_MIDI_VOICES, 512)
            midi.BASS_MIDI_FontSetVolume.assert_any_call(101, 10**(-6/20))
            synth.close(); synth.close()
            self.assertEqual(midi.BASS_MIDI_FontFree.call_count, 2)
            dll.BASS_StreamFree.assert_called_once_with(50)
            dll.BASS_Free.assert_called_once()

    def test_offline_batch_recreates_stream_but_reuses_font(self):
        with tempfile.TemporaryDirectory() as folder:
            font=make_font(Path(folder)/'test.sf2')
            dll,midi=self.fake_api()
            midi.BASS_MIDI_FontInit.side_effect=[101]
            midi.BASS_MIDI_StreamCreate.side_effect=[50,51,52]
            synth=BassSynth(Path(folder),settings={'soundfont':str(font)},
                            decode=True,bindings=(dll,midi))
            try:
                synth.start_offline_song()
                synth.start_offline_song()
                self.assertEqual(midi.BASS_MIDI_FontInit.call_count,1)
                self.assertEqual(midi.BASS_MIDI_StreamCreate.call_count,3)
                self.assertEqual(midi.BASS_MIDI_StreamSetFonts.call_count,3)
                self.assertEqual(dll.BASS_StreamFree.call_args_list, [call(50),call(51)])
            finally:
                synth.close()
            self.assertEqual(dll.BASS_StreamFree.call_args_list[-1],call(52))
            self.assertEqual(midi.BASS_MIDI_FontFree.call_count,1)

    def test_instrument_mapping_reaches_native_stream_before_play(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [make_font(Path(folder)/f'{i}.sf2') for i in (1, 2)]
            dll, midi = self.fake_api()
            settings = {'soundfont_audio': {'fonts': [{'path': str(p)} for p in paths]},
                        'instrument_fonts': {'guitar': {'path':str(paths[1]),'bank':0,'preset':0}, 'drums': {'path':str(paths[0]),'bank':0,'preset':0}}}
            order = Mock()
            order.attach_mock(midi.BASS_MIDI_StreamSetFonts, 'assign')
            order.attach_mock(dll.BASS_ChannelPlay, 'play')
            synth = BassSynth(Path(folder), settings=settings, bindings=(dll, midi))
            try:
                stream, config, count = midi.BASS_MIDI_StreamSetFonts.call_args.args
                rows = [(r.font, r.dpreset, r.dbank) for r in config]
                self.assertTrue(all((r.spreset,r.sbank)==(0,0) for r in config[:136]))
                self.assertEqual(rows[:8], [(102, p, 0) for p in range(24, 32)])
                self.assertEqual(rows[8:136], [(101, p, 128) for p in range(128)])
                self.assertEqual(rows[136:], [(101, -1, 0), (102, -1, 0)])
                self.assertEqual((stream, count), (50, 138 | 0x1000000))
                self.assertEqual([c[0] for c in order.mock_calls], ['assign', 'play'])
            finally:
                synth.close()

    def test_stale_mapping_rejected_before_device_initialization(self):
        with tempfile.TemporaryDirectory() as folder:
            path = make_font(Path(folder)/'test.sf2')
            dll, midi = self.fake_api()
            with self.assertRaises(ValueError):
                BassSynth(Path(folder), settings={'soundfont': str(path),
                    'instrument_fonts': {'bass': str(Path(folder)/'removed.sf2')}}, bindings=(dll, midi))
            dll.BASS_Init.assert_not_called()
            midi.BASS_MIDI_StreamCreate.assert_not_called()

    def test_native_mapping_failure_releases_stream_and_fonts(self):
        with tempfile.TemporaryDirectory() as folder:
            path = make_font(Path(folder)/'test.sf2')
            dll, midi = self.fake_api()
            midi.BASS_MIDI_StreamSetFonts.return_value = 0
            with self.assertRaises(OSError):
                BassSynth(Path(folder), settings={'soundfont': str(path),
                    'instrument_fonts': {'piano': str(path)}}, bindings=(dll, midi))
            dll.BASS_ChannelPlay.assert_not_called()
            dll.BASS_StreamFree.assert_called_once_with(50)
            midi.BASS_MIDI_FontFree.assert_called_once_with(101)
            dll.BASS_Free.assert_called_once()

    def test_live_refill_precedes_stream_creation_for_all_buffers(self):
        from karaoke.bass import BASS_CONFIG_UPDATEPERIOD, BASS_CONFIG_BUFFER, BASS_ATTRIB_BUFFER
        with tempfile.TemporaryDirectory() as folder:
            path = make_font(Path(folder)/'test.sf2')
            for ms in (40, 60, 80, 100, 150, 200):
                dll, midi = self.fake_api()
                order = Mock()
                order.attach_mock(dll.BASS_SetConfig, 'config')
                order.attach_mock(midi.BASS_MIDI_StreamCreate, 'create')
                synth = BassSynth(Path(folder), settings={'soundfont': str(path),
                    'soundfont_audio': {'buffer_ms': ms, 'quality': 2, 'voices': 512}},
                    bindings=(dll, midi))
                self.assertEqual(order.mock_calls[:3], [
                    call.config(BASS_CONFIG_UPDATEPERIOD, 10),
                    call.config(BASS_CONFIG_BUFFER, 500),
                    call.create(16, BASS_SAMPLE_FLOAT, 48000)])
                self.assertLess(10, ms)
                dll.BASS_ChannelSetAttribute.assert_any_call(50, BASS_ATTRIB_BUFFER, ms/1000)
                synth.close()

    def test_refill_failure_closes_device_without_starting_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            path = make_font(Path(folder)/'test.sf2')
            for results in ([0], [1, 0]):
                dll, midi = self.fake_api()
                dll.BASS_SetConfig.side_effect = results
                with self.assertRaises(OSError):
                    BassSynth(Path(folder), path, bindings=(dll, midi))
                midi.BASS_MIDI_StreamCreate.assert_not_called()
                dll.BASS_ChannelPlay.assert_not_called()
                dll.BASS_Free.assert_called_once()

    def test_offline_render_does_not_change_live_buffer_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            path = make_font(Path(folder)/'test.sf2')
            dll, midi = self.fake_api()
            synth = BassSynth(Path(folder), path, decode=True, bindings=(dll, midi))
            dll.BASS_SetConfig.assert_not_called()
            dll.BASS_ChannelPlay.assert_not_called()
            synth.close()

    def test_partial_failure_releases_only_owned_resources(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [make_font(Path(folder)/f'{i}.sf2') for i in (1, 2)]
            settings = {'soundfont_audio': {'fonts': [{'path': str(p)} for p in paths]}}
            dll, midi = self.fake_api(fail_font=1)
            with self.assertRaises(OSError):
                BassSynth(Path(folder), settings=settings, bindings=(dll, midi))
            midi.BASS_MIDI_FontFree.assert_called_once_with(101)
            dll.BASS_Free.assert_called_once()
            dll, midi = self.fake_api(init_success=0)
            with self.assertRaises(OSError):
                BassSynth(Path(folder), settings=settings, bindings=(dll, midi))
            dll.BASS_Free.assert_not_called()

    def test_custom_effects_survive_song_controller_events_and_seek(self):
        with tempfile.TemporaryDirectory() as folder:
            path = make_font(Path(folder)/'test.sf2')
            dll, midi = self.fake_api()
            settings = {'soundfont': str(path), 'soundfont_audio': {'effects_mode': 'custom', 'reverb': 45, 'chorus': 9}}
            synth = BassSynth(Path(folder), settings=settings, bindings=(dll, midi))
            synth.send(bytes([0xb3, 91, 127])); self.assertEqual(self.messages[-1], bytes([0xb3, 91, 45]))
            synth.send(bytes([0xb3, 93, 0])); self.assertEqual(self.messages[-1], bytes([0xb3, 93, 9]))
            player = MidiPlayer(output=synth)
            player.seek(0)
            self.assertIn(bytes([0xb3, 91, 45, 0xb3, 93, 9]), self.messages[-120:])
            player.close()

    def test_song_effects_are_not_overridden(self):
        with tempfile.TemporaryDirectory() as folder:
            path = make_font(Path(folder)/'test.sf2')
            dll, midi = self.fake_api()
            synth = BassSynth(Path(folder), path, bindings=(dll, midi))
            message = bytes([0xb0, 91, 73])
            synth.send(message)
            self.assertEqual(self.messages, [message])
            synth.close()


@unittest.skipUnless(os.environ.get('XSTAGE_BASS_TEST_NATIVE'), 'Set XSTAGE_BASS_TEST_NATIVE to official native libraries for PCM rendering')
class NativeSoundFontTests(unittest.TestCase):
    def render_font(self, path, gain, mode='song'):
        synth = BassSynth(Path(os.environ['XSTAGE_BASS_TEST_NATIVE']), settings={
            'soundfont_audio': {'fonts': [{'path': str(path), 'gain_db': gain}], 'effects_mode': mode, 'reverb': 100, 'chorus': 60}}, decode=True)
        try:
            synth.send(bytes([0xc0, 0]))
            synth.send(bytes([0x90, 69, 100]))
            pcm = synth.render(24000)
            synth.send(bytes([0x80, 69, 0]))
            tail = synth.render(24000)
            return struct.unpack('<'+str(len(pcm)//4)+'f', pcm), tail
        finally:
            synth.close()

    def test_real_native_float_pcm_gain_effects_and_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            path = make_font(Path(folder)/'เสียงทดสอบ.sf2')
            pcm, tail = self.render_font(path, -6)
            quiet, _ = self.render_font(path, -12)
            wet, wet_tail = self.render_font(path, -6, 'custom')
            self.assertEqual(len(pcm), 48000)
            self.assertTrue(all(math.isfinite(x) for x in pcm))
            rms = lambda x: math.sqrt(sum(v*v for v in x)/len(x))
            self.assertGreater(rms(pcm), .001)
            self.assertLess(max(abs(x) for x in pcm), 1)
            self.assertAlmostEqual(rms(quiet)/rms(pcm), 10**(-6/20), delta=.04)
            self.assertNotEqual(tail, wet_tail)
            self.assertNotEqual(pcm, wet)


if __name__ == '__main__':
    unittest.main()
