"""Read Song Studio Plus X-Media v1 containers without changing legacy files."""
from __future__ import annotations

import hashlib
import math
import os
import struct
import tempfile
from pathlib import Path

MAGIC = b"XSTGPLS1"
VERSION = 1
HEADER = struct.Struct("<8sIQQ32s32s")
HEADER_BYTES = HEADER.size
MAX_METADATA = 32 * 1024 * 1024
MAX_TEXT = 1024 * 1024

FORMAT_MAP = {
    ".xmid": ("MIDI", ".mid"),
    ".xmp3": ("AUDIO", ".mp3"), ".xm4a": ("AUDIO", ".m4a"),
    ".xwav": ("AUDIO", ".wav"), ".xaac": ("AUDIO", ".aac"),
    ".xflac": ("AUDIO", ".flac"), ".xogg": ("AUDIO", ".ogg"),
    ".xoga": ("AUDIO", ".oga"), ".xwma": ("AUDIO", ".wma"),
    ".xmp4": ("VIDEO", ".mp4"), ".xwebm": ("VIDEO", ".webm"),
    ".xmkv": ("VIDEO", ".mkv"), ".xavi": ("VIDEO", ".avi"),
    ".xmpg": ("VIDEO", ".mpg"), ".xmpeg": ("VIDEO", ".mpeg"),
    ".xdat": ("VIDEO", ".dat"), ".xvob": ("VIDEO", ".vob"),
    ".xmov": ("VIDEO", ".mov"), ".xwmv": ("VIDEO", ".wmv"),
    ".xflv": ("VIDEO", ".flv"),
}
XMEDIA_EXT = frozenset(FORMAT_MAP)
XMEDIA_MIDI_EXT = frozenset(k for k, v in FORMAT_MAP.items() if v[0] == "MIDI")
XMEDIA_AUDIO_EXT = frozenset(k for k, v in FORMAT_MAP.items() if v[0] == "AUDIO")
XMEDIA_VIDEO_EXT = frozenset(k for k, v in FORMAT_MAP.items() if v[0] == "VIDEO")


def inner_extension(path):
    try:
        return FORMAT_MAP[Path(path).suffix.casefold()][1]
    except KeyError as error:
        raise ValueError("ยังไม่รองรับนามสกุล X-Media นี้") from error


def media_kind(path):
    try:
        return FORMAT_MAP[Path(path).suffix.casefold()][0]
    except KeyError as error:
        raise ValueError("ยังไม่รองรับนามสกุล X-Media นี้") from error


def _read_exact(stream, count, label="X-Media"):
    data = stream.read(count)
    if len(data) != count:
        raise ValueError(f"{label} ถูกตัดหรือขนาดไม่ถูกต้อง")
    return data


def _decode_metadata(data):
    view = memoryview(data)
    at = 0

    def take(count):
        nonlocal at
        if count < 0 or at + count > len(view):
            raise ValueError("X-Media metadata ถูกตัดหรือขนาดไม่ถูกต้อง")
        block = view[at:at + count]
        at += count
        return block

    def u32():
        return struct.unpack("<I", take(4))[0]

    def f64():
        value = struct.unpack("<d", take(8))[0]
        if not math.isfinite(value):
            raise ValueError("X-Media metadata มีเวลาที่ไม่ใช่ตัวเลข")
        return value

    def text():
        size = u32()
        if size > MAX_TEXT:
            raise ValueError("X-Media metadata มีข้อความยาวเกินขอบเขต")
        try:
            return bytes(take(size)).decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("X-Media metadata ไม่ใช่ UTF-8 ที่สมบูรณ์") from error

    song_id, code, version_id, title, artist, timing_status = [text() for _ in range(6)]
    count = u32()
    if count > 100000:
        raise ValueError("X-Media มีบรรทัดเนื้อร้องมากเกินขอบเขต")
    lines = []
    previous = -1.0
    for _ in range(count):
        start, end, value, line_status = f64(), f64(), text(), text()
        if start < 0 or end < start or start < previous:
            raise ValueError("X-Media มีเวลาเนื้อร้องไม่ถูกต้องหรือย้อนหลัง")
        previous = start
        cue_count = u32()
        if cue_count > 200000:
            raise ValueError("X-Media มีจุดปาดสีมากเกินขอบเขต")
        syllables, cue_previous = [], -1.0
        for _ in range(cue_count):
            cue_start, duration, glyph = f64(), f64(), text()
            if cue_start < 0 or duration < 0 or cue_start < cue_previous:
                raise ValueError("X-Media มีเวลาปาดสีไม่ถูกต้องหรือย้อนหลัง")
            cue_previous = cue_start
            syllables.append({"start": cue_start, "duration": duration, "text": glyph})
        lines.append({"startTime": start, "endTime": end, "text": value,
                      "timingStatus": line_status, "syllables": syllables})
    if at != len(view):
        raise ValueError("X-Media metadata มีข้อมูลส่วนเกินที่ไม่รู้จัก")
    return {"schemaVersion": 1, "songId": song_id, "songCode": code,
            "lyricsVersionId": version_id, "title": title, "artist": artist,
            "timingStatus": timing_status, "audioOffsetMs": 0, "lines": lines}


