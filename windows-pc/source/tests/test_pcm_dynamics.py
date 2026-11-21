"""Stereo PCM safety limiter contracts; execution deferred until consolidated QA."""
import math
import struct
import unittest

from karaoke.pcm_dynamics import StereoPeakLimiter


class LimiterTests(unittest.TestCase):
    def test_interleaved_stereo_peak_is_bounded(self):
        limiter = StereoPeakLimiter(ceiling=.95)
        raw = struct.pack('<6f', 1.5, -1.5, .5, -.5, .25, -.25)
        output = struct.unpack('<6f', limiter.process(raw))
        self.assertLessEqual(max(map(abs, output)), .95001)
        self.assertAlmostEqual(output[0], -output[1], places=5)
        self.assertAlmostEqual(output[2], -output[3], places=5)
        self.assertEqual(len(limiter.process(b'')), 0)
        self.assertGreater(limiter.reduced_blocks, 0)

    def test_nonfinite_input_is_replaced_by_silence(self):
        limiter = StereoPeakLimiter()
        data = struct.pack('<4f', math.nan, math.inf, .2, -.2)
        out = struct.unpack('<4f', limiter.process(data))
        self.assertEqual(out[:2], (0., 0.))
        self.assertAlmostEqual(out[2], .2, places=5)

    def test_invalid_frames_and_options_rejected(self):
        with self.assertRaises(ValueError):
            StereoPeakLimiter(ceiling=1.5)
        with self.assertRaises(ValueError):
            StereoPeakLimiter(release_step=math.nan)
        with self.assertRaises(ValueError):
            StereoPeakLimiter().process(b'bad')


if __name__ == '__main__':
    unittest.main()
