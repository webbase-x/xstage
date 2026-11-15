"""Connect user-selected offline XStageSong/AUDIO + LYRICS to Karaoke PC.

Reads the Song Studio export catalog without converting MIDI, rewriting media,
or contacting Google Drive. The existing Karaoke SQLite index remains the
single source of search/queue records.
"""
from __future__ import annotations
from functools import lru_cache
import json
from pathlib import Path
from .lyrics import Lyrics, LyricLine

FORMAT = "xstage-pc-local-current"
CATALOG = "xstage-pc-local-catalog"
MEDIA = {".mid", ".midi", ".kar", ".m4a", ".mp3", ".wav", ".wma",
         ".mp4", ".avi", ".mpg", ".mpeg", ".wmv", ".mkv", ".mov",
         ".flac", ".ogg", ".oga", ".aac"}


def library_root(selected):
    path = Path(selected).expanduser().resolve()
    if path.name.casefold() == "audio":
        path = path.parent
    elif path.name.casefold() == "lyrics":
        path = path.parent
    if path.name.casefold() != "xstagesong":
        path = path / "XStageSong"
    if not (path / "AUDIO").is_dir() or not (path / "LYRICS").is_dir():
        raise ValueError("ไม่พบโฟลเดอร์ XStageSong/AUDIO และ XStageSong/LYRICS ที่เลือก")
    return path


def _inside(root, relative, prefix):
    if (not isinstance(relative, str) or not relative.startswith(prefix + "/")
            or "\\" in relative or ":" in relative or "\0" in relative):
        raise ValueError("พาธข้อมูลคลัง XStageSong ไม่ถูกต้อง")
    parts = relative.split("/")
    if len(parts) < 3 or any(part in ("", ".", "..") for part in parts):
        raise ValueError("พบพาธไม่ปลอดภัยใน Catalog")
    candidate = root.joinpath(*parts)
    if candidate.is_symlink() or not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError("Catalog อ้างถึงไฟล์นอกคลังหรือ symbolic link")
    return candidate


def catalog_rows(selected, *, cancelled=None):
    root = library_root(selected)
    file = root / "LYRICS" / "current.json"
    if not file.is_file():
        raise ValueError("ไม่พบ XStageSong/LYRICS/current.json กรุณานำเข้าจาก Song Studio ก่อน")
    pointer = json.loads(file.read_text(encoding="utf-8-sig"))
    if pointer.get("format") != FORMAT or pointer.get("schemaVersion") != 1:
        raise ValueError("ฐานนี้ไม่ใช่ Catalog สำหรับ Karaoke PC (ไม่ใช่ Drive File-ID Catalog)")
    found = set()
    rows = []
    for meta in pointer.get("catalogFiles") or []:
        if cancelled and cancelled.is_set():
            raise RuntimeError("ยกเลิกการนำเข้า XStageSong แล้ว")
        name = str(meta.get("path") or "")
        if not name.startswith("catalog-pc-") or not name.endswith(".json") or "/" in name or "\\" in name:
            raise ValueError("ชื่อไฟล์ Catalog ไม่ปลอดภัย")
        catalog = json.loads((root / "LYRICS" / name).read_text(encoding="utf-8-sig"))
        if catalog.get("schemaVersion") != 1 or catalog.get("format") != CATALOG:
            raise ValueError("อ่าน Catalog เพลงไม่ผ่าน")
        songs = catalog.get("songs")
        if not isinstance(songs, list) or len(songs) != meta.get("songCount"):
            raise ValueError("จำนวนเพลงใน Catalog ไม่ตรงกับฐานข้อมูล")
        for source in songs:
            if cancelled and cancelled.is_set():
                raise RuntimeError("ยกเลิกการนำเข้า XStageSong แล้ว")
            path = _inside(root, (source.get("audio") or {}).get("path"), "AUDIO")
            if not path.is_file() or path.suffix.casefold() not in MEDIA:
                raise ValueError("ไม่พบไฟล์เพลงที่ Catalog อ้างถึง: " + str(path))
            if str(path) in found:
                raise ValueError("พบไฟล์เพลงซ้ำใน Catalog")
            found.add(str(path))
            lyrics = source.get("lyrics")
            first = ""
            if lyrics:
                lyric_file = _inside(root, lyrics.get("path"), "LYRICS")
                if not lyric_file.is_file() or lyric_file.suffix.casefold() != ".json":
                    raise ValueError("ไม่พบ Lyrics JSON ของเพลง: " + path.name)
                doc = json.loads(lyric_file.read_text(encoding="utf-8-sig"))
                if doc.get("schemaVersion") != 1 or not isinstance(doc.get("lines"), list):
                    raise ValueError("Lyrics JSON ไม่ถูกต้อง: " + lyric_file.name)
                first = " ".join(str(line.get("text") or "") for line in doc["lines"][:8])[:512]
            ext = path.suffix.casefold()
            rows.append({"path": str(path), "code": str(source.get("code") or ""),
                         "title": str(source.get("title") or path.stem),
                         "artist": str(source.get("artist") or ""),
                         "kind": "MIDI" if ext in {".mid", ".midi", ".kar"} else
                                 "VIDEO" if ext in {".mp4", ".avi", ".mov", ".mkv"} else "AUDIO",
                         "format": ext[1:].upper(), "playable": 1,
                         "first_lyric": first, "source_catalog": "XStageSong PC"})
    if len(rows) != pointer.get("songCount"):
        raise ValueError("จำนวนเพลงใน current.json ไม่ตรงกับ Catalog")
    return root, rows