def inspect_xmedia(path):
    path = Path(path)
    if path.suffix.casefold() not in XMEDIA_EXT or path.is_symlink() or not path.is_file():
        raise ValueError("ไฟล์ X-Media ไม่ถูกต้องหรือไม่รองรับ")
    size = path.stat().st_size
    if size < HEADER_BYTES:
        raise ValueError("X-Media มีขนาดไม่สมบูรณ์")
    with path.open("rb") as source:
        magic, version, metadata_size, media_size, media_sha, metadata_sha = HEADER.unpack(
            _read_exact(source, HEADER_BYTES))
        if magic != MAGIC:
            raise ValueError("X-Media magic ไม่ถูกต้อง")
        if version != VERSION:
            raise ValueError(f"X-Media version {version} ยังไม่รองรับ")
        if not 4 <= metadata_size <= MAX_METADATA:
            raise ValueError("X-Media metadata มีขนาดผิดปกติ")
        media_offset = HEADER_BYTES + metadata_size
        if media_offset + media_size != size:
            raise ValueError("X-Media ขนาดไฟล์ไม่ตรงกับ header")
        metadata = _read_exact(source, metadata_size, "X-Media metadata")
    if hashlib.sha256(metadata).digest() != metadata_sha:
        raise ValueError("X-Media metadata SHA-256 ไม่ตรงกัน")
    document = _decode_metadata(metadata)
    return {"document": document, "code": document["songCode"],
            "title": document["title"], "artist": document["artist"],
            "media_offset": media_offset, "media_bytes": media_size,
            "media_sha256": media_sha.hex(), "metadata_sha256": metadata_sha.hex(),
            "kind": media_kind(path), "inner_extension": inner_extension(path),
            "format": path.suffix[1:].upper()}


def _stream_media(path, info, output=None):
    digest = hashlib.sha256()
    remaining = info["media_bytes"]
    with Path(path).open("rb") as source:
        source.seek(info["media_offset"])
        while remaining:
            block = source.read(min(4 * 1024 * 1024, remaining))
            if not block:
                raise ValueError("X-Media media ถูกตัด")
            digest.update(block)
            if output is not None:
                output.write(block)
            remaining -= len(block)
    if digest.hexdigest() != info["media_sha256"]:
        raise ValueError("X-Media media SHA-256 ไม่ตรงกัน")
    return digest.hexdigest()


def read_midi_payload(path):
    info = inspect_xmedia(path)
    if info["kind"] != "MIDI":
        raise ValueError("X-Media นี้ไม่ใช่ MIDI")
    if info["media_bytes"] > 64 * 1024 * 1024:
        raise ValueError("MIDI ภายใน X-Media ใหญ่เกิน 64 MB")
    with Path(path).open("rb") as source:
        source.seek(info["media_offset"])
        payload = _read_exact(source, info["media_bytes"], "X-Media MIDI")
    if hashlib.sha256(payload).hexdigest() != info["media_sha256"]:
        raise ValueError("X-Media media SHA-256 ไม่ตรงกัน")
    return payload, info["document"]


def materialize_media(path, cache_dir):
    """Verify and expose embedded audio/video at a stable private cache path."""
    path = Path(path)
    info = inspect_xmedia(path)
    if info["kind"] == "MIDI":
        raise ValueError("MIDI X-Media ไม่ต้องแตกไฟล์สำหรับ MediaPlayer")
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (info["media_sha256"] + info["inner_extension"])
    if target.is_file() and not target.is_symlink() and target.stat().st_size == info["media_bytes"]:
        with target.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest == info["media_sha256"]:
            return target, info["document"]
    fd, name = tempfile.mkstemp(prefix=".xmedia-", suffix=".tmp", dir=cache)
    os.close(fd)
    stage = Path(name)
    try:
        with stage.open("wb") as output:
            _stream_media(path, info, output)
            output.flush()
            os.fsync(output.fileno())
        if stage.stat().st_size != info["media_bytes"]:
            raise ValueError("X-Media media ที่แตกออกมามีขนาดไม่ครบ")
        stage.replace(target)
    finally:
        stage.unlink(missing_ok=True)
    return target, info["document"]
