"""P5 real-codec Windows CI simulation: encoded AVI -> RGB24 -> chroma display.

Uses an actual OpenCV VideoCapture/VideoWriter and a virtual MCI time source.
No physical camera, audio device, desktop or Windows MCI call is required.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from karaoke.chroma_key import composite_rgb24, ChromaKey
from karaoke.chroma_video_renderer import VideoFrame
from karaoke.opencv_frame_source import OpenCVFrameSource, MCIChromaPreview
from karaoke.virtual_lyric_display import VirtualDisplay


class FakeMCI:
    opened = True
    has_video = True
    position = 0.0

    def __init__(self):
        self.controls_called = []

    def play(self):
        self.controls_called.append("play")

    def pause(self):
        self.controls_called.append("pause")

    def set_window(self, handle):
        self.controls_called.append("set_window")


class RealCodecSimulationTests(unittest.TestCase):
    def test_encoded_moving_video_and_mci_clock(self):
        import cv2
        import numpy as np

        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "chroma-example.avi")
            writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 10, (320, 240))
            self.assertTrue(writer.isOpened(), "CI runner cannot create an MJPG AVI")
            try:
                for n in range(8):
                    bgr = np.empty((240, 320, 3), dtype=np.uint8)
                    bgr[:] = (0, 255, 0)
                    x = 30 + n * 25
                    cv2.rectangle(bgr, (x, 80), (x + 25, 110), (0, 0, 255), -1)
                    writer.write(bgr)
            finally:
                writer.release()

            mci = FakeMCI()
            background = VideoFrame(320, 240, bytes((9, 19, 39)) * 320 * 240)
            with OpenCVFrameSource(path).open() as source:
                self.assertAlmostEqual(source.fps, 10, delta=0.1)
                preview = MCIChromaPreview(mci, source, background)
                first = preview.render_virtual(VirtualDisplay(320, 240))
                self.assertEqual(first.rgb24[3 * (200 * 320 + 300): 3 * (200 * 320 + 300) + 3],
                                 bytes((9, 19, 39)))
                self.assertGreater(first.rgb24[3 * (90 * 320 + 40)], 170)
                mci.position = 0.4
                later = preview.render_virtual(VirtualDisplay(320, 240))
                self.assertNotEqual(first.rgb24, later.rgb24)
                repeated = source.read_frame(0.4)
                self.assertIs(repeated, source.read_frame(0.4))
                self.assertEqual(mci.controls_called, [])
                mci.opened = False
                self.assertIsNone(preview.render_virtual(VirtualDisplay(320, 240)))
            self.assertIsNone(source.capture)

    def test_native_compositor_matches_pure_python_fallback(self):
        foreground = bytes((0, 255, 0, 255, 0, 0, 30, 225, 30, 40, 150, 30))
        background = bytes((12, 30, 90)) * 4
        key = ChromaKey(rgb=(0, 255, 0), tolerance=30)
        native = composite_rgb24(foreground, background, 4, 1, key=key)
        with patch.dict(sys.modules, {"cv2": None, "numpy": None}):
            pure_python = composite_rgb24(foreground, background, 4, 1, key=key)
        self.assertEqual(native, pure_python)
        self.assertEqual(native, bytes((12, 30, 90, 255, 0, 0, 12, 30, 90, 40, 150, 30)))

    def test_missing_decoder_does_not_touch_fake_mci_transport(self):
        mci = FakeMCI()
        with self.assertRaises(OSError):
            OpenCVFrameSource("definitely-missing-chroma-file.avi").open()
        self.assertEqual(mci.controls_called, [])


if __name__ == "__main__":
    unittest.main()
