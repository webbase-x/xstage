"""Persistent MIDI-to-XSK outcome review and verified output index.

Kept in the selected XStageSong/DB, not the PC application install folder.
All input and output media remain unchanged; retry queues are read-only until
the existing authenticated XSK builder processes each selected source.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path

STATUSES = {"completed", "duplicate", "not_ready", "error"}
FILTERS = STATUSES | {"all"}
PAGE_SIZE = 50
MEDIA_EXT = {".mid", ".midi", ".kar"}


def canonical(path):
    value = str(Path(path).expanduser().resolve())
    return value.casefold() if os.name == "nt" else value


def connect(root):
    folder = Path(root) / "DB"
    if folder.is_symlink():
        raise ValueError("โฟลเดอร์ DB ไม่ปลอดภัย")
    folder.mkdir(parents=True, exist_ok=True)
    filename = folder / "xsk-review.sqlite3"
    if filename.is_symlink():
        raise ValueError("ไฟล์ประวัติ XSK ไม่ปลอดภัย")
    database = sqlite3.connect(filename, timeout=30)
    database.execute("""CREATE TABLE IF NOT EXISTS outcomes(
      source_path TEXT PRIMARY KEY,
      source_root TEXT NOT NULL,
      signature TEXT NOT NULL,
      status TEXT NOT NULL,
      reason TEXT NOT NULL DEFAULT '',
      digest TEXT NOT NULL DEFAULT '',
      output_path TEXT NOT NULL DEFAULT '',
      updated_at REAL NOT NULL
    )""")
    database.execute("""CREATE INDEX IF NOT EXISTS ix_xsk_review_source
      ON outcomes(source_root,status,updated_at)""")
    database.execute("""CREATE TABLE IF NOT EXISTS verified_packages(
      output_path TEXT PRIMARY KEY,
      size INTEGER NOT NULL,
      mtime_ns INTEGER NOT NULL,
      digest TEXT NOT NULL,
      song_code TEXT NOT NULL
    )""")
    return database


def signature(path):
    """Cheap unchanged-file detector, including same-stem timed lyric sidecars.

    This never substitutes for SHA-256 on newly created or unverified XSKs.
    """
    media = Path(path)
    candidates = [media]
    for suffix in (".json", ".lrc", ".lyr", ".cur"):
        candidates.append(media.with_suffix(suffix))
    for dirname in ("LYRICS", "LYR", "CUR"):
        for base in (media.parent, media.parent.parent):
            if base.name.casefold() == "song":
                candidates.append(base.parent / dirname / (media.stem + ".json"))
                candidates.append(base.parent / dirname / (media.stem + ".lrc"))
                candidates.append(base.parent / dirname / (media.stem + ".lyr"))
                candidates.append(base.parent / dirname / (media.stem + ".cur"))
    entries = []
    for candidate in dict.fromkeys(candidates):
        try:
            stat = candidate.stat()
            if candidate.is_file() and not candidate.is_symlink():
                entries.append((canonical(candidate), stat.st_size, stat.st_mtime_ns))
        except FileNotFoundError:
            continue
    return json.dumps(sorted(entries), ensure_ascii=False, separators=(",", ":"))


def lookup(database, media):
    return database.execute(
        "SELECT signature,status,digest,output_path FROM outcomes WHERE source_path=?",
        (canonical(media),)
    ).fetchone()


def record(database, media, source_root, *, signature_value,
           status, reason="", digest="", output_path=""):
    if status not in STATUSES:
        raise ValueError("สถานะ XSK ไม่ถูกต้อง")
    database.execute(
        """INSERT INTO outcomes
        (source_path,source_root,signature,status,reason,digest,output_path,updated_at)
        VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(source_path) DO UPDATE SET
          source_root=excluded.source_root,signature=excluded.signature,
          status=excluded.status,reason=excluded.reason,digest=excluded.digest,
          output_path=excluded.output_path,updated_at=excluded.updated_at""",
        (canonical(media), canonical(source_root), signature_value,
         status, reason[:500], digest, canonical(output_path) if output_path else "",
         time.time()))


def verified(database, media):
    path = Path(media)
    row = database.execute(
        "SELECT size,mtime_ns,digest,song_code FROM verified_packages WHERE output_path=?",
        (canonical(path),)
    ).fetchone()
    if row and path.is_file() and not path.is_symlink():
        st = path.stat()
        if st.st_size == row[0] and st.st_mtime_ns == row[1]:
            return row[2], row[3]
    return None


def store_verified(database, media, digest, song_code):
    path = Path(media)
    stat = path.stat()
    database.execute(
        """INSERT INTO verified_packages(output_path,size,mtime_ns,digest,song_code)
        VALUES(?,?,?,?,?) ON CONFLICT(output_path) DO UPDATE SET
        size=excluded.size,mtime_ns=excluded.mtime_ns,
        digest=excluded.digest,song_code=excluded.song_code""",
        (canonical(path), stat.st_size, stat.st_mtime_ns, digest, song_code))


def page(root, source_root, *, status="all", offset=0, limit=PAGE_SIZE):
    if status not in FILTERS:
        raise ValueError("ตัวกรองรายการ XSK ไม่ถูกต้อง")
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("ช่วงข้อมูลไม่ถูกต้อง")
    with closing(connect(root)) as database:
        base = " WHERE source_root=?"
        args = [canonical(source_root)]
        counts = dict(database.execute(
            "SELECT status,COUNT(*) FROM outcomes" + base + " GROUP BY status", args).fetchall())
        if status != "all":
            base += " AND status=?"
            args.append(status)
        total = database.execute("SELECT COUNT(*) FROM outcomes" + base, args).fetchone()[0]
        rows = database.execute(
            "SELECT source_path,status,reason,updated_at FROM outcomes" + base +
            " ORDER BY updated_at DESC,source_path LIMIT ? OFFSET ?",
            [*args, limit, offset]).fetchall()
    return {"items": [{"path": path, "name": Path(path).name,
                       "status": state, "reason": reason, "updatedAt": updated}
                      for path, state, reason, updated in rows],
            "total": total, "offset": offset, "limit": limit,
            "counts": {name: counts.get(name, 0) for name in STATUSES}}


def pending_rows(root, source_root, *, cancelled=None):
    """Only retry recorded NOT_READY/ERR paths; no full source scan."""
    root_source = Path(source_root).expanduser().resolve()
    if not root_source.is_dir() or root_source.is_symlink():
        raise ValueError("ไม่พบโฟลเดอร์ MIDI ต้นทาง")
    with closing(connect(root)) as database:
        pending = [p for (p,) in database.execute(
            "SELECT source_path FROM outcomes WHERE source_root=? "
            "AND status IN ('not_ready','error') ORDER BY source_path",
            (canonical(root_source),))]
    def rows():
        for item in pending:
            if cancelled is not None and cancelled.is_set():
                raise RuntimeError("ผู้ใช้ยกเลิกการทบทวน XSK")
            path = Path(item)
            if not path.is_relative_to(root_source):
                continue
            yield {"path": str(path), "code": path.stem, "title": path.stem,
                   "artist": "", "kind": path.suffix.lstrip(".").upper()}
    return rows(), len(pending)
