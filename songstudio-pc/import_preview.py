"""Read-only song previews for both import destinations.

Online import previews local selected upload folder; PC import previews the
generated Song Studio source library (not the destination). Never uploads,
writes media, or attempts to browse a user's private Google Drive.
"""
from __future__ import annotations

import json
from pathlib import Path

AUDIO = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".oga", ".wma",
         ".mp4", ".webm", ".avi", ".mpg", ".mpeg", ".dat", ".vob", ".mkv",
         ".mov", ".wmv", ".flv"}
MIDI = {".mid", ".midi", ".kar"}


def _catalog_items(root, records, export):
    out = []
    for record in records:
        audio = record.get("audio") or {}
        lyrics = record.get("lyrics") or {}
        try:
            source = export.safe_media_path(root, audio["path"], "audio")
            if not source.is_file() or source.is_symlink():
                continue
            suffix = source.suffix.lower()
            if suffix not in AUDIO | MIDI:
                continue
            lyric = None
            if lyrics.get("path"):
                lyric = export.safe_media_path(root, lyrics["path"], "lyrics")
                if not lyric.is_file() or lyric.is_symlink():
                    lyric = None
            out.append({"code": str(record.get("code") or source.stem),
                        "title": str(record.get("title") or source.stem),
                        "artist": str(record.get("artist") or ""),
                        "kind": suffix.lstrip(".").upper(),
                        "audio": source, "lyrics": lyric,
                        "status": "พร้อมพรีวิว" if lyric else "ไม่มี Lyrics JSON"})
        except (KeyError, ValueError, OSError, TypeError, AttributeError):
            continue
    return out


def scan(kind, folder, workspace, export, folder_upload, ncn):
    if kind == "pc":
        root = export.songs_root(workspace)
        # Uses durable published records. Does not require selecting a
        # destination or opening the Karaoke PC database.
        return _catalog_items(root, export.existing_records(root), export)
    if kind != "online":
        raise ValueError("ประเภทเมนูพรีวิวไม่ถูกต้อง")
    library = folder_upload.existing_local_catalog(folder, export)
    if library is not None:
        return _catalog_items(library["root"], library["rows"], export)
    indexed = folder_upload.scan(folder, ncn=ncn)
    entries = []
    for item in indexed["complete"]:
        files = [Path(path) for path, _ in item["files"]]
        source = next((path for path in files if path.suffix.lower() in AUDIO | MIDI), None)
        if source is None or not source.is_file() or source.is_symlink():
            continue
        lyric = next((path for path in files if path.suffix.lower() == ".lrc"), None)
        entries.append({"code": source.stem, "title": source.stem,
                        "artist": "", "kind": item["kind"], "audio": source,
                        "lyrics": lyric, "status": ("พร้อมพรีวิว" if lyric else
                          "เนื้อร้องจาก KAR/NCN ต้องอ่านต้นฉบับ")})
    return entries


def page(items, search="", offset=0, limit=50):
    search = str(search).casefold().strip()
    matching = [item for item in items if not search or
                any(search in str(item.get(key, "")).casefold()
                    for key in ("code", "title", "artist", "kind"))]
    offset = max(0, offset)
    limit = max(1, min(100, limit))
    return {"total": len(matching), "rows": [
        {"id": items.index(item), "code": item["code"], "title": item["title"],
         "artist": item["artist"], "kind": item["kind"], "status": item["status"]}
        for item in matching[offset:offset+limit]]}


def lyrics(item, export, ncn):
    lyric = item.get("lyrics")
    if lyric and lyric.is_file() and not lyric.is_symlink():
        if lyric.stat().st_size > 3_000_000:
            raise ValueError("เนื้อร้องใหญ่ผิดปกติ")
        if lyric.suffix.lower() == ".json":
            doc = json.loads(lyric.read_text(encoding="utf-8-sig"))
        else:
            doc = export.lrc_to_json(lyric.read_text(encoding="utf-8-sig"),
                                     item["code"])
    elif item["audio"].suffix.lower() == ".kar":
        doc = ncn.kar_document(item["audio"], item["code"])
    else:
        return {"lines": [], "status": "ไม่มีเนื้อร้องพร้อมเวลาที่อ่านได้ในพรีวิว"}
    lines = doc.get("lines") or []
    if not isinstance(lines, list):
        raise ValueError("โครงสร้างเนื้อร้องไม่ถูกต้อง")
    clean = []
    for row in lines[:2000]:
        if (isinstance(row, dict) and isinstance(row.get("text"), str)
                and isinstance(row.get("startTime"), (int, float))):
            clean.append({"text": row["text"], "startTime": row["startTime"],
                          "endTime": row.get("endTime", row["startTime"]+3)})
    return {"lines": clean, "status": f"พบ {len(clean)} บรรทัดพร้อมเวลา"}
