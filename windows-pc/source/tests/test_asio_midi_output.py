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

    def test_partial_pcm_push_resends_remaining_frames_in_order(self):
        class SequentialSynth(FakeSynth):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.next_frame = 0
            def render(self, frames):
                first = self.next_frame
                self.next_frame += frames
                return b''.join(n.to_bytes(8, 'little') for n in
                                range(first, first + frames))

        class PartialOutput(FakeOutput):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.accepted_frames = []
            def push(self, pcm):
                self.accepted_frames.append(int.from_bytes(pcm[:8], 'little'))
                return 1

        output = AsioMidiOutput('unused', device=0, synth_factory=SequentialSynth,
                                output_factory=PartialOutput, chunk_frames=4,
                                target_frames=4)
        sink = output.output
        try:
            for _ in range(200):
                if len(sink.accepted_frames) >= 4:
                    break
                time.sleep(.002)
            self.assertGreaterEqual(len(sink.accepted_frames), 4)
            self.assertEqual(sink.accepted_frames[:4], [0, 1, 2, 3])
        finally:
            output.close()

    def test_rejects_invalid_target(self):
        with self.assertRaises(ValueError):
            AsioMidiOutput('unused', device=0, chunk_frames=24, target_frames=12)


if __name__ == '__main__':
    unittest.main()
