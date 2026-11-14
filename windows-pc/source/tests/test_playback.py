import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from karaoke.playback import MidiPlayer
from karaoke.smf import MidiSong, MidiEvent
from karaoke.lyrics import Lyrics


class Output:
    def __init__(self):
        self.sent = []
        self.resets = 0
        self.closed = False
    def send(self, value):
        self.sent.append(value)
    def reset(self):
        self.resets += 1
    def close(self):
        self.closed = True


class PlaybackTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.output = Output()
        self.player = MidiPlayer(self.output, lambda: self.now)
        self.player.song = MidiSong([MidiEvent(0, b"\xc0\x05"), MidiEvent(0.5, b"\x90\x3c\x64"),
                                    MidiEvent(1, b"\x80\x3c\x00")], 2, Lyrics())
        self.player.duration = 2
        self.player.times = [0, 0.5, 1]

    def test_clock_pause_speed_no_time_jump(self):
        p = self.player
        p.play()
        self.now += 0.25
        p.set_speed(1.5)
        self.assertAlmostEqual(p.position, 0.25)
        self.now += 0.5
        self.assertAlmostEqual(p.position, 1)
        p.pause()
        self.now += 50
        self.assertAlmostEqual(p.position, 1)
        p.play()
        self.now += 0.2
        self.assertAlmostEqual(p.position, 1.3)

    def test_transpose_except_percussion_and_out_of_range(self):
        p = self.player
        p.set_key(3)
        p._send(b"\x90\x3c\x64")
        p._send(b"\x99\x3c\x64")
        p._send(b"\x90\x7f\x64")
        self.assertEqual(self.output.sent, [b"\x90\x3f\x64", b"\x99\x3c\x64"])

    def test_muting_stops_notes_immediately(self):
        p = self.player
        p.set_channel(3, muted=True)
        self.assertIn(b"\xb3\x78\x00", self.output.sent)
        self.output.sent.clear()
        p._send(b"\x93\x3c\x64")
        self.assertEqual(self.output.sent, [])

    def test_channel_volume_respects_file_master_and_gain(self):
        p = self.player
        p.set_volume(0.5)
        p.set_channel(0, gain=0.5)
        p._send(b"\xb0\x07\x64")
        self.assertEqual(self.output.sent[-1], bytes([0xB0, 7, 25]))

    def test_seek_restores_instrument_but_not_old_notes(self):
        p = self.player
        p.seek(0.75)
        self.assertIn(b"\xc0\x05", self.output.sent)
        self.assertFalse(any(value[0] & 0xF0 == 0x90 for value in self.output.sent))
        self.assertEqual(p.cursor, 2)

    def test_finish_is_reported_once_and_notes_reset(self):
        p = self.player
        p.play()
        self.now += 3
        p.pump()
        self.assertTrue(p.ended)
        self.assertFalse(p.playing)
        self.assertEqual(p.position, 2)
        self.assertGreater(self.output.resets, 0)
        p.ended = False
        p.pump()
        self.assertFalse(p.ended)

    def test_stop_and_restart(self):
        p = self.player
        p.play()
        self.now += 1
        p.pump()
        p.stop()
        self.assertEqual(p.position, 0)
        p.play()
        p.pump()
        self.assertEqual(p.cursor, 1)
        p.close()
        self.assertTrue(self.output.closed)


if __name__ == "__main__":
    unittest.main()
