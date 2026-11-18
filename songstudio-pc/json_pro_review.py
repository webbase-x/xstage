"""Durable, local review queue for Song Studio Lyrics JSON exports.

Stored next to the existing XStageSong catalog; independent of application
install/version and never changes original media. Only verified catalog records
count as completed on resume. Error and duplicate rows remain reviewable.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path


def canonical(path):
    return str(Path(path).resolve()).casefold()


def signature(files):
    """Fast change detector for retry/cache; not a substitute for media SHA-256."""
    parts = []
    for path, _ in files:
        item = Path(path)
        stat = item.stat()
        parts.append((canonical(item), stat.st_size, stat.st_mtime_ns))
    return json.dumps(sorted(parts), ensure_ascii=False, separators=(",", ":"))


def connect(root):
    root = Path(root)
    folder = root / "DB"
    if folder.is_symlink():
        raise ValueError("โฟลเดอร์ DB ต้องไม่เป็น Symbolic Link")
    folder.mkdir(parents=True, exist_ok=True)
    filename = folder / "json-pro-review.sqlite3"
    if filename.is_symlink():
        raise ValueError("ไฟล์ประวัติ Lyrics JSON ต้องไม่เป็น Symbolic Link")
    db = sqlite3.connect(filename, timeout=30)
    db.execute("""CREATE TABLE IF NOT EXISTS json_pro_review (
        source_path TEXT NOT NULL,
        source_root TEXT NOT NULL,
        output_format TEXT NOT NULL,
        source_signature TEXT NOT NULL,
        status TEXT NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        identity TEXT NOT NULL DEFAULT '',
        updated_at REAL NOT NULL,
        PRIMARY KEY(source_path, output_format)
    )""")
    db.execute("""CREATE INDEX IF NOT EXISTS idx_json_pro_review_status
        ON json_pro_review(source_root, output_format, status, updated_at)""")
    return db


def lookup(db, media, output_format):
    return db.execute(
        "SELECT source_signature,status,identity FROM json_pro_review "
        "WHERE source_path=? AND output_format=?",
        (canonical(media), output_format),
    ).fetchone()


def record(db, *, media, source_root, output_format, source_signature,
           status, reason="", identity=""):
    if status not in ("completed", "duplicate", "error"):
        raise ValueError("สถานะรายการไม่ถูกต้อง")
    db.execute(
        """INSERT INTO json_pro_review
        (source_path,source_root,output_format,source_signature,status,reason,identity,updated_at)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(source_path,output_format) DO UPDATE SET
          source_root=excluded.source_root,
          source_signature=excluded.source_signature,
          status=excluded.status,
          reason=excluded.reason,
          identity=excluded.identity,
          updated_at=excluded.updated_at""",
        (canonical(media), canonical(source_root), output_format,
         source_signature, status, reason[:500], identity, time.time()),
    )


def review(root, source_root, output_format, *, status="all", offset=0, limit=50):
    if output_format not in ("original", "m4a", "mp3", "wav", "flac", "ogg"):
        raise ValueError("รูปแบบผลลัพธ์ไม่ถูกต้อง")
    if status not in ("all", "error", "duplicate", "completed"):
        raise ValueError("ตัวกรองรายการไม่ถูกต้อง")
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("ช่วงรายการไม่ถูกต้อง")
    with connect(root) as db:
        clause = "WHERE source_root=? AND output_format=?"
        args = [canonical(source_root), output_format]
        totals = dict(db.execute(
            "SELECT status,COUNT(*) FROM json_pro_review " + clause + " GROUP BY status", args
        ).fetchall())
        if status != "all":
            clause += " AND status=?"
            args.append(status)
        count = db.execute("SELECT COUNT(*) FROM json_pro_review " + clause, args).fetchone()[0]
        rows = db.execute(
            "SELECT source_path,status,reason,updated_at FROM json_pro_review "
            + clause + " ORDER BY updated_at DESC,source_path LIMIT ? OFFSET ?",
            [*args, limit, offset],
        ).fetchall()
        return {"items": [{"path": path, "name": Path(path).name,
                           "status": state, "reason": reason, "updatedAt": updated}
                          for path, state, reason, updated in rows],
                "total": count, "offset": offset, "limit": limit,
                "counts": {"completed": totals.get("completed", 0),
                           "duplicate": totals.get("duplicate", 0),
                           "error": totals.get("error", 0)}}


def retry_stream(source_folder, destination_folder, *, output_format, ncn=None,
                 progress=None, cancelled=None):
    """Enumerate recorded errors ONLY, never enumerate 70,000 successful files."""
    source = Path(source_folder).resolve()
    if not source.is_dir() or source.is_symlink():
        raise ValueError("ไม่พบโฟลเดอร์ต้นทาง")
    # The caller supplies songs_root. Import dynamically to avoid cycles.
    from importlib.util import spec_from_file_location, module_from_spec
    stream_path = Path(__file__).with_name("json_source_stream.py")
    spec = spec_from_file_location("xstage_review_source_stream", stream_path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    from_path = canonical(source)
    with connect(destination_folder) as db:
        sources = [name for (name,) in db.execute(
            "SELECT source_path FROM json_pro_review "
            "WHERE source_root=? AND output_format=? AND status='error' "
            "ORDER BY source_path", (from_path, output_format)
        )]
    report = {"complete": None, "incomplete": [], "unsupported": [],
              "fileCount": 0, "folderCount": 0, "total": 0,
              "incompleteCount": 0, "unsupportedCount": 0}
    def generate():
        for name in sources:
            if cancelled is not None and cancelled.is_set():
                raise RuntimeError("ยกเลิกการทบทวน ERR")
            media = Path(name)
            if not media.is_relative_to(source) or not media.is_file() or media.is_symlink():
                report["incompleteCount"] += 1
                if len(report["incomplete"]) < 50:
                    report["incomplete"].append({"name": media.name, "reason": "ไม่พบไฟล์ต้นฉบับ"})
                continue
            row, reason = module._source_row(source, media)
            report["fileCount"] += 1
            if row is None:
                report["incompleteCount"] += 1
                if len(report["incomplete"]) < 50:
                    report["incomplete"].append({"name": media.name, "reason": reason})
                continue
            report["total"] += 1
            if progress is not None:
                progress("validate", report["total"], len(sources))
            yield row
    report["complete"] = generate()
    return report
