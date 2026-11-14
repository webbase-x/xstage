"""Build a replacement or updated song list without removing media files."""

import json
from itertools import groupby
from pathlib import Path

from .index_plan import SongPlan
from .ingest import Inspector
from .legacy import catalog_location
from .library import canonical, normalize
from .managed_import import catalog_hints, category, copy_song, safe_directory, stopped
from .name_duplicates import identity


COLUMNS = (
    'path', 'code', 'title', 'artist', 'kind', 'search', 'format', 'playable',
    'first_lyric', 'rhythm', 'key_signature', 'bpm', 'source_catalog',
    'user_edited', 'favorite', 'duplicate_preferred', 'duplicate_of', 'duplicate_state',
)


def _inspect(inspector, plan, path, old):
    record, _ = inspector.inspect(path)
    rich = set(record.pop('_rich', ()))
    hint = {key: value for key, value in (plan.hint(path) or {}).items() if value not in ('', None)}
    record.update(hint)
    rich.update(hint)
    merged = dict(old or {})
    for key, value in record.items():
        if old and key in ('code', 'title', 'artist', 'key_signature') and old['user_edited'] and old[key]:
            continue
        if (old and key in ('code', 'title', 'artist', 'key_signature', 'first_lyric', 'bpm')
                and old[key] and (key not in rich or (old['source_catalog'] and key not in hint))):
            continue
        merged[key] = value
    merged['search'] = normalize(' '.join(str(merged.get(key, '')) for key in
                                         ('code', 'title', 'artist', 'first_lyric', 'rhythm')))
    return merged


def _stage(plan, record, managed, protected, scanned):
    path = record['path']
    key = identity(record.get('title'), record.get('artist'), record.get('key_signature')) or 'path:' + path
    plan.db.execute('INSERT OR REPLACE INTO candidates VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (path, key, int(Path(path).is_relative_to(managed)), int(scanned),
                     int(record.get('id') in protected), record.get('id'), json.dumps(record, ensure_ascii=False)))


def _collect(plan, db, source, managed, mode, copy_external, cancelled, emit, protected):
    try:
        _, base = catalog_location(source)
    except ValueError:
        base = None
    scan_root = base / 'Songs' if base and (base / 'Songs').is_dir() else source
    if not scan_root.is_dir():
        raise ValueError('ไม่พบโฟลเดอร์เพลง: ' + str(scan_root))
    plan.folder(scan_root, cancelled=cancelled, events=emit)
    if copy_external and managed.is_dir() and not managed.is_relative_to(scan_root):
        plan.folder(managed, cancelled=cancelled, events=emit)
    if base:
        catalog_hints(plan, source, cancelled)
    stopped(cancelled)
    walk_errors = [note for note in plan.errors if not note.startswith(('ยังไม่รองรับ:', 'ดัชนีเดิม:'))]
    if walk_errors:
        raise ValueError('อ่านแหล่งเพลงไม่ครบ ฐานข้อมูลยังไม่ได้เปลี่ยน: ' + walk_errors[0])

    plan.db.execute('''CREATE TABLE candidates(path TEXT PRIMARY KEY, identity TEXT NOT NULL,
        managed INTEGER, scanned INTEGER, protected INTEGER, old_id INTEGER, data TEXT)''')
    inspector = Inspector()
    rejected = 0
    notes = plan.errors[:50]
    emit(dict(type='phase', phase='อ่านชื่อเพลง นักร้อง และคีย์', total=plan.count(), target=plan.count()))
    for done, (path,) in enumerate(plan.db.execute('SELECT path FROM files ORDER BY path'), 1):
        stopped(cancelled)
        old = db.execute('SELECT * FROM songs WHERE path=?', (path,)).fetchone()
        try:
            if not Path(path).is_relative_to(scan_root) and not (copy_external and Path(path).is_relative_to(managed)):
                raise ValueError('ไฟล์อยู่นอกโฟลเดอร์ที่เลือก')
            record = _inspect(inspector, plan, path, old)
        except (OSError, ValueError, EOFError) as error:
            rejected += 1
            if len(notes) < 50:
                notes.append(f'อ่านไม่ได้: {path}: {error}')
        else:
            _stage(plan, record, managed, protected, scanned=True)
        if done % 32 == 0 or done == plan.count():
            emit(dict(type='progress', done=done, total=plan.count(), path=path, rejected=rejected))
    if mode == 'rebuild' and not plan.db.execute('SELECT 1 FROM candidates LIMIT 1').fetchone():
        reason = ': ' + notes[0] if notes else ''
        raise ValueError('ไม่พบเพลงที่อ่านได้ ฐานข้อมูลยังไม่ได้เปลี่ยน' + reason)
    if mode == 'update':
        for row in db.execute("SELECT * FROM songs WHERE playable=1 AND duplicate_state NOT IN ('moved','recycled','deleted','invalid')"):
            stopped(cancelled)
            if not plan.db.execute('SELECT 1 FROM candidates WHERE path=?', (row['path'],)).fetchone():
                _stage(plan, dict(row), managed, protected, scanned=False)
    return rejected, notes


