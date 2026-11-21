"""P5 virtual multi-monitor lyric layout; no OS display APIs required.

Provides pixel bounds and text size for UI integration without opening windows.
"""
from dataclasses import dataclass
from .lyric_viewport import viewport


@dataclass(frozen=True)
class VirtualDisplay:
    width: int
    height: int
    x: int = 0
    y: int = 0

    def __post_init__(self):
        for value in (self.width, self.height, self.x, self.y):
            if type(value) is not int:
                raise ValueError("Display coordinates must be integers")
        if not 320 <= self.width <= 16384 or not 240 <= self.height <= 16384:
            raise ValueError("Unsupported virtual display size")


@dataclass(frozen=True)
class LyricFrame:
    display: VirtualDisplay
    line_texts: tuple
    active_index: int
    highlighted_prefix: str
    font_pixels: int
    bounds: tuple


def render_layout(lyrics, position, displays, *, line_count=2, offset_ms=0):
    """Produce independent lyric frames for each simulated display."""
    if not isinstance(displays, (tuple, list)) or not 1 <= len(displays) <= 8:
        raise ValueError("Expected 1-8 displays")
    if any(not isinstance(display, VirtualDisplay) for display in displays):
        raise ValueError("Invalid display")
    current = viewport(lyrics, position, line_count=line_count, offset_ms=offset_ms)
    result = []
    for display in displays:
        margin = max(8, min(display.width, display.height) // 30)
        available_height = display.height - 2 * margin
        font = max(12, min(80, display.width // 18, available_height // (line_count * 2)))
        result.append(LyricFrame(
            display=display,
            line_texts=tuple(line.text for line in current.lines),
            active_index=current.active_index,
            highlighted_prefix=current.highlighted_prefix,
            font_pixels=font,
            bounds=(display.x + margin, display.y + margin,
                    display.width - 2 * margin, available_height),
        ))
    return tuple(result)
