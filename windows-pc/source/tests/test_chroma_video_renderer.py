"""P5 virtual RGB video renderer contracts; no physical monitor or Tk root."""
import unittest
from karaoke.chroma_key import ChromaKey
from karaoke.chroma_video_renderer import ChromaVideoRenderer, VideoFrame
from karaoke.virtual_lyric_display import VirtualDisplay


class ChromaVideoRendererTests(unittest.TestCase):
    def test_composites_green_and_preserves_opaque_pixels(self):
        renderer = ChromaVideoRenderer(ChromaKey(rgb=(0, 255, 0), tolerance=0))
        front = VideoFrame(2, 1, bytes([0, 255, 0, 255, 0, 0]))
        back = VideoFrame(2, 1, bytes([5, 10, 15, 20, 25, 30]))
        result = renderer.composite(front, back)
        self.assertEqual(result.rgb24, bytes([5, 10, 15, 255, 0, 0]))

    def test_virtual_resize_two_monitors(self):
        renderer = ChromaVideoRenderer()
        front = VideoFrame(1, 1, bytes([0, 255, 0]))
        back = VideoFrame(1, 1, bytes([12, 34, 56]))
        for display in (VirtualDisplay(320, 240), VirtualDisplay(1920, 1080, -1920, 0)):
            result = renderer.preview(front, back, display)
            self.assertEqual((result.width, result.height), (display.width, display.height))
            self.assertEqual(result.rgb24[:3], bytes([12, 34, 56]))
            self.assertEqual(result.rgb24[-3:], bytes([12, 34, 56]))

    def test_rejects_mismatched_frames_and_bad_bytes(self):
        renderer = ChromaVideoRenderer()
        with self.assertRaises(ValueError):
            VideoFrame(2, 1, b"abc")
        with self.assertRaises(ValueError):
            renderer.composite(VideoFrame(1, 1, b"abc"),
                               VideoFrame(2, 1, b"abcdef"))


if __name__ == "__main__":
    unittest.main()
