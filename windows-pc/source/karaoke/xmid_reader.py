"""Reader for Song Studio Pro XSTGPLS1 embedded MIDI and timed lyrics."""
from __future__ import annotations

import hashlib
import math
import struct
from pathlib import Path

MAGIC = b"XSTGPLS1"
HEADER = struct.Struct("<8sIQQ32s32s")
MAX_METADATA = 32 * 1024 * 1024
MAX_MIDI = 64 * 1024 * 1024


def read_xmid(path):
    """Validate container and return embedded MIDI bytes and Studio metadata.

    Metadata SHA-256 is always checked. MIDI SHA-256 is checked as well, so
    corrupted files are rejected before they enter the library or player.
    """
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.suffix.casefold() != ".xmid":
        raise ValueError("ต้องเป็นไฟล์ .xmid ปกติ")
    with path.open("rb") as stream:
        header = stream.read(HEADER.size)
        if len(header) != HEADER.size:
            raise ValueError("ส่วนหัว XMID ไม่ครบ")
        magic, version, meta_len, media_len, media_hash, metadata_hash = HEADER.unpack(header)
        if magic != MAGIC or version != 1:
            raise ValueError("รูปแบบ XMID ไม่ตรงกับ Song Studio Pro v1")
        if not 0 < meta_len <= MAX_METADATA or not 0 < media_len <= MAX_MIDI:
            raise ValueError("ขนาด metadata หรือ MIDI ใน XMID ไม่ถูกต้อง")
        if path.stat().st_size != HEADER.size + meta_len + media_len:
            raise ValueError("ขนาดไฟล์ XMID ไม่ตรงกับส่วนหัว")
        payload = stream.read(meta_len)
        if hashlib.sha256(payload).digest() != metadata_hash:
            raise ValueError("SHA-256 ของเนื้อร้อง XMID ไม่ตรง")
        doc = decode_metadata(payload)
        media = stream.read(media_len)
        if hashlib.sha256(media).digest() != media_hash:
            raise ValueError("SHA-256 ของ MIDI XMID ไม่ตรง")
        if media[:4] not in (b"MThd", b"NCN1"):
            raise ValueError("XMID ไม่ได้บรรจุ MIDI ที่รองรับ")
        return media, doc


def decode_metadata(payload):
    raw = memoryview(payload)
    pos = 0

    def take(count):
        nonlocal pos
        if count < 0 or count > len(raw) - pos:
            raise ValueError("metadata XMID ถูกตัดหรือไม่สมบูรณ์")
        result = raw[pos:pos + count]
        pos += count
        return result

    def unpack(fmt):
        return struct.unpack(fmt, take(struct.calcsize(fmt)))[0]

    def text():
        length = unpack("<I")
        if length > 1024 * 1024:
            raise ValueError("ข้อความ XMID ใหญ่เกินกำหนด")
        return bytes(take(length)).decode("utf-8", "strict")

    song_id, code, version_id, title, artist, status = (text() for _ in range(6))
    count = unpack("<I")
    if count > 100000:
        raise ValueError("XMID มีบรรทัดเนื้อร้องเกินขอบเขต")
    lines = []
    for _ in range(count):
        start, end = struct.unpack("<dd", take(16))
        lyric, timing = text(), text()
        if not all(map(math.isfinite, (start, end))) or not 0 <= start < end:
            raise ValueError("เวลาบรรทัด XMID ไม่ถูกต้อง")
        cue_count = unpack("<I")
        if cue_count > 100000:
            raise ValueError("XMID มีจุดปาดสีมากเกินกำหนด")
        cues = []
        previous = -1.0
        for _ in range(cue_count):
            at, duration = struct.unpack("<dd", take(16))
            glyph = text()
            if (not all(map(math.isfinite, (at, duration))) or
                    at < start - .001 or at > end + .001 or
                    at < previous or duration < 0):
                raise ValueError("เวลาปาดสี XMID ไม่ถูกต้อง")
            previous = at
            cues.append({"startTime": at, "duration": duration, "text": glyph})
        lines.append({"text": lyric, "startTime": start, "endTime": end,
                      "timingStatus": timing, "cues": cues})
    if pos != len(raw):
        raise ValueError("มีข้อมูลส่วนเกินใน metadata XMID")
    return {"songId": song_id, "code": code, "lyricsVersionId": version_id,
            "title": title, "artist": artist, "timingStatus": status, "lines": lines}
