"""End-to-end P5 frame-source simulation without physical video devices."""
import unittest
from karaoke.chroma_frame_source import SimulatedVideoSource, ChromaFramePipeline
from karaoke.chroma_video_renderer import VideoFrame
from karaoke.virtual_lyric_display import VirtualDisplay


class ChromaFramePipelineTests(unittest.TestCase):
    def test_moving_decoded_frames_are_composited(self):
        source = SimulatedVideoSource(2, 1)
        background = VideoFrame(2, 1, bytes([10, 20, 30] * 2))
        pipeline = ChromaFramePipeline(source, background)
        first = pipeline.next_frame()
        second = pipeline.next_frame()
        self.assertEqual(first.rgb24, bytes([255, 0, 0, 10, 20, 30]))
        self.assertEqual(second.rgb24, bytes([10, 20, 30, 255, 0, 0]))
        self.assertEqual(source.index, 2)

    def test_virtual_monitor_frame_output(self):
        source = SimulatedVideoSource(2, 1)
        pipeline = ChromaFramePipeline(source, VideoFrame(2, 1, bytes([1, 2, 3] * 2)))
        for screen in (VirtualDisplay(320, 240), VirtualDisplay(1920, 1080, -1920, 0)):
            frame = pipeline.preview(screen)
            self.assertEqual((frame.width, frame.height), (screen.width, screen.height))
            self.assertEqual(len(frame.rgb24), screen.width * screen.height * 3)

    def test_rejects_bad_source(self):
        with self.assertRaises(ValueError):
            ChromaFramePipeline(object(), VideoFrame(1, 1, b"abc"))
        with self.assertRaises(ValueError):
            SimulatedVideoSource(0, 2)


if __name__ == "__main__":
    unittest.main()
