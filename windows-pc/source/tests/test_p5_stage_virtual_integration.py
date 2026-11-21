"""P5 no-hardware integration checks for existing canvas and virtual screens."""
import unittest
from karaoke.lyrics import Lyrics, LyricLine
from karaoke.ui import LyricsCanvas
from karaoke.stage import StageCanvas
from karaoke.virtual_lyric_display import VirtualDisplay, render_layout


class FakeCanvas:
    show_timeline = LyricsCanvas.show_timeline

    def __init__(self):
        self.extra_lines = ()
        self.state = ()
        self.paints = 0

    def show(self, *state):
        if self.state != state:
            self.state = state
            self.redraw()

    def redraw(self):
        self.paints += 1


class FakeStage:
    show_frame = StageCanvas.show_frame

    def __init__(self):
        self.extra_lines = ("stale",)
        self.paints = 0

    def redraw(self):
        self.paints += 1


class StageVirtualIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.lyrics = Lyrics([LyricLine(float(i), "line %s" % i) for i in range(5)])

    def test_timed_canvas_3_and_4_lines_and_stable_repaint(self):
        canvas = FakeCanvas()
        canvas.show_timeline(self.lyrics, 1.1, line_count=3)
        self.assertEqual(canvas.state[:2], ("line 1", "line 2"))
        self.assertEqual(canvas.extra_lines, ("line 3",))
        paints = canvas.paints
        canvas.show_timeline(self.lyrics, 1.1, line_count=3)
        self.assertEqual(canvas.paints, paints)
        canvas.show_timeline(self.lyrics, 1.1, line_count=4)
        self.assertEqual(canvas.extra_lines, ("line 3", "line 4"))

    def test_legacy_stage_clears_multiline_on_song_change(self):
        stage = FakeStage()
        stage.show_frame("current", "next", "cur", "title")
        self.assertEqual(stage.extra_lines, ())
        self.assertEqual(stage.state, ("current", "next", "cur", "title"))
        self.assertEqual(stage.paints, 1)

    def test_virtual_secondary_monitor_and_resize(self):
        for count in (2, 3, 4):
            frames = render_layout(self.lyrics, 1.1,
                [VirtualDisplay(640, 480), VirtualDisplay(1920, 1080, -1920, 0)],
                line_count=count)
            self.assertEqual(len(frames), 2)
            self.assertEqual(frames[0].line_texts, frames[1].line_texts)
            self.assertLess(frames[1].bounds[0], 0)
            for frame in frames:
                x, y, w, h = frame.bounds
                self.assertLessEqual(x + w, frame.display.x + frame.display.width)
                self.assertLessEqual(y + h, frame.display.y + frame.display.height)


if __name__ == "__main__":
    unittest.main()
