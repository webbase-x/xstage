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
    raw = Path(path).open("rb").read(8192)
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


def midi_events(midi: Path):
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
    return division, (ticks, sec, rates), sorted(texts, key=lambda x: (x[0], x[1], x[2]))


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
    """Render NCN lyrics to a valid timed JSON, not a fake empty LRC."""
    if not companions or companions.get("missing"):
        raise ValueError("ชุด NCN ไม่ครบ: ขาด " +
                         ", ".join(companions.get("missing", ["Lyrics", "Cursor"])) +
                         " · ต้องมี .MID + .LYR + .CUR รหัสเดียวกัน")
    lyric_file = Path(companions["lyrics"])
    cursor_file = Path(companions["cursor"])
    lines = _decode_text(lyric_file.read_bytes()).splitlines()
    if len(lines) < 5:
        raise ValueError("NCN .LYR ไม่มีข้อมูลเนื้อร้องเริ่มจากบรรทัดที่ 5")
    meta = {"title": lines[0].strip(), "artist": lines[1].strip(),
            "key": lines[2].strip()}
    raw = cursor_file.read_bytes()
    if len(raw) % 2:
        if raw[-1] != 0xff:
            raise ValueError("NCN .CUR มีจำนวนไบต์คี่ และไม่มีตัวจบ FF")
        raw = raw[:-1]
    ticks = list(struct.unpack("<" + "H"*(len(raw)//2), raw))
    division, tempo_map, _ = midi_events(Path(companions["midi"]))
    used = 0
    rendered = []
    for value in lines[4:]:
        lyric = value.strip()
        if not lyric:
            continue
        # NCN cursor includes a leading '/' newline event per lyrics line.
        text = "/" + lyric
        if used + len(text) > len(ticks):
            raise ValueError("NCN Cursor มีตำแหน่งเวลาน้อยกว่าตัวอักษรใน Lyrics")
        events = []
        current = []
        current_time = None
        # Keep Thai combining marks visually joined to their base character,
        # but consume a cursor word for EACH original Unicode code point.
        for ch in text:
            position = ticks[used]
            used += 1
            when = tick_to_seconds(position * division / 24.0, division, tempo_map)
            if ch == "/":
                continue
            if unicodedata.combining(ch) and current:
                current[-1]["text"] += ch
            else:
                current.append({"text": ch, "startTime": when})
        if not current:
            continue
        rendered.append({"startTime": current[0]["startTime"],
                         "text": lyric, "characters": current})
    if not rendered:
        raise ValueError("NCN ไม่มีเนื้อร้องที่อ่านได้")
    if used < len(ticks):
        # Some encoders leave an additional pause or unneeded cursor value.
        meta["unusedCursorValues"] = len(ticks)-used
    return _timed_lines_to_json(rendered, companions["code"], "NCN", meta)


def kar_document(midi: Path, code: str):
    """Read embedded MIDI/KAR lyric and text events; drop @T headers."""
    division, tempo_map, events = midi_events(midi)
    chunks = []
    title, artist = "", ""
    for tick, track, order, tag, text in events:
        if tag not in (1, 5) or not text.strip():
            continue
        text = text.replace("\r", "\n")
        if text.startswith("@T"):
            if not title:
                title = text[2:].strip()
            elif not artist:
                artist = text[2:].strip()
            continue
        if text.startswith("@I") or text.startswith("@L"):
            continue
        when = tick_to_seconds(tick, division, tempo_map)
        chunks.append((when, text))
    if not chunks:
        raise ValueError("ไฟล์ MIDI/KAR ไม่มีเหตุการณ์เนื้อร้องที่ฝังอยู่")
    lines, pieces, start = [], [], None
    def flush():
        nonlocal pieces, start
        actual = "".join(p["text"] for p in pieces).strip()
        if actual:
            lines.append({"startTime": start, "text": actual,
                          "characters": list(pieces)})
        pieces, start = [], None
    for when, raw in chunks:
        segments = raw.replace("\\", "/").split("/")
        for i, segment in enumerate(segments):
            if i:
                flush()
            if segment:
                pieces.append({"startTime": when, "text": segment})
                if start is None:
                    start = when
    flush()
    if not lines:
        raise ValueError("ไฟล์ MIDI/KAR มีแต่ชื่อเพลง ไม่มีเนื้อร้อง")
    return _timed_lines_to_json(lines, code, "KAR",
                                 {"title": title, "artist": artist})
