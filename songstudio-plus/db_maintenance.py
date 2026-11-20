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


# This is a source-code classification, not a claim about the size of a
# particular user's library. The dbstat virtual table measures real pages.
CATEGORIES = {
    "xstage_migrations": ("keep", "schema migrations"),
    "xstage_media": ("keep", "unique SHA-256 media registry"),
    "xstage_media_sources": ("keep", "verified source paths for playback/export"),
    "xstage_songs": ("keep", "song IDs, titles and artists"),
    "xstage_import_batches": ("temporary", "import summaries; retain recent jobs"),
    "xstage_import_items": ("temporary", "problem reports; retain recent failures"),
    "xstage_import_resume_state": ("temporary", "checkpoint counters while interrupted"),
    "xstage_import_file_checkpoints": ("temporary", "resume progress while unfinished"),
    "xstage_lyric_scan_cache": ("cache", "avoid re-parsing unchanged sidecars"),
    "xstage_lyric_drafts": ("keep", "untimed original lyric text"),
    "xstage_lyric_versions": ("keep", "current and prior lyric versions for undo"),
    "xstage_lyric_lines": ("keep", "lyric lines and timestamps"),
    "xstage_lyric_cues": ("keep", "measured or labelled estimated sweep cues"),
    "xstage_edit_batches": ("keep", "undo/edit history"),
    "xstage_edit_changes": ("keep", "undo version relationships"),
    "xstage_exports": ("keep", "output verification and incremental export"),
    "xstage_swipe_audit_runs": ("keep", "audit summary history"),
    "xstage_swipe_findings": ("derived", "only recent completed scan details needed"),
    "xstage_swipe_reviews": ("keep", "manual listening decisions"),
    "xstage_manual_reviews": ("keep", "manual timing approval history"),
}


def detailed_audit(workspace, progress=None, cancel=None):
    """Read SQLite page usage by table AND index, including current WAL size.

    Unlike filename size guesses, dbstat accounts for indexes/overflow pages.
    Never modifies the database or original music files. Runs as a job because
    a multi-gigabyte database may require a lengthy page scan.
    """
    core.init(workspace)
    if progress:
        progress({"processed": 0, "total": 2}, "ตรวจพื้นที่แต่ละตารางและดัชนี SQLite")
    db = None
    try:
        with core.connect(workspace) as db:
            if cancel:
                db.set_progress_handler(lambda: int(cancel.is_set()), 20000)
            objects = [dict(row) for row in db.execute(
                """SELECT name,type,tbl_name FROM sqlite_master
                   WHERE type IN ('table','index') AND name NOT LIKE 'sqlite_%'""")]
            owners = {row["name"]: row["tbl_name"] for row in objects}
            page_sizes = {}
            dbstat_available = True
            try:
                for row in db.execute("""SELECT name,SUM(pgsize) AS bytes,
                      COUNT(*) AS pages FROM dbstat GROUP BY name"""):
                    page_sizes[row["name"]] = (int(row["bytes"] or 0),
                                               int(row["pages"] or 0))
            except sqlite3.OperationalError as e:
                if "no such table" not in str(e).lower():
                    raise
                dbstat_available = False
            if cancel and cancel.is_set():
                raise InterruptedError("ยกเลิกการตรวจ SQLite")
            if progress:
                progress({"processed": 1, "total": 2}, "ตรวจความสอดคล้องโครงสร้างฐาน")
            # Bounded quick_check is a structural check; do not mistake it for
            # exhaustive audio/lyric correctness verification.
            quick = db.execute("PRAGMA quick_check(1)").fetchone()[0]
            db.set_progress_handler(None, 0)
            totals = {}
            for row in objects:
                kind = row["type"]
                name = row["name"]
                owner = row["tbl_name"] if kind == "index" else name
                if owner not in totals:
                    category, purpose = CATEGORIES.get(
                        owner, ("unknown", "unclassified existing SQLite object"))
                    totals[owner] = {"table": owner, "category": category,
                                     "purpose": purpose, "bytes": 0,
                                     "table_bytes": 0, "index_bytes": 0,
                                     "pages": 0, "indexes": []}
                size, pages = page_sizes.get(name, (0, 0))
                info = totals[owner]
                info["bytes"] += size
                info["pages"] += pages
                if kind == "index":
                    info["index_bytes"] += size
                    info["indexes"].append({"name": name, "bytes": size})
                else:
                    info["table_bytes"] += size
            # Include implicit sqlite_autoindex objects: unique constraints
            # may occupy substantial space even though not in sqlite_master.
            for name, (size, pages) in page_sizes.items():
                if not name.startswith("sqlite_autoindex_"):
                    continue
                owner = name[len("sqlite_autoindex_"):].rsplit("_", 1)[0]
                info = totals.get(owner)
                if info:
                    info["bytes"] += size
                    info["index_bytes"] += size
                    info["pages"] += pages
                    info["indexes"].append({"name": name, "bytes": size})
            rows = sorted(totals.values(), key=lambda x: x["bytes"], reverse=True)
    except sqlite3.OperationalError as e:
        if cancel and cancel.is_set():
            raise InterruptedError("ยกเลิกการตรวจ SQLite") from e
        raise
    result = snapshot(workspace)
    if progress:
        progress({"processed": 2, "total": 2}, "ตรวจโครงสร้าง SQLite เสร็จ")
    return {**result, "quick_check": quick, "dbstat_available": dbstat_available,
            "table_space": rows, "unknown_tables": [
                x["table"] for x in rows if x["category"] == "unknown"
            ]}


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
