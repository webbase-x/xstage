"""Read-only, user-initiated duplicate review for v0.9.43.

Group by metadata without deleting, hiding, copying or touching any song.
Exact-byte proof is an optional slow pass over complete Song Bundles.
"""
import csv
import json
import sqlite3
import time
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from .duplicates import scan as verify_exact_groups, bundle
from .ingest import Inspector
from .library import SearchCancelled, normalize

ACTIVE = ("deleted", "moved", "recycled", "excluded", "missing", "invalid")
CATEGORIES = ("exact", "code", "metadata", "title", "incomplete")


def format_group(row):
    kind = str(row.get("format") or row.get("kind") or Path(row["path"]).suffix).lower()
    extension = Path(row["path"]).suffix.lower()
    if "ncn" in kind or extension in (".mid", ".midi", ".kar", ".emk"):
        return "midi"
    if "video" in kind or extension in (".mp4", ".mkv", ".avi", ".wmv", ".mov"):
        return "video"
    return "audio"


def _norm(value):
    return normalize(str(value or "")).strip()


def _groups(rows, key_function):
    groups = defaultdict(list)
    for row in rows:
        key = key_function(row)
        if key and not isinstance(key, tuple):
            key = (key,)
        if key and all(key):
            groups[key].append(row)
    return [sorted(g, key=lambda x: x["id"]) for g in groups.values() if len(g) > 1]


def create_review(library, report_dir=None, *, verify_exact=False, cancelled=None, events=None):
    """Create an immutable report. Never changes song visibility or files."""
    out = Path(report_dir or library.path.parent / "duplicate-reviews")
    out.mkdir(parents=True, exist_ok=True)
    with library.connect() as db:
        rows = [dict(row) for row in db.execute(
            "SELECT * FROM songs WHERE duplicate_state NOT IN (?,?,?,?,?,?) ORDER BY id", ACTIVE)]
    checked = lambda: bool(cancelled is not None and cancelled.is_set())
    if checked():
        raise SearchCancelled()
    reviewed = []
    emitted = set()
    stats = {key: 0 for key in CATEGORIES}

    def include(groups, category):
        for group in groups:
            if checked():
                raise SearchCancelled()
            keeper = group[0]
            for candidate in group[1:]:
                if keeper["id"] == candidate["id"]:
                    continue
                pair = tuple(sorted((keeper["id"], candidate["id"])))
                if pair in emitted:
                    continue
                emitted.add(pair)
                reviewed.append((candidate["id"], keeper["id"], category,
                                 format_group(candidate), candidate["code"], candidate["title"],
                                 candidate["artist"], candidate["path"], keeper["path"]))
                stats[category] += 1

    errors = []
    if verify_exact:
        exact, errors = verify_exact_groups(library, cancelled=cancelled,
                         events=events, verify_only=True)
        if exact is None:
            raise SearchCancelled()
        include(exact, "exact")
    # Codes and metadata are candidates, NOT proof of identical media.
    include(_groups(rows, lambda r: _norm(r["code"])), "code")
    include(_groups(rows, lambda r: (_norm(r["title"]), _norm(r["artist"]),
                                    _norm(r["key_signature"]))), "metadata")
    include(_groups(rows, lambda r: _norm(r["title"])), "title")

    # Incomplete files are a quality report, not an exact-duplicate finding.
    # Collect in the same read-only report, never auto-delete or hide them.
    inspector=Inspector()
    with library.connect() as db:
        incomplete_rows=[dict(r) for r in db.execute(
            "SELECT * FROM songs WHERE duplicate_state IN ('missing','invalid') OR playable=0")]
    candidates={r['id']:r for r in rows}
    candidates.update({r['id']:r for r in incomplete_rows})
    for row in candidates.values():
        if checked():
            raise SearchCancelled()
        reason=None
        if row['duplicate_state'] in ('missing','invalid'):
            reason='สถานะ '+str(row['duplicate_state'])
        elif not row['playable']:
            reason='ไม่พร้อมเล่น'
        else:
            try:
                if not Path(row['path']).is_file():
                    reason='ไม่พบไฟล์ดนตรีต้นทาง'
                else:
                    _,parts=bundle(row['path'],inspector)
                    if 'ncn' in str(row.get('format') or row.get('kind') or '').lower() and (
                        'lyrics' not in parts or 'cursor' not in parts):
                        reason='ชุด NCN ขาด LYR/CUR'
            except (ValueError,OSError) as exc:
                reason=str(exc)
        if reason is not None:
            reviewed.append((row['id'],0,'incomplete',format_group(row),
                row['code'],row['title'],row['artist'],row['path'],reason))
            stats['incomplete']+=1

    stamp = time.strftime('%Y%m%d-%H%M%S')
    target = out / (stamp + '-' + str(time.time_ns())[-8:])
    target.mkdir()
    try:
        with closing(sqlite3.connect(target / 'review.sqlite3')) as db:
            db.execute('''CREATE TABLE suggestions(
                song_id INTEGER NOT NULL, keeper_id INTEGER NOT NULL,
                category TEXT NOT NULL, file_format TEXT NOT NULL,
                code TEXT, title TEXT, artist TEXT, path TEXT, keeper_path TEXT,
                PRIMARY KEY(song_id,keeper_id))''')
            db.executemany('INSERT INTO suggestions VALUES (?,?,?,?,?,?,?,?,?)', reviewed)
            db.execute('CREATE INDEX suggestions_filter ON suggestions(category,file_format)')
            db.commit()
        with (target / 'report.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(('song_id', 'keeper_id', 'category', 'file_format',
                             'code', 'title', 'artist', 'path', 'keeper_path'))
            for row in reviewed:
                # Excel formula injection defense; paths begin with drive letters.
                writer.writerow(["'" + v if isinstance(v, str) and v[:1] in ('=', '+', '-', '@')
                                 else v for v in row])
        summary = dict(version=1, library=str(library.path.resolve()),
                       exact_verified=bool(verify_exact), scanned_songs=len(rows),
                       suggestions=len(reviewed), categories=stats, errors=errors[:100],
                       note='Suggestions do not authorize deletion; every selected bundle is reverified.')
        (target / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        return target
    except BaseException:
        import shutil
        shutil.rmtree(target, ignore_errors=True)
        raise


def read_review(folder, *, category='all', file_format='all', limit=300, offset=0):
    folder = Path(folder)
    params = []
    where = []
    if category != 'all':
        if category not in CATEGORIES: raise ValueError('ประเภทซ้ำไม่ถูกต้อง')
        where.append('category=?'); params.append(category)
    if file_format != 'all':
        if file_format not in ('midi','audio','video'): raise ValueError('รูปแบบไฟล์ไม่ถูกต้อง')
        where.append('file_format=?'); params.append(file_format)
    clause = (' WHERE ' + ' AND '.join(where)) if where else ''
    with closing(sqlite3.connect(folder / 'review.sqlite3')) as db:
        db.row_factory = sqlite3.Row
        count = db.execute('SELECT count(*) FROM suggestions' + clause, params).fetchone()[0]
        rows = [dict(row) for row in db.execute('SELECT * FROM suggestions' + clause +
                    ' ORDER BY category,song_id LIMIT ? OFFSET ?', [*params, limit, offset])]
    return count, rows
