"""Opt-in P5 RGB24 video compositor and virtual-display preview.

MCI video windows do not expose RGB frames; this adapter is for frame providers
that supply RGB24 explicitly. Never pretend MCI playback is chroma-keyed.
"""
from dataclasses import dataclass
from .chroma_key import ChromaKey, composite_rgb24
from .virtual_lyric_display import VirtualDisplay


@dataclass(frozen=True)
class VideoFrame:
    width: int
    height: int
    rgb24: bytes

    def __post_init__(self):
        if type(self.width) is not int or type(self.height) is not int or not 1 <= self.width <= 8192 or not 1 <= self.height <= 8192:
            raise ValueError("Invalid video frame dimensions")
        if not isinstance(self.rgb24, bytes) or len(self.rgb24) != self.width * self.height * 3:
            raise ValueError("Invalid RGB24 video frame")


class ChromaVideoRenderer:
    """Composes captured RGB24 frames, then resizes for virtual or Tk displays."""

    def __init__(self, key=None):
        self.key = ChromaKey() if key is None else key
        if not isinstance(self.key, ChromaKey):
            raise ValueError("Invalid chroma key")

    def composite(self, foreground, background):
        if not isinstance(foreground, VideoFrame) or not isinstance(background, VideoFrame):
            raise ValueError("VideoFrame required")
        if (foreground.width, foreground.height) != (background.width, background.height):
            raise ValueError("Foreground and background dimensions differ")
        return VideoFrame(foreground.width, foreground.height,
                          composite_rgb24(foreground.rgb24, background.rgb24,
                                          foreground.width, foreground.height, key=self.key))

    def preview(self, foreground, background, display):
        """Produce resized RGB24 bytes using Pillow, without creating a window."""
        if not isinstance(display, VirtualDisplay):
            raise ValueError("VirtualDisplay required")
        frame = self.composite(foreground, background)
        from PIL import Image
        image = Image.frombytes("RGB", (frame.width, frame.height), frame.rgb24)
        image = image.resize((display.width, display.height), Image.Resampling.BILINEAR)
        return VideoFrame(display.width, display.height, image.tobytes())

    def paint_tk(self, canvas, foreground, background):
        """Paint an opt-in captured frame to an existing Tk canvas.

        Caller owns the frame source and must retain the returned PhotoImage.
        """
        from PIL import Image, ImageTk
        if canvas.winfo_width() < 1 or canvas.winfo_height() < 1:
            return None
        display = VirtualDisplay(max(320, canvas.winfo_width()), max(240, canvas.winfo_height()))
        frame = self.preview(foreground, background, display)
        image = Image.frombytes("RGB", (frame.width, frame.height), frame.rgb24)
        photo = ImageTk.PhotoImage(image, master=canvas)
        canvas.delete("chroma-video")
        canvas.create_image(0, 0, anchor="nw", image=photo, tags="chroma-video")
        return photo
