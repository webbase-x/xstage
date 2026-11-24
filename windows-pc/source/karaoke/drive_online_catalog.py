"""Read the *existing* Karaoke Online SQLite file from Google Drive for desktop.

The Online schema is deliberately different from Karaoke PC's local runtime
schema. Never pass it to SongLibrary (which runs DDL/WAL migrations).
This adapter opens DB/songs.sqlite3 read-only and never writes SQLite sidecars.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path, PurePosixPath

ROOT_NAME = "XStageKaraoke"
FORMAT = "xstage-sqlite3-v1"
MAX_ROWS = 200


def shared_root(value):
    root = Path(value).expanduser()
    if root.name == "DB":
        root = root.parent
    if not root.is_dir() or root.is_symlink() or root.name != ROOT_NAME:
        raise ValueError("เลือกโฟลเดอร์ XStageKaraoke ที่ซิงก์กับ Google Drive for desktop")
    root = root.resolve(strict=True)
    required = ("SONGS", "SOUNDFONT", "DB")
    if any(not (root / item).is_dir() or (root / item).is_symlink() for item in required):
        raise ValueError("คลัง Google Drive ต้องมี SONGS, SOUNDFONT และ DB")
    db = root / "DB" / "songs.sqlite3"
    if not db.is_file() or db.is_symlink():
        raise ValueError("ยังไม่มี DB/songs.sqlite3 บน Google Drive PC ห้ามสร้างฐานว่างแทน")
    return root


def _open_read_only(root):
    db_path = root / "DB" / "songs.sqlite3"
    db = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    db.execute("PRAGMA trusted_schema=OFF")
    return db


def _validate(db):
    metadata = dict(db.execute("SELECT key,value FROM catalog_meta"))
    if metadata.get("format") != FORMAT or metadata.get("kind") != "snapshot" or metadata.get("schemaVersion") != "1":
        raise ValueError("ฐาน SQLite ไม่ตรงรูปแบบ Karaoke Online ที่รองรับ ไม่แก้ไขฐานอัตโนมัติ")
    columns = {row[1] for row in db.execute("PRAGMA table_info(songs)")}
    required = {"web_song_id", "code", "title", "artist", "source_format",
                "original_relative_path", "payload"}
    if not required.issubset(columns):
        raise ValueError("SQLite Online ไม่มีคอลัมน์จำเป็นครบ ไม่เปลี่ยนโครงสร้างฐาน")
    if db.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
        raise ValueError("ฐานเพลง SQLite ไม่ผ่านการตรวจความสมบูรณ์")


def summary(root_value):
    root = shared_root(root_value)
    with _open_read_only(root) as db:
        _validate(db)
        amount = db.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
        duplicates = 0
        columns = {row[1] for row in db.execute("PRAGMA table_info(songs)")}
        if "midi_md5" in columns:
            duplicates = db.execute(
                "SELECT COUNT(*) FROM (SELECT midi_md5 FROM songs "
                "WHERE midi_md5 IS NOT NULL GROUP BY midi_md5 HAVING COUNT(*)>1)"
            ).fetchone()[0]
    return {"root": str(root), "database": str(root / "DB" / "songs.sqlite3"),
            "songs": amount, "duplicate_midi_groups": duplicates, "read_only": True}


def _local_media(root, relative):
    """Resolve exact Online relative location, never guess by song title/code."""
    if not isinstance(relative, str) or not relative.strip():
        return None
    normalized = relative.replace(chr(92), "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in (".", "..") for part in path.parts):
        return None
    parts = list(path.parts)
    if parts and parts[0].upper() == "SONGS":
        parts.pop(0)
    if not parts or any(":" in part for part in parts):
        return None
    songs = root / "SONGS"
    candidate = songs.joinpath(*parts)
    try:
        resolved = candidate.resolve(strict=True)
        if songs.resolve(strict=True) not in resolved.parents:
            return None
        if resolved.is_file() and not candidate.is_symlink():
            return str(resolved)
    except (OSError, RuntimeError):
        pass
    return None


def search(root_value, term="", limit=100):
    root = shared_root(root_value)
    limit = max(1, min(MAX_ROWS, int(limit)))
    term = str(term or "").strip()[:120]
    with _open_read_only(root) as db:
        _validate(db)
        if term:
            escaped = term.replace(chr(92), chr(92) * 2).replace("%", chr(92) + "%").replace("_", chr(92) + "_")
            pattern = "%" + escaped + "%"
            rows = db.execute(
                "SELECT web_song_id,code,title,artist,source_format,original_relative_path "
                "FROM songs WHERE code LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\' "
                "OR artist LIKE ? ESCAPE '\\' ORDER BY title COLLATE NOCASE LIMIT ?",
                (pattern, pattern, pattern, limit)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT web_song_id,code,title,artist,source_format,original_relative_path "
                "FROM songs ORDER BY title COLLATE NOCASE LIMIT ?", (limit,)
            ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["local_path"] = _local_media(root, item["original_relative_path"])
        result.append(item)
    return result


def duplicate_report(root_value):
    """Read-only duplicate report; no deletion or destructive deduplication."""
    root = shared_root(root_value)
    with _open_read_only(root) as db:
        _validate(db)
        columns = {row[1] for row in db.execute("PRAGMA table_info(songs)")}
        if "midi_md5" not in columns:
            return []
        return [dict(row) for row in db.execute(
            "SELECT midi_md5,COUNT(*) AS copies FROM songs WHERE midi_md5 IS NOT NULL "
            "GROUP BY midi_md5 HAVING COUNT(*)>1 ORDER BY copies DESC LIMIT 100"
        )]