def import_library(library, selected, *, cancelled=None):
    root, rows = catalog_rows(selected, cancelled=cancelled)
    if cancelled and cancelled.is_set():
        raise RuntimeError("ยกเลิกก่อนปรับดัชนีเพลง")
    # Preserve existing users' edits and favorites; update only these paths.
    count = library.upsert_catalog(rows, preserve_playable=True)
    return count, 0, []


@lru_cache(maxsize=8)
def _lyrics_by_media(pointer_name, modified_ns, byte_count):
    """Cache catalog-backed lyrics paths; timing corrections may use rev files."""
    pointer = Path(pointer_name)
    data = json.loads(pointer.read_text(encoding="utf-8-sig"))
    if data.get("format") != FORMAT or data.get("schemaVersion") != 1:
        raise ValueError("ฐานเนื้อร้อง Karaoke PC ไม่ถูกต้อง")
    mapping = {}
    for info in data.get("catalogFiles") or []:
        name = str(info.get("path") or "")
        if not name.startswith("catalog-pc-") or not name.endswith(".json") or "/" in name or "\\" in name:
            raise ValueError("ไฟล์ Catalog เนื้อร้องไม่ปลอดภัย")
        doc = json.loads((pointer.parent / name).read_text(encoding="utf-8-sig"))
        if doc.get("format") != CATALOG or doc.get("schemaVersion") != 1:
            raise ValueError("รูปแบบ Catalog เนื้อร้องไม่ถูกต้อง")
        for row in doc.get("songs") or []:
            audio = (row.get("audio") or {}).get("path")
            lyrics = (row.get("lyrics") or {}).get("path")
            if audio and lyrics:
                mapping[audio.casefold()] = lyrics
    return mapping


def source_lyrics(media_path):
    """Prefer actual timed JSON. Never fabricate per-character timestamps."""
    path = Path(media_path)
    try:
        audio = next(p for p in path.parents if p.name.casefold() == "audio"
                     and p.parent.name.casefold() == "xstagesong")
    except StopIteration:
        return None
    root = audio.parent
    try:
        relative = path.relative_to(audio)
    except ValueError:
        return None
    pointer = root / "LYRICS" / "current.json"
    selected = None
    if pointer.is_file():
        stamp = pointer.stat()
        index = _lyrics_by_media(str(pointer), stamp.st_mtime_ns, stamp.st_size)
        selected = index.get(path.relative_to(root).as_posix().casefold())
    candidate = (_inside(root, selected, "LYRICS") if selected else
                 root / "LYRICS" / relative.with_suffix(".json"))
    if not candidate.is_file() or candidate.is_symlink():
        return None
    doc = json.loads(candidate.read_text(encoding="utf-8-sig"))
    if doc.get("schemaVersion") != 1 or not isinstance(doc.get("lines"), list):
        raise ValueError("Lyrics JSON ของเพลงไม่ถูกต้อง")
    lines = []
    for value in doc["lines"]:
        text = str(value.get("text") or "")
        if not text:
            continue
        at = float(value["startTime"])
        if at < 0:
            raise ValueError("เวลา Lyrics JSON ติดลบ")
        syllables = value.get("syllables") or []
        words = [(float(part["start"]), str(part["text"]))
                 for part in syllables if isinstance(part, dict) and
                 "start" in part and "text" in part]
        lines.append(LyricLine(at, text, words))
    return Lyrics(lines, offset_ms=int(doc.get("audioOffsetMs") or 0))
