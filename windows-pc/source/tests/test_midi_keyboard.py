import unittest
from unittest.mock import Mock
from karaoke.midi_keyboard import NoteMonitor,note_name
from karaoke.playback import MidiPlayer

class KeyboardTests(unittest.TestCase):
    def test_sustain_velocity_zero_and_channel_isolation(self):
        m=NoteMonitor()
        for event in ([0x90,60,90],[0x91,64,80],[0xb0,64,127],[0x90,60,0]):m.feed(bytes(event))
        self.assertEqual(m.snapshot(),{60,64})
        m.feed(bytes([0xb0,64,0]));self.assertEqual(m.snapshot(0),set())
        self.assertEqual(m.snapshot(1),{64})
    def test_controller_reset_and_all_sound_off(self):
        m=NoteMonitor()
        for event in ([0x90,60,90],[0xb0,64,127],[0x80,60,0],[0xb0,121,0]):m.feed(bytes(event))
        self.assertFalse(m.snapshot())
        m.feed(bytes([0x90,64,90]));m.feed(bytes([0xb0,120,0]));self.assertFalse(m.snapshot())
    def test_output_transpose_drums_mute_and_pause(self):
        p=MidiPlayer(output=Mock());p.set_key(2)
        p._send(bytes([0x90,60,90]));p._send(bytes([0x99,36,90]))
        self.assertEqual(p.note_monitor.snapshot(),{62,36})
        p.set_channel(0,muted=True);self.assertEqual(p.note_monitor.snapshot(),{36})
        p.pause();self.assertFalse(p.note_monitor.snapshot())
    def test_output_failure_does_not_light_note(self):
        output=Mock();output.send.side_effect=OSError('device')
        p=MidiPlayer(output=output)
        with self.assertRaises(OSError):p._send(bytes([0x90,60,90]))
        self.assertFalse(p.note_monitor.snapshot())
    def test_names_and_reset(self):
        self.assertEqual(note_name(60),'C4')
        m=NoteMonitor();m.feed(bytes([0x90,127,1]));m.reset();self.assertFalse(m.snapshot())

    def test_full_keyboard_fits_small_and_large_widths(self):
        from karaoke.midi_keyboard import keyboard_geometry
        for width in (320,800,1366,1920,3840):
            white,black=keyboard_geometry(width,160)
            self.assertEqual({r[0] for r in white+black},set(range(128)))
            self.assertAlmostEqual(white[0][1],0)
            self.assertAlmostEqual(white[-1][3],width)
            for _,x1,y1,x2,y2 in white+black:
                self.assertGreaterEqual(x1,0);self.assertLessEqual(x2,width+.0001)
                self.assertLess(x1,x2);self.assertLessEqual(y2,160)

    def test_61_keys_default_range_and_octave_limits(self):
        from karaoke.midi_keyboard import keyboard_geometry
        white,black=keyboard_geometry(900,140,61,36)
        notes={r[0] for r in white+black}
        self.assertEqual(notes,set(range(36,97)))
        self.assertEqual(note_name(min(notes)),'C2')
        self.assertEqual(note_name(max(notes)),'C7')
        for start in (-12,0,12,60,72):
            white,black=keyboard_geometry(800,140,61,start)
            self.assertEqual(len(white+black),61)
            self.assertTrue(all(0<=r[0]<=127 and 0<=r[1]<r[3]<=800.00001 for r in white+black))
        white,black=keyboard_geometry(800,140,128,36)
        self.assertEqual({r[0] for r in white+black},set(range(128)))
