"""Read Song Studio Plus xstage_* SQLite as an optional fast catalog hint source."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import quote

from .xmedia_reader import XMEDIA_EXT, media_kind


_REQUIRED = {"xstage_songs", "xstage_media", "xstage_lyric_versions",
             "xstage_lyric_lines", "xstage_exports"}


def locate_database(folder):
    folder = Path(folder)
    candidates = [
        folder / "DB" / "xstage_plus.sqlite3",
        folder / "xstage_plus.sqlite3" if folder.name.casefold() == "db" else None,
    ]
    for path in candidates:
        if path is not None and path.is_file() and not path.is_symlink():
            return path
    return None


def _root_for(database):
    return database.parent.parent if database.parent.name.casefold() == "db" else database.parent


def _safe_export(root, value):
    text = str(value or "").replace("\\", "/").strip()
    if not text or Path(text).is_absolute():
        return None
    root = root.resolve()
    target = (root / Path(text)).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    return target


def discover(folder, allowed=None):
    """Return [(path, metadata-hint)], warnings from a valid Plus database.

    The local Karaoke SQLite remains authoritative for user state/favorites.
    Plus SQLite is read-only and only seeds exported X-Media rows, so removing
    the Plus database never damages the established Karaoke catalog.
    """
    database = locate_database(folder)
    if database is None:
        return [], []
    root = _root_for(database)
    uri = "file:" + quote(str(database.resolve()).replace("\\", "/"), safe="/:") + "?mode=ro"
    warnings, result = [], []
    try:
        db = sqlite3.connect(uri, uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        names = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'xstage_%'")}
        missing = sorted(_REQUIRED - names)
        if missing:
            return [], ["ฐาน Song Studio Plus ยังไม่ครบ: " + ", ".join(missing)]
        rows = db.execute("""
          SELECT s.code,s.title,s.artist,e.output_path,e.sha256 AS export_sha,
                 v.id AS version_id,v.timing_status
          FROM xstage_exports e
          JOIN xstage_songs s ON s.id=e.song_id
          JOIN xstage_media m ON m.id=s.media_id
          JOIN xstage_lyric_versions v ON v.id=e.version_id
          WHERE v.is_current=1
          ORDER BY s.code
        """).fetchall()
        for row in rows:
            target = _safe_export(root, row["output_path"])
            if target is None:
                warnings.append("ข้าม path จากฐาน Plus ที่ออกนอก workspace: " + str(row["output_path"]))
                continue
            ext = target.suffix.casefold()
            if ext not in XMEDIA_EXT or (allowed is not None and ext not in allowed):
                continue
            if not target.is_file() or target.is_symlink():
                warnings.append("ฐาน Plus อ้างถึง X-Media ที่ไม่พบ: " + str(target))
                continue
            lyric = db.execute(
                "SELECT text FROM xstage_lyric_lines WHERE version_id=? ORDER BY position LIMIT 8",
                (row["version_id"],)).fetchall()
            result.append((target, {
                "code": str(row["code"]),
                "title": str(row["title"] or ""),
                "artist": str(row["artist"] or ""),
                "kind": media_kind(target),
                "format": ext[1:].upper(),
                "first_lyric": " ".join(str(item[0] or "") for item in lyric)[:512],
            }))
    except sqlite3.Error as error:
        warnings.append("อ่านฐาน Song Studio Plus ไม่สำเร็จ: " + str(error))
    finally:
        try:
            db.close()
        except Exception:
            pass
    return result, warnings
