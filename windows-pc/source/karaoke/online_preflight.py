"""Fast SQLite-only Online wizard preflight. File validation happens exactly once
inside sync_web_assets after explicit user confirmation, never on wizard page 2.
"""
from contextlib import closing
import sqlite3
from pathlib import Path
from .visible_sync import EXCLUDED

def quick_eligible_counts(database):
    """Approximate eligible MIDI/NCN song counts without touching media paths.

    Visibility and playable flags match the catalog query. Missing/corrupt
    sidecars are only rejected by local_candidates on the sync worker.
    """
    placeholders = ','.join('?' for _ in EXCLUDED)
    sql = f"""SELECT
        CASE WHEN LOWER(COALESCE(format,'')) LIKE '%ncn%' THEN 'NCN' ELSE 'MIDI' END AS k,
        COUNT(*) AS n
        FROM songs
        WHERE duplicate_of=0 AND duplicate_state NOT IN ({placeholders})
          AND playable=1
          AND (LOWER(COALESCE(format,'')) LIKE '%ncn%'
               OR LOWER(COALESCE(path,'')) LIKE '%.mid'
               OR LOWER(COALESCE(path,'')) LIKE '%.kar')
        GROUP BY k"""
    counts={'NCN':0,'MIDI':0}
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', timeout=15, uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA busy_timeout=15000')
        for kind, amount in db.execute(sql,EXCLUDED):
            if kind in counts:counts[kind]=int(amount)
    return counts

def visible_row_count(database):
    placeholders=','.join('?' for _ in EXCLUDED)
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', timeout=15, uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        value=db.execute(
            f'SELECT COUNT(*) FROM songs WHERE duplicate_of=0 AND duplicate_state NOT IN ({placeholders})',
            EXCLUDED).fetchone()
        return int(value[0]) if value else 0
