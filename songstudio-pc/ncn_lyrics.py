"""NCN karaoke companion discovery, Thai lyrics and MIDI/KAR timing.

Supported source layout:
    MIDI/NCN/Song/{0..9,A..Z}/CODE.MID
    MIDI/NCN/Lyrics/{0..9,A..Z}/CODE.LYR
    MIDI/NCN/Cursor/{0..9,A..Z}/CODE.CUR

NCN cursor values are uint16 LE positions at 24 units per MIDI quarter
note, NOT seconds or indices into an .lrc file. Tempo events in the matching
MIDI are used to convert positions to seconds. No approximate fake timings.
All parsers are offline and standard-library only.
"""
from __future__ import annotations

from bisect import bisect_right
from functools import lru_cache
from pathlib import Path
import os
import struct
import re
import unicodedata

MIDI_SUFFIXES = (".mid", ".midi")
TEXT_SUFFIXES = (".lyr", ".lrc")
CANDIDATE_COMPONENTS = {"song", "lyrics", "cursor"}


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp874", "tis-620"):
        try:
            return data.decode(encoding)
        except UnicodeError:
            continue
    raise ValueError("ไม่สามารถอ่านรหัสภาษาไทยในไฟล์ Lyrics")


@lru_cache(maxsize=256)
def _ncn_root(root: Path) -> bool:
    if root.name.casefold() == "ncn":
        return True
    try:
        entries = {item.name.casefold() for item in root.iterdir() if item.is_dir()}
    except OSError:
        return False
    return {"song", "lyrics", "cursor"}.issubset(entries)


def describe(path: Path):
    """Return (root, component, subdir, casefolded code) if within NCN tree."""
    path = Path(path)
    for ancestor in path.parents:
        name = ancestor.name.casefold()
        if name in CANDIDATE_COMPONENTS and _ncn_root(ancestor.parent):
            relative = path.relative_to(ancestor)
            if not relative.parts:
                return None
            return ancestor.parent, name, Path(*relative.parts[:-1]), path.stem.casefold()
    return None


def _find_ci(folder: Path, name: str) -> Path | None:
    try:
        for item in folder.iterdir():
            if item.name.casefold() == name.casefold() and item.is_dir():
                return item
    except OSError:
        return None
    return None


@lru_cache(maxsize=1024)
def _file_names(folder: Path) -> dict[str, Path]:
    try:
        return {p.name.casefold(): p for p in folder.iterdir() if p.is_file()}
    except OSError:
        return {}


def resolve_companions(midi: Path, index: dict | None = None) -> dict | None:
    """Resolve .MID/.LYR/.CUR in mirrored Song/Lyrics/Cursor directories.

    Never use files from a different code or digit bucket. Case-insensitive
    Windows compatible; does not depend on directory listing order.
    """
    found = describe(midi)
    if not found or found[1] != "song" or midi.suffix.lower() not in MIDI_SUFFIXES:
        return None
    root, _, subdir, code = found
    result = {"midi": str(midi), "lyrics": None, "cursor": None,
              "format": "NCN", "code": midi.stem}
    for component, suffix, key in (("lyrics", ".lyr", "lyrics"),
                                   ("cursor", ".cur", "cursor")):
        indexed = (index or {}).get((str(root).casefold(), str(subdir).casefold(),
                                      code, suffix))
        if indexed is not None and Path(indexed).is_file():
            result[key] = str(indexed)
            continue
        folder = _find_ci(root, component)
        if folder is None:
            continue
        for part in subdir.parts:
            folder = _find_ci(folder, part) if folder else None
        if folder:
            candidate = _file_names(folder).get((midi.stem + suffix).casefold())
            if candidate is not None:
                result[key] = str(candidate)
    missing = [name for name in ("lyrics", "cursor") if not result[name]]
    result["missing"] = missing
    return result


def index_component(path: Path, index: dict):
    item = describe(path)
    if item and item[1] in ("lyrics", "cursor") and path.suffix.lower() in (".lyr", ".cur"):
        root, component, subdir, code = item
        index[(str(root).casefold(), str(subdir).casefold(),
               code, path.suffix.lower())] = str(path)


def lyric_metadata(path: Path):
    """Read only first ~8 KB of .LYR to keep scanning 100k songs fast."""
    with Path(path).open("rb") as source:
        raw = source.read(8192)
    lines = _decode_text(raw).splitlines()
    if len(lines) < 4:
        raise ValueError("ไฟล์ .LYR มีหัวข้อมูลไม่ครบ 4 บรรทัด")
    return {"title": lines[0].strip(), "artist": lines[1].strip(),
            "key": lines[2].strip()}