def _select(plan, db, managed, copy_external, cancelled, emit):
    plan.db.execute('CREATE TABLE chosen(id INTEGER, path TEXT PRIMARY KEY, data TEXT NOT NULL, write_row INTEGER)')
    plan.db.execute('CREATE INDEX candidates_identity ON candidates(identity)')
    plan.db.execute('CREATE INDEX candidates_old_id ON candidates(old_id)')
    total = plan.db.execute('SELECT count(DISTINCT identity) FROM candidates').fetchone()[0]
    emit(dict(type='phase', phase='คัดรายการซ้ำและเตรียมไฟล์', total=total))
    copied = duplicates = selected = 0
    order = 'identity, managed DESC, ' + ('scanned DESC, ' if copy_external else '') + 'protected DESC, old_id IS NULL, old_id, path'
    rows = plan.db.execute('SELECT path, identity, managed, scanned, protected, old_id, data FROM candidates ORDER BY ' + order)
    for done, (key, group) in enumerate(groupby(rows, key=lambda row: row[1]), 1):
        stopped(cancelled)
        path, _, internal, scanned, is_protected, retained_id, data = next(group)
        # An unindexed managed copy can lack the metadata from its source DBF.
        # If a complete entry already claimed the exact bundle, retain its metadata.
        if retained_id is None and key.startswith('path:') and plan.db.execute(
                'SELECT 1 FROM chosen WHERE path=?', (path,)).fetchone():
            continue
        record = json.loads(data)
        favored = record.get('favorite', 0)
        # The winning file may be in Songs while a duplicate ID is already queued.
        # Pick the managed path first, then keep a queued ID where possible.
        protected_id = retained_id if is_protected else None
        for _, _, _, _, is_protected, alias_id, alias_data in group:
            stopped(cancelled)
            duplicates += 1
            if protected_id is None and is_protected:
                protected_id = alias_id
            if retained_id is None:
                retained_id = alias_id
            favored = max(favored, json.loads(alias_data).get('favorite', 0))
        retained_id = protected_id or retained_id
        if copy_external and scanned and not internal:
            original = Path(path)
            prefix = canonical(managed / category(original) / original.stem)
            avoid = {row[0] for row in plan.db.execute(
                'SELECT path FROM candidates WHERE path>=? AND path<? AND identity<>? '
                "AND (old_id IS NOT NULL OR identity NOT LIKE 'path:%') "
                'UNION SELECT path FROM chosen WHERE path>=? AND path<?',
                (prefix, prefix + '\uffff', key, prefix, prefix + '\uffff'))}
            target, created = copy_song(original, managed, cancelled, avoid_paths=avoid)
            path = canonical(target)
            copied += int(created)
        record.update(path=path, favorite=favored, duplicate_of=0, duplicate_state='')
        old = db.execute('SELECT * FROM songs WHERE id=?', (retained_id,)).fetchone() if retained_id else None
        if old and old['user_edited']:
            record.update({field: old[field] for field in ('code', 'title', 'artist', 'key_signature', 'user_edited') if old[field]})
            record['search'] = normalize(' '.join(str(record.get(field, '')) for field in
                                                   ('code', 'title', 'artist', 'first_lyric', 'rhythm')))
        values = tuple(record.get(name, 0 if name in ('favorite', 'user_edited', 'duplicate_preferred') else '') for name in COLUMNS)
        changed = old is None or values != tuple(old[name] for name in COLUMNS)
        plan.db.execute('INSERT INTO chosen VALUES (?, ?, ?, ?)',
                        (retained_id, path, json.dumps(values, ensure_ascii=False), int(changed)))
        selected += 1
        if done % 32 == 0 or done == total:
            emit(dict(type='progress', done=done, total=total, path=path, duplicates=duplicates))
    plan.db.commit()
    return selected, duplicates, copied


