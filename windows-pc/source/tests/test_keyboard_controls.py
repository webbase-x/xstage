import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from karaoke.keyboard_controls import PreviewVoice,fx_file,hit_note
from karaoke.midi_keyboard import keyboard_geometry

class KeyboardControlsTests(unittest.TestCase):
    def test_fx_numbers_extension_case_and_wav_priority(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'01.MP3').touch();(p/'01.wav').touch();(p/'10.WAV').touch()
            self.assertEqual(fx_file(p,1).name,'01.wav')
            self.assertEqual(fx_file(p,10).name,'10.WAV')
            with self.assertRaises(ValueError):fx_file(p,2)
            with self.assertRaises(ValueError):fx_file(p,11)
    def test_press_release_and_instrument_change_send_correct_midi(self):
        out=Mock();voice=PreviewVoice(lambda:out)
        voice.press(60);voice.press(60)
        self.assertEqual([c.args[0] for c in out.send.call_args_list].count(bytes([0x90,60,96])),1)
        voice.select(40)
        self.assertEqual(out.send.call_args_list[-2].args[0],bytes([0x80,60,0]))
        self.assertEqual(out.send.call_args_list[-1].args[0],bytes([0xc0,40]))
        voice.press(64);voice.close();self.assertFalse(voice.notes);out.close.assert_called_once()
    def test_black_keys_win_hit_test_and_lower_white_key_is_natural(self):
        geometry=keyboard_geometry(1500,150)
        black=geometry[1][0];n,x1,y1,x2,y2=black
        self.assertEqual(hit_note(geometry,(x1+x2)/2,20),n)
        self.assertNotEqual(hit_note(geometry,(x1+x2)/2,130),n)
        self.assertIsNone(hit_note(geometry,-1,20))
    def test_no_midi_event_on_invalid_note(self):
        out=Mock();voice=PreviewVoice(lambda:out)
        with self.assertRaises(ValueError):voice.press(128)
        out.send.assert_not_called()

    def test_f4_pins_open_then_hides(self):
        from types import SimpleNamespace
        from karaoke.performer import PlaybackApp
        panel=Mock();panel.winfo_exists.return_value=True;panel.winfo_ismapped.return_value=False
        app=SimpleNamespace(_midi_keyboard_window=panel,open_midi_keyboard=Mock())
        PlaybackApp.toggle_midi_keyboard(app)
        app.open_midi_keyboard.assert_called_once()
        self.assertTrue(panel._keyboard_pinned)
        panel.winfo_ismapped.return_value=True
        PlaybackApp.toggle_midi_keyboard(app)
        panel._keyboard_hide.assert_called_once()