def _varlen(source: bytes, pos: int, end: int):
    value = 0
    for _ in range(4):
        if pos >= end:
            raise ValueError("MIDI delta-time ไม่สมบูรณ์")
        byte = source[pos]
        pos += 1
        value = (value << 7) | (byte & 127)
        if not byte & 0x80:
            return value, pos
    raise ValueError("MIDI delta-time ยาวเกินมาตรฐาน")


def midi_events(midi: Path, *, include_duration=False):
    """Extract tempo and text metadata, preserving absolute tick positions."""
    data = Path(midi).read_bytes()
    if len(data) < 14 or data[:4] != b"MThd":
        raise ValueError("ไฟล์ MIDI ไม่มีส่วนหัว MThd")
    length = struct.unpack_from(">I", data, 4)[0]
    if length < 6 or len(data) < 8 + length:
        raise ValueError("ส่วนหัว MIDI ไม่สมบูรณ์")
    fmt, n_tracks, division = struct.unpack_from(">HHH", data, 8)
    if fmt == 2:
        raise ValueError("MIDI format 2 มีหลายไทม์ไลน์ ไม่รองรับการแปลง Cursor")
    if division & 0x8000:
        raise ValueError("MIDI แบบ SMPTE timing ไม่รองรับการแปลง Cursor")
    if division == 0 or n_tracks > 1024:
        raise ValueError("MIDI timing หรือจำนวน track ไม่ถูกต้อง")
    offset = 8 + length
    max_tick = 0
    tempos = [(0, 500000)]
    texts = []
    for track_index in range(n_tracks):
        if data[offset:offset+4] != b"MTrk" or offset+8 > len(data):
            raise ValueError("ข้อมูล MIDI track ไม่สมบูรณ์")
        count = struct.unpack_from(">I", data, offset+4)[0]
        pos = offset + 8
        end = pos + count
        if end > len(data):
            raise ValueError("MIDI track มีข้อมูลไม่ครบ")
        tick = 0
        running = None
        order = 0
        while pos < end:
            delta, pos = _varlen(data, pos, end)
            tick += delta
            if pos >= end:
                raise ValueError("MIDI event ไม่มี status byte")
            opcode = data[pos]
            if opcode & 0x80:
                pos += 1
                if opcode < 0xf0:
                    running = opcode
            else:
                if running is None:
                    raise ValueError("MIDI running status ไม่ถูกต้อง")
                opcode = running
            if opcode == 0xff:
                if pos >= end:
                    raise ValueError("MIDI meta event ไม่สมบูรณ์")
                tag = data[pos]
                pos += 1
                count_bytes, pos = _varlen(data, pos, end)
                payload = data[pos:pos+count_bytes]
                if len(payload) != count_bytes:
                    raise ValueError("MIDI meta payload ไม่สมบูรณ์")
                pos += count_bytes
                if tag == 0x51 and count_bytes == 3:
                    tempos.append((tick, int.from_bytes(payload, "big")))
                elif tag in (0x01, 0x05, 0x03):
                    try:
                        decoded = _decode_text(payload)
                    except ValueError:
                        decoded = payload.decode("latin-1", errors="replace")
                    texts.append((tick, track_index, order, tag, decoded))
                if tag == 0x2f:
                    break
            elif opcode in (0xf0, 0xf7):
                count_bytes, pos = _varlen(data, pos, end)
                pos += count_bytes
            elif 0x80 <= opcode <= 0xef:
                pos += 1 if (opcode & 0xf0) in (0xc0, 0xd0) else 2
            elif opcode in (0xf1, 0xf3):
                pos += 1
            elif opcode == 0xf2:
                pos += 2
            elif opcode in (0xf6, 0xf8, 0xfa, 0xfb, 0xfc, 0xfe):
                pass
            else:
                raise ValueError("MIDI status ไม่รองรับ")
            if pos > end:
                raise ValueError("MIDI event เกินขอบเขต track")
            order += 1
        max_tick = max(max_tick, tick)
        offset = end
    # When multiple tracks specify a tempo at the same tick, choose the
    # last event deterministically. Standard MIDI default is 120 BPM.
    tempo_map = {}
    for t, rate in sorted(tempos, key=lambda x: x[0]):
        if rate > 0:
            tempo_map[t] = rate
    anchors = sorted(tempo_map.items())
    ticks, sec, rates = [], [], []
    current_seconds, old_tick, old_rate = 0., 0, 500000
    for tick, rate in anchors:
        current_seconds += (tick-old_tick) * old_rate / (division * 1_000_000)
        ticks.append(tick)
        sec.append(current_seconds)
        rates.append(rate)
        old_tick, old_rate = tick, rate
    result = (division, (ticks, sec, rates),
              sorted(texts, key=lambda x: (x[0], x[1], x[2])))
    if include_duration:
        return (*result, tick_to_seconds(max_tick, division, result[1]))
    return result


