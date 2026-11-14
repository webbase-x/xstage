import ctypes
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from karaoke.audio_auto import recommend, resolve_options, machine_specs, MemoryStatus, GIB
from karaoke.soundfont import normalize_audio


class AutoAudioTests(unittest.TestCase):
    def specs(self, threads=12, total=24, available=12):
        return dict(cpu='Test CPU', threads=threads, total=int(total*GIB),
                    available=int(available*GIB))

    def test_tiers_and_headroom(self):
        for spec, expected in [(self.specs(), (2,512,100)),
                               (self.specs(8,8,4), (1,256,150)),
                               (self.specs(2,4,1), (0,128,200)),
                               (self.specs(16,32,1), (0,128,200))]:
            r = recommend([], spec)
            self.assertEqual(tuple(r[k] for k in ('quality','voices','buffer_ms')), expected)

    def test_unknown_memory_is_conservative(self):
        r = recommend([], self.specs(32,0,0))
        self.assertEqual(r['tier'], 'safe')

    def test_large_fonts_reduce_headroom_without_reading_samples(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'large.sf2'
            with p.open('wb') as f:
                f.truncate(4*GIB)
            r = recommend([dict(path=str(p))], self.specs(16,32,5))
            self.assertEqual(r['tier'], 'light')
            self.assertEqual(r['font_bytes'], 4*GIB)

    def test_sfz_and_missing_font_never_assumed_tiny(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'external.sfz'
            p.write_text('<sample> sample=large.wav')
            for path in (p, Path(folder)/'missing.sf2'):
                r = recommend([dict(path=str(path))], self.specs())
                self.assertTrue(r['unknown_samples'])
                self.assertNotEqual(r['tier'], 'high')

    def test_manual_preserved_and_auto_rechecks_each_time(self):
        options = normalize_audio({'soundfont_audio': dict(quality=2, voices=1024, buffer_ms=60)})
        with patch('karaoke.audio_auto.machine_specs') as probe:
            self.assertEqual(resolve_options(options), options)
            probe.assert_not_called()
        options['quality_mode'] = 'auto'
        with patch('karaoke.audio_auto.machine_specs', side_effect=[self.specs(), self.specs(4,4,1)]):
            a, b = resolve_options(options), resolve_options(options)
        self.assertEqual(a['quality'], 2)
        self.assertEqual(b['quality'], 0)
        self.assertEqual(options['voices'], 1024)
        self.assertEqual(b['effects_mode'], options['effects_mode'])

    def test_mode_roundtrip_and_legacy_preserved(self):
        self.assertEqual(normalize_audio({})['quality_mode'], 'manual')
        a = normalize_audio({'soundfont_audio': {'quality_mode':'auto'}})
        self.assertEqual(normalize_audio({'soundfont_audio':a})['quality_mode'], 'auto')

    def test_windows_memory_abi_and_failure(self):
        self.assertEqual(ctypes.sizeof(MemoryStatus), 64)
        fn = Mock()
        def fill(ptr):
            ptr._obj.total = 16*GIB
            ptr._obj.available = 6*GIB
            self.assertEqual(ptr._obj.length, 64)
            return 1
        fn.side_effect = fill
        kernel = Mock(GlobalMemoryStatusEx=fn)
        with patch('karaoke.audio_auto.os.name', 'nt'), patch('ctypes.WinDLL', return_value=kernel, create=True):
            self.assertEqual(machine_specs()['available'], 6*GIB)
            fn.side_effect = lambda ptr: 0
            self.assertEqual(machine_specs()['total'], 0)

    def test_dialog_auto_toggle_and_manual_profile(self):
        from karaoke.audio_dialog import AudioSettings
        class Var:
            def __init__(self, v): self.v = v
            def get(self): return self.v
            def set(self, v): self.v = v
        dialog = AudioSettings.__new__(AudioSettings)
        dialog.quality_mode = Var('auto')
        dialog.quality, dialog.voices, dialog.buffer_ms = Var('2'), Var('512'), Var('80')
        dialog.auto_detail = Var('')
        dialog.fonts = []
        dialog.quality_controls = [Mock()]
        with patch('karaoke.audio_auto.machine_specs', return_value=self.specs()):
            dialog.update_auto()
        self.assertEqual(dialog.buffer_ms.get(), '100')
        dialog.quality_controls[0].configure.assert_called_with(state='disabled')
        dialog.profile('light')
        self.assertEqual(dialog.quality_mode.get(), 'manual')
        dialog.quality_controls[0].configure.assert_called_with(state='readonly')


    def test_auto_values_reach_native_synth(self):
        from test_soundfont import SoundFontTests
        from soundfont_fixture import make_font
        from karaoke.bass import BassSynth, BASS_ATTRIB_MIDI_SRC, BASS_ATTRIB_MIDI_VOICES, BASS_ATTRIB_BUFFER
        with tempfile.TemporaryDirectory() as folder:
            path = make_font(Path(folder)/'test.sf2')
            dll, midi = SoundFontTests().fake_api()
            with patch('karaoke.audio_auto.machine_specs', return_value=self.specs(2,4,1)):
                synth = BassSynth(Path(folder), settings={'soundfont': str(path),
                    'soundfont_audio': {'quality_mode':'auto'}}, bindings=(dll,midi))
            dll.BASS_ChannelSetAttribute.assert_any_call(50, BASS_ATTRIB_MIDI_SRC, 0)
            dll.BASS_ChannelSetAttribute.assert_any_call(50, BASS_ATTRIB_MIDI_VOICES, 128)
            dll.BASS_ChannelSetAttribute.assert_any_call(50, BASS_ATTRIB_BUFFER, .2)
            synth.close()