def _commit(db, plan, mode, initial_version, cancelled):
    db.execute('ATTACH DATABASE ? AS plan', (str(Path(plan.temp.name) / 'plan.db'),))
    db.execute('BEGIN IMMEDIATE')
    if db.execute('PRAGMA main.data_version').fetchone()[0] != initial_version:
        raise ValueError('รายการเพลงมีการแก้ไขระหว่างงาน กรุณาเริ่มใหม่')
    stopped(cancelled)
    db.execute('CREATE TABLE IF NOT EXISTS catalog_id_sequence (id INTEGER PRIMARY KEY CHECK(id=1), last_id INTEGER NOT NULL)')
    last_id = db.execute('SELECT max(id) FROM songs').fetchone()[0] or 0
    previous = db.execute('SELECT last_id FROM catalog_id_sequence WHERE id=1').fetchone()
    last_id = max(last_id, previous[0] if previous else 0)
    if mode == 'clear':
        db.execute("DELETE FROM songs WHERE duplicate_state NOT IN ('moved','recycled','deleted')")
    else:
        if mode == 'rebuild':
            where = "duplicate_state NOT IN ('moved','recycled','deleted')"
        else:
            where = 'id IN (SELECT old_id FROM plan.candidates WHERE old_id IS NOT NULL)'
        db.execute('DELETE FROM songs WHERE (' + where + ' OR path IN (SELECT path FROM plan.chosen)) '
                   'AND id NOT IN (SELECT id FROM plan.chosen WHERE id IS NOT NULL)')
        statement = ('INSERT INTO songs(id,' + ','.join(COLUMNS) + ') VALUES ('
                     + ','.join('?' for _ in range(len(COLUMNS) + 1)) + ') ON CONFLICT(id) DO UPDATE SET '
                     + ','.join(f'{name}=excluded.{name}' for name in COLUMNS))
        for song_id, data in db.execute('SELECT id,data FROM plan.chosen WHERE write_row=1'):
            stopped(cancelled)
            if song_id is None:
                last_id += 1
                song_id = last_id
            db.execute(statement, (song_id, *json.loads(data)))
    db.execute('INSERT OR REPLACE INTO catalog_id_sequence VALUES (1,?)', (last_id,))
    stopped(cancelled)


def maintain_catalog(library, source, songs_root, mode, copy_external, cancelled=None, events=None, protected=()):
    if copy_external:
        raise ValueError('v0.9.43 ไม่รองรับการคัดลอกเพลงอัตโนมัติ')
    """Scan and copy before applying a single transaction to the live catalog."""
    if mode not in ('update', 'rebuild', 'clear'):
        raise ValueError('รูปแบบการสร้างรายการไม่ถูกต้อง')
    emit = events or (lambda event: None)
    stopped(cancelled)
    with SongPlan() as plan, library.connect() as db:
        version = db.execute('PRAGMA main.data_version').fetchone()[0]
        if mode != 'clear':
            emit(dict(type='phase', phase='สำรวจไฟล์เพลง', total=None))
            if copy_external:
                safe_directory(Path(songs_root).absolute())
            managed = Path(canonical(Path(songs_root)))
            rejected, notes = _collect(plan, db, Path(canonical(Path(source))), managed, mode, copy_external,
                                       cancelled, emit, set(protected))
            count, duplicates, copied = _select(plan, db, managed, copy_external, cancelled, emit)
        emit(dict(type='phase', phase='สำรองและบันทึกรายการเพลง', total=None))
        library.backup_before_rebuild(cancelled)
        _commit(db, plan, mode, version, cancelled)
        if mode == 'clear':
            return 0, 0, ['ล้างรายการเพลงแล้ว']
        skipped = duplicates + rejected + plan.omitted
        return count, skipped, [f'รายการเพลง {count:,} · ซ้ำ {duplicates:,} · คัดลอก {copied:,} · อ่านไม่ได้ {rejected:,}', *notes]
