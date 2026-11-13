"""Durable, resumable song discovery for X-Stage Song Studio PC.

The catalog lives only in the user's private local AppData. Scans never alter
original media. A successful scan atomically publishes a complete snapshot.
Interrupted scans save inspected entries as a checkpoint; an earlier complete
snapshot remains usable. Re-scan still enumerates directory entries to detect
deletions and in-place edits, but unchanged media/NCN metadata is reused.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

SCHEMA = 1
SUPPORTED = {".mp3", ".m4a", ".mp4", ".aac", ".wav", ".wma",
             ".flac", ".ogg", ".oga", ".mid", ".midi", ".kar", ".ncn"}
COMPANIONS = {".lyr", ".cur"}


def _scope(source, workspace):
    source = str(Path(source).expanduser().resolve())
    workspace = str(Path(workspace).expanduser().resolve())
    return hashlib.sha256((source.casefold() + "\0" + workspace.casefold())
                          .encode("utf-8")).hexdigest()


def _connect(db_path):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(db_path), timeout=30)
    try:
        db.execute("""CREATE TABLE IF NOT EXISTS song_index(
            scope TEXT NOT NULL, path TEXT NOT NULL, size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL, row_json TEXT NOT NULL,
            PRIMARY KEY (scope, path))""")
        db.execute("""CREATE TABLE IF NOT EXISTS song_checkpoint(
            scope TEXT NOT NULL, path TEXT NOT NULL, size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL, row_json TEXT NOT NULL,
            PRIMARY KEY (scope, path))""")
        db.execute("""CREATE TABLE IF NOT EXISTS song_index_info(
            scope TEXT PRIMARY KEY, count INTEGER NOT NULL,
            indexed_at REAL NOT NULL, version INTEGER NOT NULL)""")
        return db
    except Exception:
        db.close()
        raise


def _read_rows(db, table, scope):
    return {
        p: (size, modified, json.loads(payload))
        for p, size, modified, payload in db.execute(
            "SELECT path, size, mtime_ns, row_json FROM " + table +
            " WHERE scope = ?", (scope,))
    }


def _overlay(row, notes):
    row = dict(row)
    note = notes.get(row["path"], {})
    if isinstance(note, dict):
        for key in ("title", "artist"):
            if note.get(key):
                row[key] = note[key]
        row["lyrics_edit"] = note.get("lyrics", "")
    return row


def restore(source, workspace, db_path, notes):
    """Instant startup from a previously completed snapshot; no disk walk."""
    if not Path(source).expanduser().is_dir() or not Path(db_path).is_file():
        return []
    scope = _scope(source, workspace)
    try:
        with _connect(db_path) as db:
            info = db.execute(
                "SELECT count, version FROM song_index_info WHERE scope=?",
                (scope,)).fetchone()
            if not info or info[1] != SCHEMA:
                return []
            rows = [_overlay(item[2], notes)
                    for item in _read_rows(db, "song_index", scope).values()]
            if len(rows) != info[0]:
                return []  # Never present a partial or corrupted snapshot.
        return sorted(rows, key=lambda row: row["id"])
    except (OSError, ValueError, sqlite3.DatabaseError, KeyError, TypeError):
        return []


def _save_checkpoint(db_path, scope, records):
    """Resume from known inspected files without replacing the live catalog."""
    with _connect(db_path) as db:
        with db:
            db.execute("DELETE FROM song_checkpoint WHERE scope=?", (scope,))
            db.executemany(
                "INSERT INTO song_checkpoint VALUES (?,?,?,?,?)",
                ((scope, path, size, modified,
                  json.dumps(row, ensure_ascii=False, separators=(",", ":")))
                 for path, (size, modified, row) in records.items()))


def scan(source, workspace, db_path, notes, ncn, *, full=False,
         cancelled=None, on_progress=None):
    """Incremental enumeration + NCN binding, then atomic catalog publication.

    On cancellation keep the previous committed catalog and checkpoint the
    completed file enumeration; next scan reuses unchanged checkpoint rows.
    """
    origin = Path(source).expanduser().resolve()
    work = Path(workspace).expanduser().resolve()
    if not origin.is_dir():
        raise ValueError("โฟลเดอร์ต้นฉบับไม่มีอยู่ กรุณาเลือกโฟลเดอร์ก่อนสแกน")
    excludes = {work / "songs", work / "song"}
    if any(origin == item or item in origin.parents for item in excludes):
        raise ValueError("โฟลเดอร์ต้นฉบับต้องไม่อยู่ในโฟลเดอร์ผลลัพธ์ของโปรแกรม")
    scope = _scope(origin, work)
    with _connect(db_path) as db:
        previous = _read_rows(db, "song_index", scope)
        staging = {} if full else _read_rows(db, "song_checkpoint", scope)
    used = set()
    records = {}
    scanned = added = changed = reused = 0
    last_status = time.monotonic()
    failed_dirs = []
    component_index = {}
    component_stamps = {}

    def status(force=False):
        nonlocal last_status
        now = time.monotonic()
        if on_progress and (force or now - last_status >= .7):
            on_progress(f"ตรวจพบเพลง {len(records):,} · ตรวจไฟล์ {scanned:,}"
                        f" · ใช้ดัชนีเดิม {reused:,} · เพิ่ม {added:,} · เปลี่ยน {changed:,}",
                        scanned)
            last_status = now

    def is_cancelled():
        return bool(cancelled and cancelled.is_set())

    directories = [origin]
    while directories:
        if is_cancelled():
            status(True)
            if records:
                _save_checkpoint(db_path, scope, records)
            raise RuntimeError("หยุดสแกนแล้ว · บันทึกจุดตรวจล่าสุดไว้ สแกนครั้งต่อไปใช้ดัชนีเดิมต่อได้")
        folder = directories.pop()
        try:
            with os.scandir(folder) as it:
                entries = sorted(it, key=lambda x: x.name.casefold())
        except OSError as exc:
            failed_dirs.append(f"{folder}: {exc}")
            continue
        child_dirs = []
        for entry in entries:
            if is_cancelled():
                break
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    candidate = Path(entry.path)
                    if not any(candidate == item or item in candidate.parents
                               for item in excludes):
                        child_dirs.append(candidate)
                    continue
                extension = Path(entry.name).suffix.lower()
                if extension not in (SUPPORTED | COMPANIONS):
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                info = entry.stat(follow_symlinks=False)
                path = entry.path
                scanned += 1
                if extension in COMPANIONS:
                    ncn.index_component(Path(path), component_index)
                    component_stamps[path] = (info.st_size, info.st_mtime_ns)
                    status()
                    continue
                cached = (None if full else staging.get(path) or previous.get(path))
                if cached and cached[0] == info.st_size and cached[1] == info.st_mtime_ns:
                    row = dict(cached[2])
                    reused += 1
                else:
                    old = previous.get(path)
                    song_id = old[2]["id"] if old else None
                    row = {"path": path, "title": Path(entry.name).stem,
                           "artist": "", "code": Path(entry.name).stem,
                           "kind": extension[1:].upper(), "size": info.st_size,
                           "status": "unsupported" if extension == ".ncn" else "ready",
                           "lyrics_edit": ""}
                    if song_id:
                        row["id"] = song_id
                        changed += 1
                    else:
                        added += 1
                row = _overlay(row, notes)
                records[path] = (info.st_size, info.st_mtime_ns, row)
                status()
            except OSError as exc:
                failed_dirs.append(f"{entry.path}: {exc}")
        directories.extend(reversed(child_dirs))

    if is_cancelled():
        status(True)
        if records:
            _save_checkpoint(db_path, scope, records)
        raise RuntimeError("หยุดสแกนแล้ว · บันทึกจุดตรวจล่าสุดไว้ สแกนครั้งต่อไปใช้ดัชนีเดิมต่อได้")
    if failed_dirs:
        if records:
            _save_checkpoint(db_path, scope, records)
        raise RuntimeError("สแกนไม่ครบเพราะอ่านไฟล์หรือโฟลเดอร์ไม่ได้ · "
                           "ยังคงดัชนีเดิม ไม่ลบรายการที่มองไม่เห็น · " +
                           "; ".join(failed_dirs[:3]))

    next_id = max((item[2].get("id", 0) for item in previous.values()), default=0) + 1
    for path, (_, _, row) in records.items():
        if not row.get("id"):
            row["id"] = next_id
            next_id += 1

    songs = list(records.values())
    for number, (_, _, row) in enumerate(songs, 1):
        if is_cancelled():
            _save_checkpoint(db_path, scope, records)
            raise RuntimeError("หยุดสแกนแล้ว · เก็บจุดตรวจล่าสุดไว้")
        original = Path(row["path"])
        if original.suffix.lower() not in (".mid", ".midi"):
            continue
        # During scans use ONLY the already enumerated companion index.
        # The old fallback scanned the same Lyrics/Cursor folders for each MIDI.
        trio = ncn.resolve_companions(original, component_index, indexed_only=True)
        if trio is None:
            row.pop("ncn", None)
            row.pop("components", None)
            row.pop("_ncn_stamp", None)
            continue
        stamp = {
            "lyrics": list(component_stamps.get(trio["lyrics"], ())) if trio["lyrics"] else [],
            "cursor": list(component_stamps.get(trio["cursor"], ())) if trio["cursor"] else [],
            "paths": [trio["lyrics"], trio["cursor"]],
        }
        prior_stamp = row.get("_ncn_stamp")
        if prior_stamp == stamp and row.get("source_format") == "NCN":
            continue
        note = notes.get(row["path"], {})
        row.update(ncn=trio, source_format="NCN",
                   components={"song": trio["midi"], "lyrics": trio["lyrics"],
                               "cursor": trio["cursor"]},
                   _ncn_stamp=stamp)
        row.pop("component_error", None)
        row["status"] = "ready" if not trio["missing"] else "missing-companion"
        if trio["lyrics"]:
            try:
                meta = ncn.lyric_metadata(Path(trio["lyrics"]))
                row["title"] = (note.get("title") or meta["title"] or original.stem)
                row["artist"] = note.get("artist") or meta["artist"]
            except (OSError, ValueError) as exc:
                row["status"] = "lyrics-error"
                row["component_error"] = str(exc)
        if trio["missing"]:
            row["component_error"] = "NCN ขาด " + ", ".join(trio["missing"])
        if on_progress and number % 1000 == 0:
            on_progress(f"จับคู่ MIDI/NCN {number:,}/{len(songs):,} เพลง", scanned)

    rows = [record[2] for record in songs]
    rows.sort(key=lambda x: x["id"])
    removed = len(set(previous) - set(records))
    # Snapshot swaps only when directory enumeration and NCN bindings finish.
    # The disk database, not the UI thread, is the long-lived source of truth.
    if on_progress:
        on_progress(f"กำลังบันทึกดัชนีเพลง {len(rows):,} รายการในเครื่อง", scanned)
    with _connect(db_path) as db:
        with db:
            if full:
                db.execute("DELETE FROM song_index WHERE scope=?", (scope,))
                updates = list(records.items())
            else:
                updates = [
                    (path, record) for path, record in records.items()
                    if path not in previous or record[0] != previous[path][0]
                    or record[1] != previous[path][1]
                    or record[2] != previous[path][2]
                ]
                db.executemany("DELETE FROM song_index WHERE scope=? AND path=?",
                               ((scope, p) for p in set(previous) - set(records)))
            db.executemany(
                "INSERT OR REPLACE INTO song_index VALUES (?,?,?,?,?)",
                ((scope, path, size, modified,
                  json.dumps(row, ensure_ascii=False, separators=(",", ":")))
                 for path, (size, modified, row) in updates))
            db.execute("INSERT OR REPLACE INTO song_index_info VALUES (?,?,?,?)",
                       (scope, len(rows), time.time(), SCHEMA))
            db.execute("DELETE FROM song_checkpoint WHERE scope=?", (scope,))
    return rows, {"songs": len(rows), "checked": scanned, "reused": reused,
                  "added": added, "changed": changed, "removed": removed,
                  "mode": "full" if full else "incremental"}
