"""P5 lyric viewport simulation contracts (no monitor required)."""
import unittest
from karaoke.lyrics import LyricLine, Lyrics
from karaoke.lyric_viewport import viewport


class LyricViewportTests(unittest.TestCase):
    def setUp(self):
        self.lyrics = Lyrics([LyricLine(i, "line " + str(i),
                          [(float(i), "line "), (i + .5, str(i))]) for i in range(6)])

    def test_two_three_four_lines(self):
        for count in (2, 3, 4):
            with self.subTest(count=count):
                view = viewport(self.lyrics, 2.6, line_count=count)
                self.assertEqual(len(view.lines), count)
                self.assertEqual(view.lines[0].text, "line 2")
                self.assertEqual(view.active_index, 0)
                self.assertEqual(view.highlighted_prefix, "line 2")

    def test_before_first_and_after_last(self):
        early = viewport(self.lyrics, -1, line_count=4)
        self.assertEqual(early.active_index, -1)
        self.assertEqual(len(early.lines), 4)
        late = viewport(self.lyrics, 5.5, line_count=4)
        self.assertEqual([line.text for line in late.lines], ["line 5"])

    def test_offset_and_empty_timeline(self):
        self.assertEqual(viewport(self.lyrics, 1.6, offset_ms=1000).lines[0].text, "line 2")
        self.assertEqual(viewport(Lyrics(), 0).lines, ())

    def test_reject_invalid_inputs(self):
        for count in (1, 5, True):
            with self.assertRaises(ValueError):
                viewport(self.lyrics, 1, line_count=count)
        with self.assertRaises(ValueError):
            viewport(self.lyrics, float("nan"))
        with self.assertRaises(ValueError):
            viewport(self.lyrics, 1, offset_ms=True)


if __name__ == "__main__":
    unittest.main()
