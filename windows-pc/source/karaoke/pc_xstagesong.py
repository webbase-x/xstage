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
from .xmedia_reader import XMEDIA_EXT, inspect_xmedia, media_kind

FORMAT = "xstage-pc-local-current"
CATALOG = "xstage-pc-local-catalog"
MEDIA = {".mid", ".midi", ".kar", ".m4a", ".mp3", ".wav", ".wma",
         ".mp4", ".avi", ".mpg", ".mpeg", ".wmv", ".mkv", ".mov",
         ".flac", ".ogg", ".oga", ".aac", ".webm", ".dat", ".vob", ".flv", ".xsk"} | set(XMEDIA_EXT)


def library_root(selected):
    path = Path(selected).expanduser().resolve()
    if path.name.casefold() == "db" and (path / "xstage_plus.sqlite3").is_file():
        path = path.parent
    if (path / "DB" / "xstage_plus.sqlite3").is_file():
        return path
    if path.name.casefold() == "audio":
        path = path.parent
    elif path.name.casefold() == "lyrics":
        path = path.parent
    if path.name.casefold() != "xstagesong":
        path = path / "XStageSong"
    if not (path / "LYRICS").is_dir() or not any(
            (path / folder).is_dir() for folder in ("AUDIO", "VIDEO", "MIDI")):
        raise ValueError("ไม่พบ XStageSong แบบเดิม หรือ workspace Song Studio Plus ที่มี DB/xstage_plus.sqlite3")
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
    if (root / "DB" / "xstage_plus.sqlite3").is_file():
        from .plus_catalog import discover
        discovered, warnings = discover(root)
        if warnings and not discovered:
            raise ValueError("; ".join(warnings))
        rows = []
        for path, hint in discovered:
            if cancelled and cancelled.is_set():
                raise RuntimeError("ยกเลิกการนำเข้า Song Studio Plus แล้ว")
            rows.append({"path": str(path), "code": str(hint.get("code") or ""),
                         "title": str(hint.get("title") or path.stem),
                         "artist": str(hint.get("artist") or ""),
                         "kind": str(hint.get("kind") or "AUDIO"),
                         "format": str(hint.get("format") or path.suffix[1:].upper()),
                         "playable": 1, "first_lyric": str(hint.get("first_lyric") or ""),
                         "source_catalog": "Song Studio Plus SQLite"})
        return root, rows
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
            xmedia_ref = source.get("xmedia") if isinstance(source.get("xmedia"), dict) else None
            media_ref = (xmedia_ref or source.get("audio") or {}).get("path")
            prefix = media_ref.split("/", 1)[0] if isinstance(media_ref, str) else ""
            if prefix not in ("AUDIO", "VIDEO", "MIDI"):
                raise ValueError("Catalog อ้างถึงโฟลเดอร์สื่อที่ไม่รองรับ")
            path = _inside(root, media_ref, prefix)
            if not path.is_file() or path.suffix.casefold() not in MEDIA:
                raise ValueError("ไม่พบไฟล์เพลงที่ Catalog อ้างถึง: " + str(path))
            if str(path) in found:
                raise ValueError("พบไฟล์เพลงซ้ำใน Catalog")
            found.add(str(path))
            lyrics = source.get("lyrics")
            first = ""
            embedded = None
            if xmedia_ref:
                embedded = inspect_xmedia(path)["document"]
                first = " ".join(str(line.get("text") or "") for line in embedded.get("lines", [])[:8])[:512]
            if lyrics:
                lyric_rel = lyrics.get("path")
                lyric_root = lyric_rel.split("/", 1)[0] if isinstance(lyric_rel, str) else ""
                if lyric_root not in ("LYRICS", "AUDIO", "VIDEO", "MIDI") or (
                        lyric_root != "LYRICS" and "/LYRICS/" not in lyric_rel):
                    raise ValueError("พาธเนื้อร้องต้องอยู่ใน LYRICS ของประเภทเพลง")
                lyric_file = _inside(root, lyric_rel, lyric_root)
                if not lyric_file.is_file() or lyric_file.suffix.casefold() != ".json":
                    raise ValueError("ไม่พบ Lyrics JSON ของเพลง: " + path.name)
                doc = json.loads(lyric_file.read_text(encoding="utf-8-sig"))
                if doc.get("schemaVersion") != 1 or not isinstance(doc.get("lines"), list):
                    raise ValueError("Lyrics JSON ไม่ถูกต้อง: " + lyric_file.name)
                first = " ".join(str(line.get("text") or "") for line in doc["lines"][:8])[:512]
            ext = path.suffix.casefold()
            kind = (media_kind(path) if ext in XMEDIA_EXT else
                    "MIDI" if ext in {".mid", ".midi", ".kar"} else
                    "VIDEO" if ext in {".mp4", ".avi", ".mpg", ".mpeg", ".wmv", ".mkv", ".mov", ".webm", ".dat", ".vob", ".flv"} else
                    "AUDIO")
            rows.append({"path": str(path), "code": str((embedded or {}).get("songCode") or source.get("code") or ""),
                         "title": str((embedded or {}).get("title") or source.get("title") or path.stem),
                         "artist": str((embedded or {}).get("artist") or source.get("artist") or ""),
                         "kind": kind,
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
        category = next(p for p in path.parents if
                        p.name.casefold() in ("audio", "video", "midi") and
                        p.parent.name.casefold() == "xstagesong")
    except StopIteration:
        return None
    root = category.parent
    try:
        relative = path.relative_to(category)
    except ValueError:
        return None
    pointer = root / "LYRICS" / "current.json"
    selected = None
    if pointer.is_file():
        stamp = pointer.stat()
        index = _lyrics_by_media(str(pointer), stamp.st_mtime_ns, stamp.st_size)
        selected = index.get(path.relative_to(root).as_posix().casefold())
    if selected:
        prefix = selected.split("/", 1)[0]
        candidate = _inside(root, selected, prefix)
    else:
        # Accept directly copied format-local song/lyrics pairs, even when
        # the destination has no existing database pointer.
        parts = relative.parts
        if len(parts) >= 4 and parts[-3].casefold() == "song":
            candidate = category / Path(*parts[:-3]) / "LYRICS" / Path(*parts[-2:]).with_suffix(".json")
        elif len(parts) >= 3 and parts[-3].casefold() == "song":
            candidate = category / Path(*parts[:-3]) / "LYRICS" / Path(*parts[-2:]).with_suffix(".json")
        else:
            candidate = root / "LYRICS" / relative.with_suffix(".json")
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
