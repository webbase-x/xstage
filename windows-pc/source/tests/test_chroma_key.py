"""P5 deterministic virtual-display chroma-key regression tests."""
import unittest
from karaoke.chroma_key import ChromaKey, composite_rgb24


class ChromaKeyTests(unittest.TestCase):
    def test_green_pixels_reveal_background(self):
        front = bytes([0, 255, 0, 255, 0, 0])
        back = bytes([20, 30, 40, 50, 60, 70])
        self.assertEqual(composite_rgb24(front, back, 2, 1),
                         bytes([20, 30, 40, 255, 0, 0]))

    def test_tolerance_boundary_and_custom_key(self):
        front = bytes([5, 245, 10, 11, 240, 10])
        back = bytes([1, 2, 3, 4, 5, 6])
        self.assertEqual(composite_rgb24(front, back, 2, 1, key=ChromaKey(tolerance=10)),
                         bytes([1, 2, 3, 11, 240, 10]))
        self.assertEqual(composite_rgb24(bytes([0, 0, 255]), bytes([1, 2, 3]), 1, 1,
                                         key=ChromaKey((0, 0, 255), 0)), bytes([1, 2, 3]))

    def test_rejects_invalid_dimensions_frames_and_key(self):
        with self.assertRaises(ValueError):
            composite_rgb24(b"", b"", 0, 1)
        with self.assertRaises(ValueError):
            composite_rgb24(b"abc", b"", 1, 1)
        with self.assertRaises(ValueError):
            ChromaKey(tolerance=-1)
        with self.assertRaises(ValueError):
            ChromaKey((0, True, 0), 0)


if __name__ == "__main__":
    unittest.main()
