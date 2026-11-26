"""X-Stage Song Studio Plus NCN/MIDI reader.

This standalone parser starts from the previously tested legacy NCN reader
in the same repository; it does not depend on the older Studio runtime.
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
# Observed on legacy NCN collections: these markers are not proof of MIDI.
LEGACY_SMF_PREFIXES = frozenset((
    b"TECH", b"MTdd", b"eThd", b"#$%&", b"#nu$", b"-4Hd",
))
STANDARD_SMF_PREFIXES = frozenset((b"MThd", b"NCN1", b"Lock", b"Good"))
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
def _file_names_at_stamp(folder: Path, mtime_ns: int, ctime_ns: int) -> dict[str, Path]:
    # Cache by directory revision rather than permanently by path. New NCN
    # LYR/CUR companions created after the first song must become visible.
    try:
        return {p.name.casefold(): p for p in folder.iterdir()
                if p.is_file() and not p.is_symlink()}
    except OSError:
        return {}


def _file_names(folder: Path) -> dict[str, Path]:
    try:
        stat = folder.stat()
    except OSError:
        return {}
    return _file_names_at_stamp(folder, stat.st_mtime_ns, stat.st_ctime_ns)


# The source index explicitly clears this cache after refreshing its scan.
# Preserve that public callable contract while making per-folder writes visible.
_file_names.cache_clear = _file_names_at_stamp.cache_clear


def _find_companion_file(folder: Path, code: str, suffix: str) -> Path | None:
    """Resolve by exact code and preserve original filename casing on Windows.

    The directory cache avoids repeated scans in huge NCN collections. If
    companion files are copied after a prior lookup, an O(1) direct probe
    detects them and a fresh listing returns the spelling stored on disk.
    """
    key = (code + suffix).casefold()
    cached = _file_names(folder).get(key)
    if cached is not None and cached.is_file() and not cached.is_symlink():
        return cached
    for extension in (suffix, suffix.upper()):
        candidate = folder / (code + extension)
        if not candidate.is_file() or candidate.is_symlink():
            continue
        try:
            for item in folder.iterdir():
                if (item.name.casefold() == key and item.is_file()
                        and not item.is_symlink()):
                    return item
        except OSError:
            pass
        return candidate
    return None


def resolve_companions(midi: Path, index: dict | None = None, *,
                       indexed_only: bool = False) -> dict | None:
    """Resolve .MID/.LYR/.CUR in mirrored Song/Lyrics/Cursor directories.

    Never use files from a different code or digit bucket. Case-insensitive
    Windows compatible; does not depend on directory listing order.
    """
    midi = Path(midi)
    if midi.suffix.lower() not in MIDI_SUFFIXES:
        return None
    # Studio imports also accept exact same-stem NCN files placed in ONE
    # directory, e.g. "00001(1).mid/.lyr/.cur". The classic split NCN
    # Song/Lyrics/Cursor layout below is unchanged.
    if not indexed_only:
        direct = {}
        try:
            files = {p.name.casefold(): p for p in midi.parent.iterdir()
                     if p.is_file() and not p.is_symlink()}
            for component, suffix in (("lyrics", ".lyr"), ("cursor", ".cur")):
                match = files.get((midi.stem + suffix).casefold())
                if match is not None:
                    direct[component] = str(match)
        except OSError:
            pass
        if direct:
            result = {"midi": str(midi), "lyrics": direct.get("lyrics"),
                      "cursor": direct.get("cursor"), "format": "NCN",
                      "code": midi.stem}
            result["missing"] = [role for role in ("lyrics", "cursor")
                                 if not result.get(role)]
            return result
    found = describe(midi)
    if not found or found[1] != "song":
        return None
    root, _, subdir, code = found
    result = {"midi": str(midi), "lyrics": None, "cursor": None,
              "format": "NCN", "code": midi.stem}
    for component, suffix, key in (("lyrics", ".lyr", "lyrics"),
                                   ("cursor", ".cur", "cursor")):
        indexed = (index or {}).get((str(root).casefold(), str(subdir).casefold(),
                                      code, suffix))
        if indexed is not None and (indexed_only or Path(indexed).is_file()):
            result[key] = str(indexed)
            continue
        if indexed_only:
            continue
        folder = _find_ci(root, component)
        if folder is None:
            continue
        for part in subdir.parts:
            folder = _find_ci(folder, part) if folder else None
        if folder:
            candidate = _find_companion_file(folder, midi.stem, suffix)
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


def lyric_rows(raw):
    """Decode full text before newline normalization, including UTF-16 BOM."""
    if raw.startswith((b"\xff\xfe",b"\xfe\xff")):
        text=raw.decode("utf-16")
    else:
        text=_decode_text(raw.split(b"\x1a",1)[0])
    return text.split("\x1a",1)[0].replace("\r\n","\n").replace("\r","\n").split("\n")


def lyric_metadata(path: Path):
    with Path(path).open("rb") as source:
        raw=source.read(1024*1024+1)
    if len(raw)>1024*1024: raise ValueError("LYR exceeds 1 MB")
    lines=lyric_rows(raw)
    if len(lines)<2: raise ValueError("LYR metadata incomplete")
    title=re.sub(r"^(?:title|song title|ชื่อเพลง)\s*[:=]\s*","",lines[0].strip(),flags=re.I)
    artist=re.sub(r"^(?:artist|singer|ศิลปิน|นักร้อง)\s*[:=]\s*","",lines[1].strip(),flags=re.I)
    return {"title":title,"artist":artist,"key":lines[2].strip() if len(lines)>2 else ""}


def midi_metadata(events):
    tags=[v[2:].strip() for tick,track,order,tag,v in events
          if tick==0 and tag in (1,5) and v.startswith("@T") and v[2:].strip()]
    return {"title":tags[0] if tags else "", "artist":tags[1] if len(tags)>1 else ""}


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


def _valid_substituted_smf(data: bytes) -> bool:
    """Validate real SMF geometry before accepting an observed legacy marker."""
    if len(data) < 26:
        return False
    length = struct.unpack_from(">I", data, 4)[0]
    if not 6 <= length <= 1024 or 8 + length + 8 > len(data):
        return False
    fmt, tracks, division = struct.unpack_from(">HHH", data, 8)
    if fmt not in (0, 1) or not 1 <= tracks <= 1024:
        return False
    if fmt == 0 and tracks != 1:
        return False
    if division == 0 or division & 0x8000:
        return False
    offset = 8 + length
    if data[offset:offset+4] != b"MTrk":
        return False
    track_size = struct.unpack_from(">I", data, offset+4)[0]
    return 4 <= track_size <= len(data) - offset - 8


def midi_events(midi: Path, *, include_duration=False, raw_data=None):
    """Extract tempo and text metadata, preserving absolute tick positions."""
    data = Path(midi).read_bytes() if raw_data is None else raw_data
    # Accept known legacy magic substitutions only after full header/track
    # validation. Never guess timings, decrypt, or modify the source file.
    if len(data) < 14:
        raise ValueError("ไฟล์ MIDI สั้นเกินไปหรือส่วนหัวไม่สมบูรณ์")
    signature = data[:4]
    alternative = signature not in STANDARD_SMF_PREFIXES
    if alternative and (signature not in LEGACY_SMF_PREFIXES
                        or not _valid_substituted_smf(data)):
        found = signature.hex(" ").upper()
        raise ValueError(
            f"ส่วนหัว MIDI {found} ไม่ใช่ SMF มาตรฐานหรือไม่มีโครงสร้าง "
            "MThd/MTrk ที่ตรวจสอบได้ · อาจเป็นไฟล์เข้ารหัสหรือรูปแบบเฉพาะ"
        )
    length = struct.unpack_from(">I", data, 4)[0]
    if length < 6 or len(data) < 8 + length:
        raise ValueError("ส่วนหัว MIDI ไม่สมบูรณ์")
    fmt, n_tracks, division = struct.unpack_from(">HHH", data, 8)
    if fmt == 2:
        raise ValueError("MIDI format 2 มีหลายไทม์ไลน์ ไม่รองรับการแปลง Cursor")
    if division & 0x8000:
        raise ValueError("MIDI แบบ SMPTE timing ไม่รองรับการแปลง Cursor")
    if division == 0 or not 1 <= n_tracks <= 1024:
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
        found_eot = False
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
                    found_eot = True
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
        if alternative and not found_eot:
            raise ValueError("ส่วนหัว MIDI พิเศษไม่มี End of Track ครบตามมาตรฐาน")
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
        chars = line.get("characters") or []
        # Nick/NCN CUR gives real onset times for each source character. Never
        # close a line before its last measured cue: doing so produced invalid
        # Plus SQLite rows and silently rejected otherwise complete NCN songs.
        latest_cue = max((float(c["startTime"]) for c in chars),
                         default=float(line["startTime"]))
        is_last = n + 1 == len(lines)
        nominal_end = (float(lines[n+1]["startTime"]) if not is_last
                       else float(line["startTime"]) + 4.0)
        # An overlapping line or an unusually long final phrase cannot
        # borrow an invented endpoint from CUR. Only extend the boundary
        # enough to keep *measured* character onsets inside their own line.
        if is_last or latest_cue >= nominal_end:
            line["endTimeEstimated"] = True
        line["endTime"] = round(max(float(line["startTime"]) + .05,
                                    nominal_end, latest_cue + .05), 3)
        # X-Stage Karaoke PC/Web consumes syllables[start,duration,text].
        # NCN CUR byte cues and KAR MIDI meta-event cues are already timed;
        # carry them through rather than letting the stage interpolate an
        # approximate word highlight over the whole line.
        chars = line.get("characters") or []
        if chars:
            syllables = []
            for i, item in enumerate(chars):
                start = max(0., float(item["startTime"]))
                end = min(line["endTime"], float(chars[i+1]["startTime"])) \
                    if i+1 < len(chars) else line["endTime"]
                syllables.append({
                    "text": str(item["text"]),
                    "start": round(start, 4),
                    "duration": round(max(0., end-start), 4)
                })
            line["syllables"] = syllables
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
    utf16=source_bytes.startswith((b"\xff\xfe",b"\xfe\xff"))
    if utf16:
        # A Unicode text conversion can retain legacy CP874 cursor offsets.
        # Reject nonrepresentable text rather than inventing cursor positions.
        source_bytes="\n".join(lyric_rows(source_bytes)).encode("cp874")
    source_bytes=source_bytes.split(b"\x1a",1)[0]
    if len(source_bytes) > 1024 * 1024:
        raise ValueError("ไฟล์ NCN .LYR ใหญ่เกิน 1 MB")
    # Legacy NCN is CP874. Normalize line endings in bytes before consuming
    # CUR indices: Windows CRLF is ONE line marker, not two time entries.
    rows = source_bytes.replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n")
    if len(rows) < 5:
        raise ValueError("NCN .LYR ไม่มีข้อมูลเนื้อร้องเริ่มจากบรรทัดที่ 5")
    meta = lyric_metadata(lyric_file)
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

    # Converted NCN libraries sometimes store UTF-8 LYR while keeping
    # historical CUR offsets indexed by CP874 bytes. Decode the text and
    # restore the original CP874 byte granularity ONLY when the CUR entry
    # count supports it; never silently synthesize missing CUR positions.
    body = list(rows[4:])
    body_encoding="cp874"
    def count_positions(items):
        return sum(1+len(item) for item in items if item.strip())
    try:
        utf8_text=source_bytes.decode("utf-8-sig")
    except UnicodeError:
        utf8_text=None
    if utf8_text is not None and any(ord(ch)>127 for ch in utf8_text):
        utf8_rows=utf8_text.replace("\r\n","\n").replace("\r","\n").split("\n")
        native=[line.encode("utf-8") for line in utf8_rows[4:]]
        try:
            legacy=[line.encode("cp874") for line in utf8_rows[4:]]
        except UnicodeError:
            legacy=None
        # Exact byte count is necessary for a native Unicode cursor layout.
        # Converted legacy collections may still have surplus tail entries.
        if legacy is not None and (count_positions(native)==count_positions(legacy) or
              abs(len(positions)-count_positions(legacy))<=abs(len(positions)-count_positions(native))):
            body=legacy
            if count_positions(native)!=count_positions(legacy):
                warnings.append("UTF-8 Lyrics ใช้ CUR ตามจำนวนไบต์ CP874 ดั้งเดิม")
        elif len(positions)==count_positions(native):
            body=native
            body_encoding="utf-8"
        else:
            raise ValueError("UTF-8 LYR: cannot verify CUR alignment")
    if utf16 and len(positions)!=count_positions(body):
        raise ValueError("UTF-16 LYR: legacy CUR alignment cannot be verified")
    meta["cursorEncoding"]=body_encoding
    while body and not body[-1].strip(b" \x00\x1a"):
        body.pop()
    removed_footers = 0
    # Vendor credits in real Nick/eXtreme NCN collections can be decorated
    # with dots (e.g. ".....เต่า คาราโอเกะ......"). Never remove an internal
    # credit or an actual lyric with its own CUR positions.
    footer = re.compile(
        r"^(?:nick[\s_-]*karaoke(?:\s+professional)?|"
        r"นิค[\s_-]*คาราโอเกะ|เต่า[\s_-]*คาราโอเกะ)$", re.I)
    decorations = " \t.…·•*_-~=<>[]()"
    def needed(lines):
        return sum(1 + len(part) for part in lines if part.strip())
    # Only discard a recognizable *final* vendor-only credit if all preceding
    # lines have real CUR entries. Otherwise a short/damaged cursor remains
    # incomplete; never mislabel missing real lyrics as fully synchronized.
    while body and len(positions) < needed(body):
        candidate = body[-1].strip(b" \x00\x1a").decode(body_encoding, errors="replace")
        candidate = candidate.strip(decorations)
        if not footer.fullmatch(candidate) or len(positions) < needed(body[:-1]):
            break
        body.pop()
        removed_footers += 1
        while body and not body[-1].strip(b" \x00\x1a"):
            body.pop()

    # In some legacy NCN variants a visually blank LYR row consumes its
    # own CUR newline entry. Detect this only from an exact CUR count,
    # otherwise keep the established nonblank-line convention.
    blanks=sum(1 for part in body if not part.strip())
    blank_markers=(blanks>0 and len(positions)==needed(body)+blanks)
    if blank_markers:
        warnings.append("CUR มีตำแหน่งบรรทัดว่างตามต้นฉบับ")
    division, tempo_map, events, midi_duration = midi_events(
        Path(companions["midi"]), include_duration=True)
    for field,value in midi_metadata(events).items():
        if not meta.get(field) and value: meta[field]=value
    rendered = []
    previous_pos = 0
    cursor_index = 0
    timing_incomplete = False
    stop_song = False
    for raw_line in body:
        if not raw_line.strip():
            if blank_markers and cursor_index<len(positions):
                cursor_index+=1
            continue
        chars = []
        text_parts = []
        # Use the *original source bytes* to preserve NCN Cursor alignment.
        cursor_index += 1  # one NCN line marker
        for char in raw_line.decode(body_encoding, errors="replace"):
            width=len(char.encode(body_encoding, errors="replace"))
            if cursor_index+width > len(positions):
                timing_incomplete = True
                break
            position = positions[cursor_index]
            # A native UTF-8 cue group is only accepted when every byte
            # carries the same verified onset. No per-byte glyph corruption.
            if width>1 and any(value!=position for value in positions[cursor_index:cursor_index+width]):
                raise ValueError("UTF-8 LYR: ambiguous multi-byte CUR positions")
            cursor_index += width
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
    raw = Path(midi).read_bytes()
    # Most ordinary MIDI files only contain notes. Avoid parsing every note
    # event for thousands of tracks that have no text/lyric meta-event at all.
    # This is only a fast negative filter: real candidates still use the full
    # validated event parser, and embedded lyric timings are never guessed.
    if b"\xff\x01" not in raw and b"\xff\x05" not in raw:
        raise ValueError("ไฟล์ MIDI/KAR ไม่มีเหตุการณ์เนื้อร้องที่ฝังอยู่")
    division, tempo_map, events = midi_events(midi, raw_data=raw)
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
