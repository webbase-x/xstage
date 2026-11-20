"""Opt-in, crash-safe maintenance for X-Stage Song Studio Plus SQLite.

Never removes media, registered songs, lyric text/cues, manual edits or exports.
Only completed import audit/checkpoint rows can be pruned.
"""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
import plus_core as core

ISSUE_OUTCOMES = (
    "error", "lyrics-error", "timing-incomplete", "partial-lyrics",
    "untimed-lyrics", "missing-lyr", "skipped-ncn-incomplete",
)
RETAIN_COMPLETED = 4


def snapshot(workspace):
    """Read-only space and catalog counters; never scan original media."""
    core.init(workspace)
    path = core.db_path(workspace)
    with core.connect(workspace) as db:
        page_size = db.execute("PRAGMA page_size").fetchone()[0]
        page_count = db.execute("PRAGMA page_count").fetchone()[0]
        free_pages = db.execute("PRAGMA freelist_count").fetchone()[0]
        names = (
            ("songs", "xstage_songs"),
            ("media", "xstage_media"),
            ("sources", "xstage_media_sources"),
            ("lyrics_versions", "xstage_lyric_versions"),
            ("lyric_lines", "xstage_lyric_lines"),
            ("lyric_cues", "xstage_lyric_cues"),
            ("import_batches", "xstage_import_batches"),
            ("import_items", "xstage_import_items"),
            ("checkpoints", "xstage_import_file_checkpoints"),
        )
        counts = {key: db.execute("SELECT count(*) FROM " + table).fetchone()[0]
                  for key, table in names}
        completed = db.execute("""SELECT count(*) FROM xstage_import_batches
            WHERE status='completed'""").fetchone()[0]
        resumable = db.execute("""SELECT count(*) FROM xstage_import_resume_state
            WHERE status IN ('cancelled','interrupted','running')""").fetchone()[0]
        failures = db.execute("""SELECT count(*) FROM xstage_import_items
            WHERE outcome IN (""" + ",".join("?" for _ in ISSUE_OUTCOMES) + ")",
            ISSUE_OUTCOMES).fetchone()[0]
    def size_or_zero(p):
        try:
            return p.stat().st_size
        except OSError:
            return 0
    return {
        "database_bytes": size_or_zero(path),
        "wal_bytes": size_or_zero(Path(str(path) + "-wal")),
        "page_bytes": page_count * page_size,
        "reusable_bytes": free_pages * page_size,
        "completed_batches": completed,
        "resumable_batches": resumable,
        "issue_rows": failures,
        "counts": counts,
    }


def cleanup_history(workspace, progress=None, cancel=None, retain_completed=RETAIN_COMPLETED):
    """Trim ONLY completed import audit rows in an atomic transaction.

    Keep full issue records for latest finished batches, never discard any
    cancelled/interrupted/running work or its resume checkpoints.
    """
    if not isinstance(retain_completed, int) or not 1 <= retain_completed <= 20:
        raise ValueError("จำนวนประวัติที่เก็บต้องอยู่ระหว่าง 1 ถึง 20")
    core.init(workspace)
    before = snapshot(workspace)
    if cancel and cancel.is_set():
        return {"cancelled": True, "before": before}
    counts = {"completed": 0, "old_batches_removed": 0,
              "checkpoints_removed": 0, "success_logs_removed": 0,
              "old_logs_removed": 0}
    with core.WRITE_LOCK, core.connect(workspace) as db:
        finished = [row[0] for row in db.execute("""SELECT id
            FROM xstage_import_batches WHERE status='completed'
            ORDER BY created_at DESC,id DESC""")]
        counts["completed"] = len(finished)
        keep = set(finished[:retain_completed])
        try:
            for idx, batch_id in enumerate(finished):
                if cancel and cancel.is_set():
                    raise InterruptedError("ยกเลิกการจัดการประวัติ SQLite")
                cur = db.execute("""DELETE FROM xstage_import_file_checkpoints
                    WHERE batch_id=?""", (batch_id,))
                counts["checkpoints_removed"] += max(cur.rowcount, 0)
                if batch_id in keep:
                    cur = db.execute("""DELETE FROM xstage_import_items
                        WHERE batch_id=? AND outcome NOT IN (""" +
                        ",".join("?" for _ in ISSUE_OUTCOMES) + ")",
                        (batch_id, *ISSUE_OUTCOMES))
                    counts["success_logs_removed"] += max(cur.rowcount, 0)
                else:
                    cur = db.execute("DELETE FROM xstage_import_items WHERE batch_id=?",
                                     (batch_id,))
                    counts["old_logs_removed"] += max(cur.rowcount, 0)
                    db.execute("DELETE FROM xstage_import_resume_state WHERE batch_id=?",
                               (batch_id,))
                    db.execute("DELETE FROM xstage_import_batches WHERE id=?",
                               (batch_id,))
                    counts["old_batches_removed"] += 1
                if progress and (idx % 4 == 0 or idx + 1 == len(finished)):
                    progress({"processed": idx + 1, "total": len(finished),
                              **counts}, "ล้างเฉพาะประวัติงานที่เสร็จแล้ว")
            if cancel and cancel.is_set():
                raise InterruptedError("ยกเลิกการจัดการประวัติ SQLite")
            db.commit()
        except Exception:
            db.rollback()
            raise
    return {"cancelled": False, **counts,
            "before": before, "after": snapshot(workspace), "file_shrunk": False}


def compact_database(workspace, progress=None, cancel=None):
    """Explicit VACUUM with sufficient disk space, never run on import."""
    core.init(workspace)
    path = core.db_path(workspace)
    before = snapshot(workspace)
    if cancel and cancel.is_set():
        return {"cancelled": True, "before": before}
    free = shutil.disk_usage(path.parent).free
    minimum = max(256 * 1024 * 1024, before["database_bytes"] * 2)
    if free < minimum:
        raise ValueError(
            "พื้นที่ว่างไม่พอสำหรับย่อ SQLite อย่างปลอดภัย: ต้องมีอย่างน้อย " +
            str(round(minimum / (1024 ** 3), 2)) + " GB"
        )
    if progress:
        progress({"processed": 0, "total": 1},
                 "กำลังย่อ SQLite · ห้ามปิดโปรแกรมจนกว่าจะเสร็จ")
    with core.WRITE_LOCK:
        db = sqlite3.connect(path, timeout=60, isolation_level=None)
        try:
            db.execute("PRAGMA busy_timeout=60000")
            db.set_progress_handler(
                lambda: 1 if cancel and cancel.is_set() else 0, 10000)
            db.execute("VACUUM")
            db.set_progress_handler(None, 0)
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.OperationalError as exc:
            if cancel and cancel.is_set():
                raise InterruptedError("ยกเลิกการย่อฐานข้อมูล SQLite") from exc
            raise
        finally:
            db.set_progress_handler(None, 0)
            db.close()
    if progress:
        progress({"processed": 1, "total": 1}, "ย่อ SQLite เสร็จ")
    return {"cancelled": False, "before": before,
            "after": snapshot(workspace), "file_shrunk": True}
