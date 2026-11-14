"""Timed lyrics: plain/enhanced LRC and standard MIDI/KAR lyric events."""
from __future__ import annotations

import bisect
import re
import os
from dataclasses import dataclass, field
from pathlib import Path


def ncn_text_bytes(data: bytes) -> bytes:
    """NCN DOS text ends at SUB (0x1A); trailing OPT bytes are not lyrics.

    Slice before decoding or splitting lines: the binary trailer may contain
    line breaks and bytes invalid in CP874. Cursor indices of the text prefix
    stay unchanged. Shared by standalone NCN and embedded EMK metadata/playback.
    """
    return data.split(b"\x1a", 1)[0]


def decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp874", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


@dataclass
class LyricLine:
    start: float
    text: str
    # Absolute times in seconds, with the text that starts at each time.
    words: list[tuple[float, str]] = field(default_factory=list)


class Lyrics:
    def __init__(self, lines=(), offset_ms: int = 0):
        self.lines = sorted(lines, key=lambda line: line.start)
        self.starts = [line.start for line in self.lines]
        self.offset_ms = offset_ms

    def at(self, position: float, user_offset_ms: int = 0):
        """Return current line, upcoming line and exact word-highlight prefix.

        Positive offset shows lyrics earlier. Plain LRC highlights an entire
        line at its timestamp; word timing is never invented from line length.
        """
        position += (self.offset_ms + user_offset_ms) / 1000
        index = bisect.bisect_right(self.starts, position) - 1
        if index < 0:
            return None, self.lines[0] if self.lines else None, ""
        line = self.lines[index]
        following = self.lines[index + 1] if index + 1 < len(self.lines) else None
        prefix = "".join(text for when, text in line.words if when <= position)
        return line, following, prefix if line.words else line.text


STAMP = re.compile(r"\[(\d+):(\d{2})(?:[.:](\d{1,3}))?\]")
WORD = re.compile(r"<(\d+):(\d{2})(?:[.:](\d{1,3}))?>")


def stamp_seconds(match) -> float:
    fraction = match.group(3) or "0"
    return int(match.group(1)) * 60 + int(match.group(2)) + int(fraction) / 10 ** len(fraction)


def parse_lrc(text: str) -> Lyrics:
    offset = re.search(r"\[offset:([+-]?\d+)\]", text, flags=re.I)
    lines = []
    for raw in text.splitlines():
        tags = list(STAMP.finditer(raw))
        if not tags:
            continue
        body = raw[tags[-1].end():]
        word_tags = list(WORD.finditer(body))
        words = []
        if word_tags:
            leading = body[:word_tags[0].start()]
            if leading:
                words.append((stamp_seconds(tags[0]), leading))
            for i, tag in enumerate(word_tags):
                stop = word_tags[i + 1].start() if i + 1 < len(word_tags) else len(body)
                words.append((stamp_seconds(tag), body[tag.end():stop]))
            body = WORD.sub("", body)
        for tag in tags:
            delta = stamp_seconds(tag) - stamp_seconds(tags[0])
            lines.append(LyricLine(stamp_seconds(tag), body,
                                   [(at + delta, value) for at, value in words]))
    return Lyrics(lines, int(offset.group(1)) if offset else 0)


def midi_lyrics(events: list[tuple[float, str]]) -> Lyrics:
    """Soft Karaoke '/' and '\\' delimit lines. Embedded MIDI lyrics use CR/LF."""
    lines = []
    text = ""
    words = []
    start = 0.0

    def flush():
        nonlocal text, words
        if text:
            lines.append(LyricLine(start, text, words))
        text, words = "", []

    for when, value in events:
        if value.startswith("@"):
            continue
        # Keep timing for each original syllable, including its spaces.
        parts = re.split(r"([/\\\r\n])", value)
        for part in parts:
            if part in ("/", "\\", "\r", "\n"):
                flush()
            elif part:
                if not text:
                    start = when
                text += part
                words.append((when, part))
    flush()
    return Lyrics(lines)


def sidecar_lyrics(path: Path) -> Lyrics | None:
    direct = path.with_suffix('.lrc')
    if direct.is_file():
        return parse_lrc(decode_text(direct.read_bytes()))
    if os.name == 'nt':
        return None
    # Windows filesystem is case insensitive, but this is also testable elsewhere.
    for child in path.parent.iterdir():
        if child.suffix.lower() == ".lrc" and child.stem.casefold() == path.stem.casefold():
            return parse_lrc(decode_text(child.read_bytes()))
    return None
