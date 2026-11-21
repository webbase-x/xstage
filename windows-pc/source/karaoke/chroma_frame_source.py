"""Frame-source bridge for P5 chroma-key playback.

A real decoder can supply read_frame() -> VideoFrame. A deterministic RGB
source exercises the same compositor/renderer contract without video hardware.
The Windows MCI player does not expose frames and is not wrapped here.
"""
from .chroma_video_renderer import VideoFrame, ChromaVideoRenderer


class SimulatedVideoSource:
    """Repeatable decoded-frame stand-in with a moving red pixel on green."""

    def __init__(self, width=4, height=2):
        if type(width) is not int or type(height) is not int or not 1 <= width <= 8192 or not 1 <= height <= 8192:
            raise ValueError("Invalid source dimensions")
        self.width, self.height = width, height
        self.index = 0

    def read_frame(self):
        pixels = bytearray(bytes((0, 255, 0)) * (self.width * self.height))
        at = (self.index % (self.width * self.height)) * 3
        pixels[at:at + 3] = b"\xff\x00\x00"
        self.index += 1
        return VideoFrame(self.width, self.height, bytes(pixels))


class ChromaFramePipeline:
    """Pull decoded frames, composite, and render to a virtual or Tk display."""

    def __init__(self, source, background, renderer=None):
        if not callable(getattr(source, "read_frame", None)):
            raise ValueError("Frame source must implement read_frame()")
        if not isinstance(background, VideoFrame):
            raise ValueError("Background must be a VideoFrame")
        self.source = source
        self.background = background
        self.renderer = renderer or ChromaVideoRenderer()
        self.last_photo = None

    def next_frame(self):
        foreground = self.source.read_frame()
        if foreground is None:
            return None
        if not isinstance(foreground, VideoFrame):
            raise ValueError("Frame source returned invalid frame")
        return self.renderer.composite(foreground, self.background)

    def preview(self, display):
        frame = self.source.read_frame()
        return None if frame is None else self.renderer.preview(frame, self.background, display)

    def paint_tk(self, canvas):
        frame = self.source.read_frame()
        if frame is None:
            return False
        self.last_photo = self.renderer.paint_tk(canvas, frame, self.background)
        return self.last_photo is not None
