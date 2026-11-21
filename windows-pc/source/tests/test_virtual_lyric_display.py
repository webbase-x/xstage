"""P5 virtual display sizing and multi-monitor lyric tests."""
import unittest
from karaoke.lyrics import Lyrics, LyricLine
from karaoke.virtual_lyric_display import VirtualDisplay, render_layout


class VirtualLyricDisplayTests(unittest.TestCase):
    def setUp(self):
        self.lyrics = Lyrics([LyricLine(0., "one"), LyricLine(1., "two"),
                              LyricLine(2., "three"), LyricLine(3., "four")])

    def test_two_independent_display_bounds_and_scaled_fonts(self):
        displays = (VirtualDisplay(640, 480), VirtualDisplay(1920, 1080, 640, 0))
        frames = render_layout(self.lyrics, 1.2, displays, line_count=3)
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0].line_texts, ("two", "three", "four"))
        self.assertEqual(frames[0].active_index, 0)
        self.assertGreater(frames[1].font_pixels, frames[0].font_pixels)
        self.assertGreaterEqual(frames[1].bounds[0], 640)
        for frame in frames:
            x, y, w, h = frame.bounds
            self.assertGreaterEqual(x, frame.display.x)
            self.assertGreaterEqual(y, frame.display.y)
            self.assertLessEqual(x + w, frame.display.x + frame.display.width)
            self.assertLessEqual(y + h, frame.display.y + frame.display.height)

    def test_empty_lyrics_and_all_supported_line_counts(self):
        for lines in (2, 3, 4):
            frame, = render_layout(Lyrics(), 0, [VirtualDisplay(320, 240)], line_count=lines)
            self.assertEqual(frame.line_texts, ())
            self.assertEqual(frame.active_index, -1)

    def test_invalid_virtual_displays_fail_closed(self):
        with self.assertRaises(ValueError):
            VirtualDisplay(0, 480)
        with self.assertRaises(ValueError):
            render_layout(self.lyrics, 0, [])
        with self.assertRaises(ValueError):
            render_layout(self.lyrics, 0, [object()])


if __name__ == "__main__":
    unittest.main()
