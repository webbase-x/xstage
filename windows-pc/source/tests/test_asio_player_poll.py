"""ASIO failover polling integrates with the MIDI scheduler, without hardware."""
from types import SimpleNamespace
import unittest

from karaoke.playback import MidiPlayer


class Output:
    def __init__(self):
        self.polls = 0
        self.sent = []
    def poll(self):
        self.polls += 1
    def send(self, data):
        self.sent.append(data)
    def reset(self):
        pass
    def close(self):
        pass


class MidiAudioHealthTests(unittest.TestCase):
    def test_play_and_pump_poll_output(self):
        output = Output()
        now = [2.0]
        player = MidiPlayer(output=output, clock=lambda: now[0])
        player.song = SimpleNamespace(events=[], duration=20)
        player.duration = 20
        player.play()
        self.assertEqual(output.polls, 1)
        now[0] += .05
        player.pump()
        self.assertEqual(output.polls, 2)
        player.pause()
        player.pump()
        self.assertEqual(output.polls, 2)


if __name__ == '__main__':
    unittest.main()
