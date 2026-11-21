"""Windows-safe simulated decoder and MCI-clock chroma integration tests.

No webcam, physical monitor, OpenCV installation or audio device required.
"""
import unittest
from karaoke.opencv_frame_source import OpenCVFrameSource, MCIChromaPreview
from karaoke.chroma_video_renderer import VideoFrame
from karaoke.virtual_lyric_display import VirtualDisplay


class FakeBGR:
    ndim = 3
    shape = (1, 2, 3)

    def __getitem__(self, key):
        assert key == (slice(None), slice(None), slice(None, None, -1))
        return self

    def tobytes(self):
        return bytes((0, 255, 0, 255, 0, 0))


class FakeCapture:
    def __init__(self, path):
        self.path = path
        self.released = False
        self.seeks = []
        self.reads = 0

    def isOpened(self):
        return True

    def seek_seconds(self, seconds):
        self.seeks.append(seconds)

    def read(self):
        self.reads += 1
        return True, FakeBGR()

    def release(self):
        self.released = True


class FakePlayer:
    opened = True
    has_video = True
    position = 1.25


class OpenCVFrameSourceTests(unittest.TestCase):
    def test_simulated_bgr_decoder_to_rgb24_and_close(self):
        capture = FakeCapture("video.mp4")
        source = OpenCVFrameSource("video.mp4", capture_factory=lambda _: capture)
        with source:
            frame = source.read_frame(1.25)
            self.assertEqual((frame.width, frame.height), (2, 1))
            self.assertEqual(frame.rgb24, bytes((0, 255, 0, 255, 0, 0)))
            self.assertEqual(capture.seeks, [1.25])
        self.assertTrue(capture.released)

    def test_mci_clock_drives_chroma_virtual_preview_without_touching_transport(self):
        player = FakePlayer()
        capture = FakeCapture("video.mp4")
        source = OpenCVFrameSource("video.mp4", capture_factory=lambda _: capture)
        background = VideoFrame(2, 1, bytes((7, 8, 9, 10, 11, 12)))
        with source:
            bridge = MCIChromaPreview(player, source, background)
            result = bridge.render_virtual(VirtualDisplay(320, 240))
        self.assertEqual((result.width, result.height), (320, 240))
        self.assertEqual(result.rgb24[:3], bytes((7, 8, 9)))
        self.assertEqual(capture.seeks, [1.25])
        self.assertEqual(capture.reads, 1)
        self.assertEqual(player.position, 1.25)

    def test_closed_mci_does_not_decode(self):
        player = FakePlayer()
        player.opened = False
        capture = FakeCapture("video.mp4")
        source = OpenCVFrameSource("video.mp4", capture_factory=lambda _: capture)
        with source:
            bridge = MCIChromaPreview(player, source, VideoFrame(2, 1, bytes(6)))
            self.assertIsNone(bridge.render_virtual(VirtualDisplay(320, 240)))
        self.assertEqual(capture.reads, 0)

    def test_paused_mci_clock_reuses_last_rgb_frame(self):
        class FakeCV:
            CAP_PROP_POS_MSEC = 1
        class TimedCapture(FakeCapture):
            def set(self, prop, value):
                self.seeks.append((prop, value))
                return True
        capture = TimedCapture("video.mp4")
        source = OpenCVFrameSource("video.mp4", capture_factory=lambda _: capture)
        with source:
            source.cv2 = FakeCV()
            source.fps = 30
            first = source.read_frame(1.25)
            second = source.read_frame(1.25)
            self.assertIs(first, second)
            self.assertEqual(capture.reads, 1)
            self.assertEqual(capture.seeks, [(1, 1250.0)])
            source.read_frame(1.30)
            self.assertEqual(capture.reads, 2)
        self.assertIsNone(source.last_frame)

    def test_invalid_clock_is_rejected(self):
        source = OpenCVFrameSource("video.mp4", capture_factory=FakeCapture)
        with source:
            with self.assertRaises(ValueError):
                source.read_frame(-1)


if __name__ == "__main__":
    unittest.main()
