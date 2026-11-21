"""Optional OpenCV RGB24 frame decoder synchronized to the existing MCI clock.

This is a *secondary* video-frame reader: MCI remains the sole audio/video
transport. No replacement player, audio output or codec installation occurs.
OpenCV is imported only when the opt-in reader is opened.
"""
from pathlib import Path
import math

from .chroma_video_renderer import VideoFrame


class OpenCVFrameSource:
    def __init__(self, path, capture_factory=None):
        self.path = Path(path)
        self.capture_factory = capture_factory
        self.capture = None
        self.cv2 = None
        self.fps = 0.0
        self.last_index = None

    def open(self):
        if self.capture is not None:
            return self
        if self.capture_factory is None:
            try:
                import cv2
            except ImportError as error:
                raise RuntimeError("OpenCV unavailable; keep native MCI video") from error
            self.cv2 = cv2
            factory = cv2.VideoCapture
        else:
            factory = self.capture_factory
        capture = factory(str(self.path))
        if capture is None or not capture.isOpened():
            if capture is not None:
                capture.release()
            raise OSError("Unable to open secondary video decoder")
        self.capture = capture
        if self.cv2 is not None:
            fps = float(capture.get(self.cv2.CAP_PROP_FPS))
            self.fps = fps if math.isfinite(fps) and fps > 0 else 0.0
        return self

    def read_frame(self, seconds=None):
        if self.capture is None:
            raise RuntimeError("Frame source is not open")
        if seconds is not None:
            if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
                raise ValueError("Invalid playback position")
            if self.cv2 is None:
                # Test doubles may implement seek_seconds; production uses OpenCV.
                if hasattr(self.capture, "seek_seconds"):
                    self.capture.seek_seconds(float(seconds))
            else:
                index = int(float(seconds) * self.fps) if self.fps else None
                if index is None or index != self.last_index:
                    self.capture.set(self.cv2.CAP_PROP_POS_MSEC, float(seconds) * 1000)
                    self.last_index = index
                else:
                    return None  # Do not decode/repaint the same timed frame.
        success, bgr = self.capture.read()
        if not success or bgr is None:
            return None
        # OpenCV returns BGR arrays. Flip the channel order without assuming
        # contiguous strides; NumPy's tobytes() normalizes the output.
        if getattr(bgr, "ndim", 0) != 3 or bgr.shape[2] != 3:
            raise ValueError("Decoder did not return a BGR24 image")
        height, width = bgr.shape[:2]
        return VideoFrame(width, height, bgr[:, :, ::-1].tobytes())

    def close(self):
        capture, self.capture = self.capture, None
        self.last_index = None
        if capture is not None:
            capture.release()

    def __enter__(self):
        return self.open()

    def __exit__(self, *_):
        self.close()


class MCIChromaPreview:
    """Optional video-only bridge. Native MCI continues playback and audio."""

    def __init__(self, mci_player, frame_source, background, renderer=None):
        from .chroma_video_renderer import ChromaVideoRenderer
        self.player = mci_player
        self.source = frame_source
        self.background = background
        self.renderer = renderer or ChromaVideoRenderer()
        self.last_photo = None

    def render_virtual(self, display):
        if not getattr(self.player, "opened", False) or not getattr(self.player, "has_video", False):
            return None
        frame = self.source.read_frame(self.player.position)
        return None if frame is None else self.renderer.preview(frame, self.background, display)

    def paint_tk(self, canvas):
        if not getattr(self.player, "opened", False) or not getattr(self.player, "has_video", False):
            return False
        frame = self.source.read_frame(self.player.position)
        if frame is None:
            return False
        self.last_photo = self.renderer.paint_tk(canvas, frame, self.background)
        return self.last_photo is not None
