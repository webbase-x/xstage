"""Durable local playback event ledger for all-time popular medley rankings.

One event per finished play, idempotently imported from the latest history.json.
The 500-row history remains a UI/recovery journal; this SQLite file persists
completed/medley events beyond the history cap. Never use titles as keys.
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from contextlib import closing
from pathlib import Path
from .library import SearchCancelled

STAT_FILENAME = 'play_stats.sqlite3'
_STATUSES = frozenset(('completed', 'medley'))


def validate_stats(path):
    """Validate an optional backup without executing application data."""
    path = Path(path)
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('ฐานสถิติเพลงฮิตสำรองเสียหาย')
        columns = {row[1] for row in db.execute('PRAGMA table_info(plays)')}
        if not {'event_id', 'song_id', 'path', 'played_at', 'status'} <= columns:
            raise ValueError('ฐานสถิติเพลงฮิตไม่ถูกต้อง')
    return True


def _connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.execute('CREATE TABLE IF NOT EXISTS plays ('
               'event_id TEXT PRIMARY KEY, song_id INTEGER NOT NULL, '
               'path TEXT NOT NULL, played_at INTEGER NOT NULL, status TEXT NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_plays_date ON plays(played_at)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_plays_song ON plays(song_id,path)')
    return db


def sync_recent(history_path):
    """Catch up from current history after any interrupted stats write.

    For old rows without event IDs, identical rows get deterministic ordinal
    fingerprints, preventing double counting across repeated imports.
    """
    from .performance_features import read_history_snapshot
    history_path = Path(history_path)
    rows, _revision = read_history_snapshot(history_path)
    seen_legacy = {}
    entries = []
    for row in rows:
        if row.get('status') not in _STATUSES:
            continue
        item = row.get('item') or {}
        song_id = item.get('song_id')
        path = row.get('path')
        if type(song_id) is not int or not 0 < song_id < 2**63 or not isinstance(path, str) or not path:
            continue
        try:
            timestamp = datetime.fromisoformat(row['time'])
        except (ValueError, TypeError):
            continue
        if timestamp.tzinfo is None:
            continue
        event_id = row.get('event_id')
        if not isinstance(event_id, str) or not (1 <= len(event_id) <= 100):
            canonical = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
            duplicate_number = seen_legacy.get(canonical, 0)
            seen_legacy[canonical] = duplicate_number + 1
            event_id = 'legacy:' + hashlib.sha256((canonical + '\0' + str(duplicate_number)).encode('utf-8')).hexdigest()
        entries.append((event_id, song_id, path, int(timestamp.timestamp()), row['status']))
    stats_path = history_path.with_name(STAT_FILENAME)
    with closing(_connect(stats_path)) as db:
        with db:
            db.executemany('INSERT OR IGNORE INTO plays VALUES (?,?,?,?,?)', entries)
    return stats_path


def history_hits(history_path, period='all', *, cancelled=lambda: False, now=None):
    """Read all-time or time-window hits without loading the entire event log."""
    if period not in ('all', '7', '30', '90'):
        raise ValueError('ช่วงเวลาจัดอันดับเพลงฮิตไม่ถูกต้อง')
    if cancelled():
        raise SearchCancelled()
    now = now if now is not None else datetime.now().astimezone()
    if now.tzinfo is None:
        raise ValueError('ต้องระบุเวลาปัจจุบันที่มีเขตเวลา')
    path = sync_recent(history_path)
    after = int((now - timedelta(days=int(period))).timestamp()) if period != 'all' else None
    upper = int((now + timedelta(minutes=5)).timestamp())
    with closing(sqlite3.connect(path)) as db:
        db.set_progress_handler(lambda: int(cancelled()), 1000)
        query = ('SELECT song_id,path,COUNT(*) AS n,MAX(played_at) AS last FROM plays '
                 'WHERE played_at<=?')
        params = [upper]
        if after is not None:
            query += ' AND played_at>=?'
            params.append(after)
        query += ' GROUP BY song_id,path ORDER BY n DESC,last DESC,song_id,path'
        try:
            rows = [(song_id, name, count, datetime.fromtimestamp(last, timezone.utc))
                    for song_id, name, count, last in db.execute(query, params)]
        except sqlite3.OperationalError:
            if cancelled():
                raise SearchCancelled()
            raise
    if cancelled():
        raise SearchCancelled()
    return rows
