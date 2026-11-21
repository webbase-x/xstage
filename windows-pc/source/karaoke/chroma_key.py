"""P5 pure RGB chroma-key compositor for deterministic virtual-display tests.

Input/output are tightly packed RGB24 bytes; no video driver is required.
The renderer may opt in explicitly without altering existing playback.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class ChromaKey:
    rgb: tuple = (0, 255, 0)
    tolerance: int = 30

    def __post_init__(self):
        if (not isinstance(self.rgb, tuple) or len(self.rgb) != 3 or
                any(type(x) is not int or not 0 <= x <= 255 for x in self.rgb)):
            raise ValueError("Invalid chroma-key RGB")
        if type(self.tolerance) is not int or not 0 <= self.tolerance <= 255:
            raise ValueError("Invalid chroma-key tolerance")


def composite_rgb24(foreground, background, width, height, *, key=ChromaKey()):
    """Replace foreground pixels near the selected key with background pixels."""
    if type(width) is not int or type(height) is not int or not 0 < width <= 8192 or not 0 < height <= 8192:
        raise ValueError("Invalid frame dimensions")
    size = width * height * 3
    if (not isinstance(foreground, bytes) or not isinstance(background, bytes)
            or len(foreground) != size or len(background) != size):
        raise ValueError("RGB24 frame sizes must match")
    if not isinstance(key, ChromaKey):
        raise ValueError("Invalid chroma-key settings")
    # OpenCV is already available when the opt-in real decoder is enabled.
    # Vectorized native compositing keeps high-resolution video responsive.
    # The standard-library-only fallback remains for core and CI tests.
    try:
        import cv2
        import numpy as np
    except ImportError:
        pass
    else:
        pixels = np.frombuffer(foreground, dtype=np.uint8).reshape(height, width, 3)
        backing = np.frombuffer(background, dtype=np.uint8).reshape(height, width, 3)
        lower = tuple(max(0, component - key.tolerance) for component in key.rgb)
        upper = tuple(min(255, component + key.tolerance) for component in key.rgb)
        mask = cv2.inRange(pixels, lower, upper)
        result = pixels.copy()
        cv2.copyTo(backing, mask, result)
        return result.tobytes()
    result = bytearray(foreground)
    kr, kg, kb = key.rgb
    for i in range(0, size, 3):
        r, g, b = foreground[i:i + 3]
        if max(abs(r - kr), abs(g - kg), abs(b - kb)) <= key.tolerance:
            result[i:i + 3] = background[i:i + 3]
    return bytes(result)
