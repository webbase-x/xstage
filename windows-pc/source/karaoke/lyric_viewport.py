"""Pure P5 multi-line timed lyric viewport; no monitor or GUI required."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class LyricViewport:
    lines: tuple
    active_index: int
    highlighted_prefix: str


def viewport(lyrics, position, *, line_count=2, offset_ms=0):
    """Return 2–4 consecutive real lyric lines without synthesizing timestamps.

    Keep the active line visible and provide the exact timed prefix from Lyrics.at.
    """
    if type(line_count) is not int or line_count not in (2, 3, 4):
        raise ValueError("Lyric line count must be 2, 3 or 4")
    if type(position) not in (int, float) or not math.isfinite(position):
        raise ValueError("Invalid playback position")
    if type(offset_ms) is not int or abs(offset_ms) > 600000:
        raise ValueError("Invalid lyric offset")
    current, following, prefix = lyrics.at(position, offset_ms)
    rows = lyrics.lines
    if not rows:
        return LyricViewport((), -1, "")
    if current is None:
        return LyricViewport(tuple(rows[:line_count]), -1, "")
    # Identity matching avoids confusing repeated lyric text or timestamps.
    index = next((i for i, line in enumerate(rows) if line is current), -1)
    if index < 0:
        raise ValueError("Active lyric line missing from timeline")
    return LyricViewport(tuple(rows[index:index + line_count]), 0, prefix)
