"""Mock-only ASIO MIDI producer contracts; no real sound device."""
import time
import unittest

from karaoke.asio_midi_output import AsioMidiOutput


class FakeSynth:
    def __init__(self, native, settings=None, decode=False):
        assert decode is True
        self.closed = False
        self.calls = 0

    def render(self, frames):
        self.calls += 1
        return bytes(frames * 8)

    def send(self, data):
        return len(data)

    def reset(self):
        return None

    def close(self):
        self.closed = True


class FakeBridge:
    def __init__(self):
        self.frames = 0

    def buffered_frames(self):
        return self.frames


class FakeOutput:
    def __init__(self, native, device, channel):
        self.bridge = FakeBridge()
        self.closed = False

    def push(self, pcm):
        frames = len(pcm) // 8
        self.bridge.frames += frames
        return frames

    def close(self):
        self.closed = True


class AsioMidiOutputTests(unittest.TestCase):
    def test_producer_stops_at_target_and_closes(self):
        output = AsioMidiOutput('unused', device=0, synth_factory=FakeSynth,
                                output_factory=FakeOutput, chunk_frames=24,
                                target_frames=48)
        synth, sink = output.synth, output.output
        try:
            for _ in range(100):
                if sink.bridge.frames >= 48:
                    break
                time.sleep(.002)
            self.assertEqual(sink.bridge.frames, 48)
            self.assertEqual(output.send(b'abc'), 3)
            self.assertIsNone(output.reset())
        finally:
            output.close()
        self.assertTrue(synth.closed)
        self.assertTrue(sink.closed)

    def test_rejects_invalid_target(self):
        with self.assertRaises(ValueError):
            AsioMidiOutput('unused', device=0, chunk_frames=24, target_frames=12)


if __name__ == '__main__':
    unittest.main()