def tick_to_seconds(tick, division, map_tuple):
    ticks, seconds, rates = map_tuple
    idx = max(0, bisect_right(ticks, tick)-1)
    return round(seconds[idx] + (tick-ticks[idx]) * rates[idx] /
                 (division * 1_000_000), 3)


def _timed_lines_to_json(lines, code, format_name, metadata=None):
    for n, line in enumerate(lines):
        next_time = lines[n+1]["startTime"] if n+1 < len(lines) else line["startTime"]+4
        line["endTime"] = round(max(line["startTime"]+.05, next_time), 3)
    return {
        "schemaVersion": 1, "songCode": code, "sourceFormat": format_name,
        "lines": lines, "rawLrc": to_lrc(lines),
        "metadata": metadata or {},
    }


def to_lrc(lines):
    rows = []
    for line in lines:
        timestamp = max(0, float(line["startTime"]))
        minutes, rem = divmod(timestamp, 60)
        rows.append(f"[{int(minutes):02d}:{rem:05.2f}]{line['text']}")
    return "\n".join(rows) + ("\n" if rows else "")


def ncn_document(companions):
    """NCN24 MIDI/LYR/CUR synchronisation, adapted from X-Stage Karaoke PC.

    A CUR entry represents one *CP874 source byte*, not a Unicode grapheme.
    The newline marker consumes one CUR entry per nonblank lyric line.
    Preserve verified earlier lyrics when a historical CUR file ends short,
    but report incomplete timing rather than fabricating the remainder.
    """
    if not companions or companions.get("missing"):
        raise ValueError("ชุด NCN ไม่ครบ: ขาด " +
                         ", ".join(companions.get("missing", ["Lyrics", "Cursor"])) +
                         " · ต้องมี .MID + .LYR + .CUR รหัสเดียวกัน")
    lyric_file = Path(companions["lyrics"])
    cursor_file = Path(companions["cursor"])
    source_bytes = lyric_file.read_bytes()
    if len(source_bytes) > 1024 * 1024:
        raise ValueError("ไฟล์ NCN .LYR ใหญ่เกิน 1 MB")
    # Legacy NCN is CP874. Normalize line endings in bytes before consuming
    # CUR indices: Windows CRLF is ONE line marker, not two time entries.
    rows = source_bytes.replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n")
    if len(rows) < 5:
        raise ValueError("NCN .LYR ไม่มีข้อมูลเนื้อร้องเริ่มจากบรรทัดที่ 5")
    meta = {
        "title": _decode_text(rows[0]).strip(),
        "artist": _decode_text(rows[1]).strip(),
        "key": _decode_text(rows[2]).strip(),
    }
    raw_cursor = cursor_file.read_bytes()
    if len(raw_cursor) > 2 * 1024 * 1024:
        raise ValueError("ไฟล์ NCN .CUR ใหญ่เกิน 2 MB")
    warnings = []
    if len(raw_cursor) % 2:
        if raw_cursor[-1:] != b"\xff":
            warnings.append("CUR มีไบต์ท้ายที่ไม่ครบหนึ่งค่าเวลา · ข้ามไบต์ท้าย")
        raw_cursor = raw_cursor[:-1]
    positions = list(struct.unpack("<" + "H" * (len(raw_cursor) // 2), raw_cursor))
    if not positions:
        raise ValueError("NCN .CUR ไม่มีตำแหน่งเวลาที่อ่านได้")

    body = list(rows[4:])
    while body and not body[-1].strip(b" \x00\x1a"):
        body.pop()
    removed_footers = 0
    footer = re.compile(r"^(?:nick[\s_-]*karaoke(?:\s+professional)?|นิค[\s_-]*คาราโอเกะ)$", re.I)
    def needed(lines):
        return sum(1 + len(part) for part in lines if part.strip())
    # Some old collections append an untimed Nick Karaoke credit. Strip only
    # when there are not enough CUR entries: a *timed* credit is real lyrics.
    while body and len(positions) < needed(body):
        candidate = body[-1].strip(b" \x00\x1a").decode("cp874", errors="replace")
        if not footer.fullmatch(candidate):
            break
        body.pop()
        removed_footers += 1
        while body and not body[-1].strip(b" \x00\x1a"):
            body.pop()

    division, tempo_map, _, midi_duration = midi_events(
        Path(companions["midi"]), include_duration=True)
    rendered = []
    previous_pos = 0
    cursor_index = 0
    timing_incomplete = False
    stop_song = False
    for raw_line in body:
        if not raw_line.strip():
            continue
        chars = []
        text_parts = []
        # Use the *original source bytes* to preserve NCN Cursor alignment.
        for byte in b"\n" + raw_line:
            if cursor_index >= len(positions):
                timing_incomplete = True
                break
            position = positions[cursor_index]
            cursor_index += 1
            if byte in (10, 13):  # One NCN line marker has no printable glyph.
                continue
            if position == 65535:  # Historical end/untimed position marker.
                timing_incomplete = True
                continue
            if position < previous_pos:
                position = previous_pos  # Never run lyrics backwards.
                warnings.append("CUR มีเวลาย้อนกลับ · ปรับให้เรียงตามเวลาดนตรี")
            previous_pos = position
            when = tick_to_seconds(position * division / 24.0, division, tempo_map)
            if when > midi_duration + 10:
                warnings.append("CUR มีเวลายาวเกินความยาว MIDI · คงเฉพาะช่วงก่อนหน้า")
                timing_incomplete = True
                stop_song = True
                break
            char = bytes([byte]).decode("cp874", errors="replace")
            text_parts.append(char)
            if unicodedata.category(char).startswith("M") and chars:
                chars[-1]["text"] += char
            else:
                chars.append({"text": char, "startTime": when})
        text = "".join(text_parts)
        if text.strip() and chars:
            rendered.append({
                "startTime": chars[0]["startTime"],
                "text": text,
                "characters": chars
            })
        if cursor_index >= len(positions) or stop_song:
            if not stop_song and len(positions) < needed(body):
                timing_incomplete = True
            break
    if not rendered:
        raise ValueError("NCN ไม่มีเนื้อร้องที่จับคู่กับ CUR/MIDI ได้จริง")
    if timing_incomplete:
        warnings.append("เนื้อร้องบางช่วงไม่มีเวลาจริง · เก็บเฉพาะส่วนที่ตรวจสอบได้")
    if cursor_index < len(positions):
        meta["unusedCursorValues"] = len(positions) - cursor_index
    if warnings:
        meta["timingWarnings"] = list(dict.fromkeys(warnings))
    meta["timingComplete"] = not timing_incomplete
    meta["removedUntimedFooterLines"] = removed_footers
    meta["cursorValues"] = len(positions)
    return _timed_lines_to_json(rendered, companions["code"], "NCN", meta)

def kar_document(midi: Path, code: str):
    """Real MIDI/KAR lyric events using the X-Stage Karaoke PC line protocol.

    Soft Karaoke uses '/' and '\\' line boundaries. Ordinary MIDI lyric
    meta events also use CR/LF. A line-only control event must NOT be
    discarded by a whitespace filter. Notes alone never become lyrics.
    """
    division, tempo_map, events = midi_events(midi)
    chunks = []
    title, artist = "", ""
    for tick, track, order, tag, text in events:
        if tag not in (1, 5) or not text:
            continue
        if text.startswith("@T"):
            if not title:
                title = text[2:].strip()
            elif not artist:
                artist = text[2:].strip()
            continue
        if text.startswith("@"):
            # Karaoke metadata (@L/@I and unknown declarations) are not song
            # words and must never be presented as timed lyrics.
            continue
        when = tick_to_seconds(tick, division, tempo_map)
        chunks.append((when, text))
    if not chunks:
        raise ValueError("ไฟล์ MIDI/KAR ไม่มีเหตุการณ์เนื้อร้องที่ฝังอยู่")
    lines, pieces, start = [], [], None
    def flush():
        nonlocal pieces, start
        actual = "".join(p["text"] for p in pieces)
        if actual.strip():
            lines.append({"startTime": start, "text": actual,
                          "characters": list(pieces)})
        pieces, start = [], None
    for when, raw in chunks:
        # Preserve per-syllable timing and original spaces, as PC karaoke
        # playback does. Splitting on CR/LF is essential for embedded MIDI.
        for segment in re.split(r"([/\\\r\n])", raw):
            if segment in ("/", "\\", "\r", "\n"):
                flush()
            elif segment:
                pieces.append({"startTime": when, "text": segment})
                if start is None:
                    start = when
    flush()
    if not lines:
        raise ValueError("ไฟล์ MIDI/KAR มีแต่ชื่อเพลง ไม่มีเนื้อร้อง")
    return _timed_lines_to_json(lines, code, "KAR",
                                 {"title": title, "artist": artist})
