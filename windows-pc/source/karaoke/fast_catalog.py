"""Transactional, cache-first song catalog builder (0.9.39+).

The media tree is read-only except when the user explicitly elects to COPY
external media. Never infer exact duplicates from song titles, IDs or keys.
"""
from __future__ import annotations

import csv
import json
import os
import sqlite3
from pathlib import Path

from .catalog_maintenance import COLUMNS, _inspect
from .index_plan import SongPlan
from .ingest import Inspector
from .incremental import signature, content_key, trusted_stamp, READER_REVISION
from .legacy import catalog_location
from .library import SearchCancelled, canonical, normalize
from .managed_import import catalog_hints, copy_song, safe_directory, stopped
from .name_duplicates import identity

CACHE_REV = 'fast-catalog-2:' + READER_REVISION
SCANNED_MODES = ('quick', 'fast', 'full', 'safe_rebuild')
DUP_POLICIES = ('hide', 'show', 'review')


class CatalogBuildResult(tuple):
    """Keeps compatibility with existing (count, skipped, notes) callbacks."""
    def __new__(cls, count, skipped, notes, *, safe_to_shutdown=False,
                duplicate_report=None, metrics=None):
        result = super().__new__(cls, (count, skipped, notes))
        result.safe_to_shutdown = bool(safe_to_shutdown)
        result.duplicate_report = duplicate_report
        result.metrics = metrics or {}
        return result


def _cache_path(library):
    return library.path.with_name(library.path.stem + '-fast-catalog-cache.sqlite3')


def _make_cache(path):
    cache = sqlite3.connect(path, timeout=30)
    cache.row_factory = sqlite3.Row
    cache.execute('PRAGMA journal_mode=WAL')
    cache.execute('PRAGMA synchronous=NORMAL')
    cache.execute('''CREATE TABLE IF NOT EXISTS checked (
        path TEXT PRIMARY KEY, stamp TEXT NOT NULL, size_key TEXT NOT NULL,
        digest TEXT, reader TEXT NOT NULL)''')
    cache.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    cache.execute('''CREATE TABLE IF NOT EXISTS pending (
        path TEXT PRIMARY KEY, stamp TEXT NOT NULL, size_key TEXT NOT NULL)''')
    return cache


def _active(row):
    return row and row['duplicate_state'] not in ('deleted', 'moved', 'recycled', 'excluded')


def _stage(plan, path, old, stamp, sizes, digest, record, managed, scanned=1, verify=0):
    plan.db.execute('''INSERT OR REPLACE INTO staged
        (path,old_id,planned_id,stamp,size_key,digest,data,managed,scanned,code,identity,verify)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
        (path, old['id'] if old else None, old['id'] if old else None,
         stamp, sizes, digest, json.dumps(record, ensure_ascii=False),
         int(Path(path).is_relative_to(managed)), scanned,
         str(record.get('code') or '').strip().casefold(),
         identity(record.get('title'), record.get('artist'), record.get('key_signature')) or 'path:' + path, int(verify)))


def _scan(plan, library, db, cache, source, managed, mode, copy_external, cancelled, emit, metrics):
    try:
        _, base = catalog_location(source)
    except ValueError:
        base = None
    scan_root = base / 'Songs' if base and (base / 'Songs').is_dir() else source
    if not scan_root.is_dir():
        raise ValueError('ไม่พบโฟลเดอร์เพลง: ' + str(scan_root))
    emit(dict(type='phase', phase='สำรวจรายการไฟล์โดยไม่อ่านเนื้อหา', total=None))
    plan.folder(scan_root, cancelled=cancelled, events=emit)
    if copy_external and managed.is_dir() and not managed.is_relative_to(scan_root):
        plan.folder(managed, cancelled=cancelled, events=emit)
    if base:
        catalog_hints(plan, source, cancelled)
    stopped(cancelled)
    errors = [e for e in plan.errors if not e.startswith(('ยังไม่รองรับ:', 'ดัชนีเดิม:'))]
    if errors:
        raise ValueError('สแกนโฟลเดอร์ไม่ครบ จึงไม่เปลี่ยนฐานข้อมูล: ' + errors[0])
    if not plan.count():
        if mode == 'safe_rebuild':
            raise ValueError('ไม่พบเพลงในโฟลเดอร์ ยกเลิกสร้างใหม่เพื่อรักษาฐานเดิม')
    plan.db.execute('''CREATE TABLE staged (
        path TEXT PRIMARY KEY, old_id INTEGER, planned_id INTEGER, stamp TEXT NOT NULL,
        size_key TEXT NOT NULL, digest TEXT, data TEXT NOT NULL,
        managed INTEGER NOT NULL, scanned INTEGER NOT NULL, code TEXT, identity TEXT,
        verify INTEGER NOT NULL DEFAULT 0)''')
    plan.db.execute('CREATE INDEX staged_sizes ON staged(size_key)')
    plan.db.execute('CREATE INDEX staged_digest ON staged(digest)')
    plan.db.execute('CREATE INDEX staged_code ON staged(code)')
    plan.db.execute('CREATE INDEX staged_identity ON staged(identity)')
    plan.db.execute('''CREATE TABLE missing (path TEXT PRIMARY KEY, old_id INTEGER NOT NULL, digest TEXT)''')
    plan.db.execute('CREATE INDEX missing_digest ON missing(digest)')
    metrics['scanned_root'] = str(scan_root)
    inspector = Inspector()
    total = plan.count()
    emit(dict(type='phase', phase=('ตรวจใหม่ทั้งคลัง' if mode != 'fast' else 'ตรวจเฉพาะไฟล์ที่เปลี่ยน'), total=total))
    for done, (path,) in enumerate(plan.db.execute('SELECT path FROM files ORDER BY path'), 1):
        stopped(cancelled)
        old = db.execute('SELECT * FROM songs WHERE path=?', (path,)).fetchone()
        try:
            if not Path(path).is_relative_to(scan_root) and not (copy_external and Path(path).is_relative_to(managed)):
                raise ValueError('ไฟล์เพลงอยู่นอกต้นทาง')
            if not _active(old) and old is not None:
                metrics['skipped_protected'] += 1
                continue  # Never silently resurrect deleted/moved/recycled tombstones.
            if Path(path).is_symlink() or getattr(Path(path), 'is_junction', lambda: False)():
                raise ValueError('ไม่รองรับไฟล์เพลงที่เป็นลิงก์')
            stamp, sizes = signature(path, inspector)
            cached = cache.execute('SELECT stamp,size_key,digest,reader FROM checked WHERE path=?', (path,)).fetchone()
            unchanged = bool(mode == 'fast' and old and old['duplicate_state'] != 'missing' and cached and
                             cached['stamp'] == stamp and cached['size_key'] == sizes and
                             cached['reader'] == CACHE_REV and trusted_stamp(stamp))
            hint = plan.hint(path)
            if unchanged and not hint:
                record = dict(old)
                digest = cached['digest']
                metrics['unchanged'] += 1
            else:
                record = _inspect(inspector, plan, path, old)
                digest = cached['digest'] if cached and cached['stamp'] == stamp and trusted_stamp(stamp) else None
                metrics['updated' if old else 'added'] += 1
            if not unchanged and signature(path, inspector)[0] != stamp:
                raise ValueError('ไฟล์เปลี่ยนขณะตรวจ')
            _stage(plan, path, old, stamp, sizes, digest, record, managed, verify=int(not unchanged))
        except SearchCancelled:
            raise
        except (OSError, ValueError, EOFError, sqlite3.Error) as error:
            metrics['failed'] += 1
            if len(metrics['warnings']) < 30:
                metrics['warnings'].append(f'{path}: {error}')
        if done % 256 == 0 or done == total:
            plan.db.commit()
            emit(dict(type='progress', done=done, total=total,
                      unchanged=metrics['unchanged'], added=metrics['added'],
                      updated=metrics['updated'], failed=metrics['failed'], path=path))
    # Rows outside the selected roots are NOT reconciled as missing/offline.
    # A removable drive or NAS can be temporarily unavailable even while a
    # user is only updating a different folder. Cache known external records
    # without probing them on every update; first-use catalog entries are
    # checked read-only to seed cross-folder duplicate comparisons.
    total_old = db.execute("SELECT count(*) FROM songs WHERE duplicate_state NOT IN ('moved','recycled','deleted','excluded')").fetchone()[0]
    emit(dict(type='phase', phase='ตรวจเฉพาะรายการเดิมในขอบเขตที่เลือก', total=total_old))
    scan_roots = (scan_root, managed) if copy_external else (scan_root,)
    for done, old in enumerate(db.execute(
            "SELECT * FROM songs WHERE duplicate_state NOT IN ('moved','recycled','deleted','excluded')"), 1):
        stopped(cancelled)
        path = old['path']
        if plan.db.execute('SELECT 1 FROM staged WHERE path=?', (path,)).fetchone():
            continue
        in_scope = any(Path(path).is_relative_to(root) for root in scan_roots)
        cached = cache.execute('SELECT stamp,size_key,digest,reader FROM checked WHERE path=?', (path,)).fetchone()
        if not in_scope:
            metrics['outside_kept'] += 1
            # Do not resurrect entries already known as missing outside scope.
            if old['duplicate_state'] == 'missing':
                continue
            if cached and cached['reader'] == CACHE_REV:
                stamp, sizes = cached['stamp'], cached['size_key']
                digest = cached['digest']
            else:
                # One-time migration only; never mark an unselected location missing.
                try:
                    stamp, sizes = signature(path, inspector)
                except (OSError, ValueError, EOFError):
                    metrics['outside_unavailable'] += 1
                    continue
                digest = None
            _stage(plan, path, old, stamp, sizes, digest, dict(old), managed, scanned=0)
        else:
            # Directory traversal completed; an old in-scope path absent from
            # staged must be preserved as a reversible missing record.
            if Path(path).is_file():
                metrics['failed'] += 1
                if len(metrics['warnings']) < 30:
                    metrics['warnings'].append('ไฟล์เดิมไม่อยู่ในชุดที่สแกน: ' + path)
            plan.db.execute('INSERT OR IGNORE INTO missing VALUES (?,?,?)',
                            (path, old['id'], cached['digest'] if cached else None))
            metrics['missing'] += 1
            if old['duplicate_state'] != 'missing' or old['playable'] or old['duplicate_of']:
                metrics['missing_changed'] += 1
        if done % 512 == 0 or done == total_old:
            plan.db.commit()
            emit(dict(type='progress', done=done, total=total_old,
                      missing=metrics['missing'], outside_kept=metrics['outside_kept']))
    if mode == 'safe_rebuild' and metrics['failed']:
        raise ValueError('พบไฟล์อ่านไม่ได้ในโหมดสร้างใหม่ จึงไม่แทนที่ฐานเดิม: ' + metrics['warnings'][0])
    if mode == 'safe_rebuild' and not plan.db.execute('SELECT 1 FROM staged LIMIT 1').fetchone():
        raise ValueError('ไม่มีเพลงที่อ่านได้ ไม่เปลี่ยนฐานข้อมูลเดิม')


def _hash_candidates(plan, cache, cancelled, emit, metrics):
    """Read file BODIES only for same-size bundles, reuse trusted prior hashes."""
    sizes = plan.db.execute('SELECT count(*) FROM (SELECT 1 FROM staged GROUP BY size_key HAVING count(*)>1)').fetchone()[0]
    emit(dict(type='phase', phase='เทียบขนาดและยืนยันเนื้อหาเพลงซ้ำ', total=sizes))
    inspector = Inspector()
    for done, (size,) in enumerate(plan.db.execute('SELECT size_key FROM staged GROUP BY size_key HAVING count(*)>1'), 1):
        stopped(cancelled)
        cursor = plan.db.execute('SELECT path,stamp,digest,scanned FROM staged WHERE size_key=?', (size,))
        while True:
            batch = cursor.fetchmany(256)
            if not batch:
                break
            for path, stamp, old_digest, scanned in batch:
                stopped(cancelled)
                if not scanned and not old_digest and not Path(path).is_file():
                    # An unselected offline source must not cause a scan error.
                    metrics['outside_unavailable'] += 1
                    continue
                if old_digest and trusted_stamp(stamp):
                    metrics['digest_reused'] += 1
                    continue
                try:
                    hashed = content_key(path, inspector, cancelled)
                    if signature(path, inspector)[0] != stamp:
                        raise ValueError('ไฟล์เปลี่ยนระหว่างตรวจ SHA-256')
                    plan.db.execute('UPDATE staged SET digest=? WHERE path=?', (hashed, path))
                    metrics['hashed'] += 1
                except SearchCancelled:
                    raise
                except (OSError, EOFError, ValueError) as error:
                    # An uncertain collision must never be automatically merged.
                    metrics['failed'] += 1
                    if len(metrics['warnings']) < 30:
                        metrics['warnings'].append(f'{path}: {error}')
        if done % 25 == 0 or done == sizes:
            plan.db.commit()
            emit(dict(type='progress', done=done, total=sizes, hashed=metrics['hashed'],
                      failed=metrics['failed']))


def _copy_external(plan, managed, cancelled, emit, metrics):
    """Copy verified external bundles only at explicit user request."""
    total = plan.db.execute('SELECT count(*) FROM staged WHERE managed=0 AND scanned=1').fetchone()[0]
    rows = plan.db.execute('SELECT path,digest,data FROM staged WHERE managed=0 AND scanned=1 ORDER BY path')
    # Only one copy per already-hashed identical group; existing managed copy wins.
    inspector = Inspector()
    emit(dict(type='phase', phase='คัดลอกเพลงที่เลือกเข้า Songs (ไม่ลบต้นทาง)', total=total))
    for done, (path, digest, data) in enumerate(rows, 1):
        stopped(cancelled)
        try:
            if digest and plan.db.execute(
                    'SELECT 1 FROM staged WHERE managed=1 AND digest=? LIMIT 1', (digest,)).fetchone():
                continue
            target, created = copy_song(path, managed, cancelled)
            target = canonical(target)
            if created:
                metrics['copied'] += 1
            if target != path and not plan.db.execute('SELECT 1 FROM staged WHERE path=?', (target,)).fetchone():
                if digest is None:
                    digest = content_key(path, inspector, cancelled)
                    plan.db.execute('UPDATE staged SET digest=? WHERE path=?', (digest, path))
                record = json.loads(data)
                record['path'] = target
                stamp, sizes = signature(target, inspector)
                _stage(plan, target, None, stamp, sizes, digest, record, managed, verify=1)
                metrics['staged_new_rows'] += 1
        except SearchCancelled:
            raise
        except (OSError, ValueError, EOFError) as error:
            metrics['failed'] += 1
            if len(metrics['warnings']) < 30:
                metrics['warnings'].append(f'คัดลอกไม่สำเร็จ {path}: {error}')
        if done % 32 == 0 or done == total:
            plan.db.commit()
            emit(dict(type='progress', done=done, total=total, copied=metrics['copied']))


def _allocate_ids(plan, db):
    last = db.execute('SELECT max(id) FROM songs').fetchone()[0] or 0
    present = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='catalog_id_sequence'").fetchone()
    row = db.execute('SELECT last_id FROM catalog_id_sequence WHERE id=1').fetchone() if present else None
    last = max(last, row[0] if row else 0)
    for (path,) in plan.db.execute('SELECT path FROM staged WHERE old_id IS NULL ORDER BY path'):
        last += 1
        plan.db.execute('UPDATE staged SET planned_id=? WHERE path=?', (last, path))
    return last


def _rank(row, protected):
    record = json.loads(row['data'])
    return (row['planned_id'] not in protected, not record.get('duplicate_preferred'),
            not record.get('user_edited'), not record.get('favorite'),
            not row['managed'], row['old_id'] is None,
            row['planned_id'])


def _duplicates(plan, policy, protected, cancelled, emit, metrics):
    # Only probe unselected paths in actual hash-collision groups. An offline
    # drive must not become the keeper that hides a valid scanned song.
    for (path,) in plan.db.execute('''SELECT s.path FROM staged s WHERE s.scanned=0 AND s.digest IS NOT NULL
        AND EXISTS(SELECT 1 FROM staged t WHERE t.digest=s.digest AND t.scanned=1)'''):
        stopped(cancelled)
        if not Path(path).is_file():
            plan.db.execute('UPDATE staged SET digest=NULL WHERE path=?', (path,))
            metrics['outside_unavailable'] += 1
    plan.db.execute('CREATE TABLE visibility(path TEXT PRIMARY KEY, keeper INTEGER, state TEXT)')
    plan.db.execute('CREATE TABLE duplicate_pairs(keeper_id INTEGER,keeper_path TEXT,duplicate_id INTEGER,duplicate_path TEXT,digest TEXT)')
    groups = plan.db.execute('SELECT count(*) FROM (SELECT 1 FROM staged WHERE digest IS NOT NULL GROUP BY digest HAVING count(*)>1)').fetchone()[0]
    emit(dict(type='phase', phase='จัดกลุ่มไฟล์ซ้ำจริงและเลือกไฟล์หลัก', total=groups))
    for done, (digest,) in enumerate(plan.db.execute(
            'SELECT digest FROM staged WHERE digest IS NOT NULL GROUP BY digest HAVING count(*)>1'), 1):
        stopped(cancelled)
        plan.db.row_factory = sqlite3.Row
        # Two ordered passes avoid loading enormous duplicate groups into RAM.
        winner = min(plan.db.execute('SELECT * FROM staged WHERE digest=?', (digest,)),
                     key=lambda row: _rank(row, protected))
        for candidate in plan.db.execute('SELECT * FROM staged WHERE digest=?', (digest,)):
            if candidate['path'] == winner['path']:
                continue
            metrics['duplicates'] += 1
            plan.db.execute('INSERT INTO duplicate_pairs VALUES (?,?,?,?,?)',
                            (winner['planned_id'], winner['path'], candidate['planned_id'],
                             candidate['path'], digest))
            if policy == 'hide':
                plan.db.execute('INSERT INTO visibility VALUES (?,?,?)',
                                (candidate['path'], winner['planned_id'], 'kept'))
        if done % 50 == 0 or done == groups:
            emit(dict(type='progress', done=done, total=groups, duplicates=metrics['duplicates']))
    # Explicit user hides must survive re-indexing, but only if the same
    # verified bundle still matches its keeper.  An old v0.9.40 automatic
    # `kept` state is NOT treated as a new user choice.
    if policy != 'hide':
        for path, data, digest in plan.db.execute('SELECT path,data,digest FROM staged'):
            record = json.loads(data)
            keeper = int(record.get('duplicate_of') or 0)
            if record.get('duplicate_state') != 'manual_hidden' or not keeper or not digest:
                continue
            known = plan.db.execute('SELECT digest FROM staged WHERE planned_id=?', (keeper,)).fetchone()
            if known is not None and known[0] == digest:
                plan.db.execute('INSERT OR REPLACE INTO visibility VALUES (?,?,?)',
                                (path, keeper, 'manual_hidden'))
    plan.db.commit()
    changes = 0
    for data, keeper, state in plan.db.execute('''SELECT s.data,v.keeper,v.state
            FROM staged s LEFT JOIN visibility v ON v.path=s.path'''):
        record = json.loads(data)
        if (int(record.get('duplicate_of') or 0) != int(keeper or 0)
                or str(record.get('duplicate_state') or '') != str(state or '')):
            changes += 1
    metrics['visibility_changed'] = changes
    return metrics['duplicates']


def _plan_replacements(plan, db, cancelled, metrics):
    """Promote a verified live duplicate if its former keeper disappeared.

    Do not rewrite or remove the old ID: queues and other external references
    can resolve it through a catalog_song_alias mapping instead.
    """
    plan.db.row_factory = sqlite3.Row
    plan.db.execute('CREATE TABLE replacements (old_id INTEGER PRIMARY KEY, new_id INTEGER NOT NULL)')
    alias_exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='catalog_song_alias'").fetchone()
    for old_id, digest in plan.db.execute('SELECT old_id,digest FROM missing WHERE digest IS NOT NULL'):
        stopped(cancelled)
        old = db.execute('SELECT * FROM songs WHERE id=?', (old_id,)).fetchone()
        if old is None:
            continue
        candidates = plan.db.execute("""SELECT s.* FROM staged s
            LEFT JOIN visibility v ON v.path=s.path
            WHERE s.digest=? AND v.keeper IS NULL ORDER BY s.planned_id""", (digest,))
        winner = min(candidates, key=lambda row: _rank(row, set()), default=None)
        if winner is None:
            continue
        new_id = winner['planned_id']
        if new_id == old_id:
            continue
        # Only primary IDs need an alias. Favorites of any missing exact copy
        # are merged with the new active keeper rather than lost.
        if not old['duplicate_of']:
            prior = (db.execute('SELECT new_id FROM catalog_song_alias WHERE old_id=?', (old_id,)).fetchone()
                     if alias_exists else None)
            if not prior or prior[0] != new_id:
                plan.db.execute('INSERT OR REPLACE INTO replacements VALUES (?,?)', (old_id, new_id))
        data = json.loads(winner['data'])
        if old['favorite']:
            data['favorite'] = 1
        if old['duplicate_preferred']:
            data['duplicate_preferred'] = 1
        if old['user_edited'] and not data.get('user_edited'):
            for key in ('code', 'title', 'artist', 'key_signature'):
                data[key] = old[key]
            data['user_edited'] = 1
        plan.db.execute('UPDATE staged SET data=? WHERE path=?',
                        (json.dumps(data, ensure_ascii=False), winner['path']))
    metrics['recovered_keepers'] = plan.db.execute('SELECT count(*) FROM replacements').fetchone()[0]


def _commit(library, plan, db, version, mode, policy, cancelled):
    # Stage all work first. Only this short transaction changes the live catalog.
    path = Path(plan.temp.name) / 'plan.db'
    plan.db.commit()
    db.execute('ATTACH DATABASE ? AS catalog_plan', (str(path),))
    try:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('PRAGMA main.data_version').fetchone()[0] != version:
            raise ValueError('ฐานเพลงถูกเปลี่ยนจากงานอื่นระหว่างสแกน กรุณาเริ่มใหม่')
        stopped(cancelled)
        db.execute('CREATE TABLE IF NOT EXISTS catalog_id_sequence (id INTEGER PRIMARY KEY CHECK(id=1), last_id INTEGER NOT NULL)')
        # Rebuild is scoped: never DELETE records outside the selected root.
        # Missing records become reversible tombstones with stable IDs.
        db.execute("""UPDATE songs SET duplicate_of=0,duplicate_state='missing',playable=0
            WHERE id IN (SELECT old_id FROM catalog_plan.missing)
              AND (duplicate_state<>'missing' OR duplicate_of<>0 OR playable<>0)""")
        statement = ('INSERT INTO songs(id,' + ','.join(COLUMNS) + ') VALUES (' +
                     ','.join('?' for _ in range(len(COLUMNS) + 1)) + ') ON CONFLICT(path) DO UPDATE SET ' +
                     ','.join(name + '=excluded.' + name for name in COLUMNS if name != 'path'))
        # Only changed rows are updated, to avoid FTS triggers and write amplification.
        cursor = plan.db.execute('''SELECT s.path,s.planned_id,s.data,v.keeper,v.state,s.scanned
            FROM staged s LEFT JOIN visibility v ON v.path=s.path ORDER BY s.path''')
        values = []
        for path, sid, data, keeper, state, scanned in cursor:
            stopped(cancelled)
            if not scanned and keeper is None:
                continue  # Never change a non-selected folder's status.
            record = json.loads(data)
            record['path'] = path
            record['duplicate_of'] = keeper or 0
            record['duplicate_state'] = state or ''
            record['search'] = normalize(' '.join(str(record.get(key) or '') for key in
                                                  ('code','title','artist','first_lyric','rhythm')))
            row = tuple(record.get(name, 0 if name in ('user_edited','favorite','duplicate_preferred','duplicate_of') else '')
                        for name in COLUMNS)
            existing = db.execute('SELECT '+','.join(COLUMNS)+' FROM songs WHERE path=?', (path,)).fetchone()
            if existing is not None and tuple(existing) == row:
                continue
            values.append((sid, *row))
            if len(values) >= 256:
                db.executemany(statement, values)
                values.clear()
        if values:
            db.executemany(statement, values)
        db.execute('''CREATE TABLE IF NOT EXISTS catalog_song_alias
                      (old_id INTEGER PRIMARY KEY, new_id INTEGER NOT NULL)''')
        # An original file that has returned takes precedence over an alias.
        db.execute('DELETE FROM catalog_song_alias WHERE old_id IN (SELECT old_id FROM catalog_plan.staged)')
        db.execute('''INSERT OR REPLACE INTO catalog_song_alias(old_id,new_id)
            SELECT old_id,new_id FROM catalog_plan.replacements''')
        stopped(cancelled)
        last = plan.db.execute('SELECT max(planned_id) FROM staged').fetchone()[0] or 0
        previous = db.execute('SELECT last_id FROM catalog_id_sequence WHERE id=1').fetchone()
        last = max(last, previous[0] if previous else 0)
        db.execute('INSERT OR REPLACE INTO catalog_id_sequence VALUES (1,?)', (last,))
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise
    finally:
        db.execute('DETACH DATABASE catalog_plan')


def _persist_cache(cache, plan, *, clear_pending=True):
    """Upsert only genuinely new/changed signatures; zero writes on no-op."""
    plan.db.commit()
    cache.execute('ATTACH DATABASE ? AS new_catalog', (str(Path(plan.temp.name)/'plan.db'),))
    try:
        before = cache.total_changes
        with cache:
            cache.execute("""INSERT INTO checked(path,stamp,size_key,digest,reader)
                SELECT path,stamp,size_key,digest,? FROM new_catalog.staged WHERE 1
                ON CONFLICT(path) DO UPDATE SET
                    stamp=excluded.stamp,size_key=excluded.size_key,
                    digest=excluded.digest,reader=excluded.reader
                WHERE checked.stamp IS NOT excluded.stamp
                   OR checked.size_key IS NOT excluded.size_key
                   OR checked.digest IS NOT excluded.digest
                   OR checked.reader IS NOT excluded.reader""", (CACHE_REV,))
        if clear_pending:
            # Only selected files verified on this pass. Pending files on
            # other disconnected drives remain queued for a later pass.
            with cache:
                cache.execute("""DELETE FROM pending WHERE path IN
                    (SELECT path FROM new_catalog.staged WHERE scanned=1)
                       OR path IN (SELECT path FROM new_catalog.missing)""")
        return cache.total_changes-before
    finally:
        cache.execute('DETACH DATABASE new_catalog')


def _verify_changed_files(plan, cancelled, *, strict=False):
    """Revalidate catalog candidates before commit and before auto shutdown.

    Only changed/new files are re-statted normally. In strict shutdown mode
    every selected item is checked because an unchanged file can also vanish
    after discovery. The signature includes the complete media bundle.
    """
    inspector = Inspector()
    query = 'SELECT path,stamp,size_key FROM staged WHERE scanned=1'
    if not strict:
        query += ' AND verify=1'
    for path, stamp, sizes in plan.db.execute(query):
        stopped(cancelled)
        try:
            latest, latest_size = signature(path, inspector)
            if latest != stamp or latest_size != sizes:
                raise ValueError('ไฟล์เปลี่ยนหลังจากสแกน')
        except (OSError, EOFError, ValueError) as error:
            raise ValueError(f'ไฟล์เพลงเปลี่ยนหรือไม่พร้อมใช้งานก่อนเสร็จงาน: {path}: {error}') from error


def _write_reports(library, plan, policy):
    output = library.path.parent
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    def write(name, header, rows):
        target = output / name
        temp = target.with_suffix('.tmp')
        with temp.open('w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.writer(stream)
            writer.writerow(header)
            writer.writerows(rows)
        os.replace(temp, target)
        reports.append(str(target))
    write('catalog-exact-duplicates.csv',
          ('รหัสรายการหลัก','ไฟล์หลัก','รหัสรายการซ้ำ','ไฟล์ซ้ำ','SHA-256 ของชุดเพลง','วิธีจัดการ'),
          ((a,b,c,d,e,policy) for a,b,c,d,e in plan.db.execute('SELECT * FROM duplicate_pairs')))
    # Same song title/artist/key or code with distinct media is NOT an exact duplicate.
    # List potential conflicts for review; retain all associated files.
    def variants(field):
        if field == 'identity':
            query = "SELECT identity FROM staged WHERE identity NOT LIKE 'path:%' GROUP BY identity HAVING count(*)>1"
        else:
            query = "SELECT code FROM staged WHERE code<>'' GROUP BY code HAVING count(*)>1"
        for (key,) in plan.db.execute(query):
            values = plan.db.execute(f'SELECT path,size_key,digest FROM staged WHERE {field}=?', (key,))
            # Cache only distinct content signatures, not the potentially huge
            # full group, before streaming the report rows to disk.
            has_more_than_one = len({value[0] for value in plan.db.execute(
                f"SELECT DISTINCT coalesce(digest,'unhashed-size:'||size_key) FROM staged WHERE {field}=? LIMIT 2",
                (key,))}) > 1
            if has_more_than_one:
                yield from ((key, *row) for row in values)
    write('catalog-possible-versions.csv',
          ('ชื่อ+ศิลปิน+คีย์','ไฟล์','กลุ่มขนาด','SHA-256 ถ้าตรวจแล้ว'), variants('identity'))
    write('catalog-code-collisions.csv',
          ('รหัสเพลง','ไฟล์','กลุ่มขนาด','SHA-256 ถ้าตรวจแล้ว'), variants('code'))
    write('catalog-missing-files.csv', ('รหัสรายการ','ไฟล์ที่ไม่พบ','SHA-256 เดิม (ถ้ามี)'),
          plan.db.execute("SELECT old_id,path,coalesce(digest,'') FROM missing ORDER BY path"))
    return reports



def regenerate_catalog_reports(library, *, duplicate_policy='hide', cancelled=None):
    """Recreate CSV reports from the COMMITTED catalog and known hash cache.

    No source media is opened. Hashes absent from the cache are represented as
    unknown; this is report repair, NOT a new integrity/duplicate verification.
    """
    if duplicate_policy not in DUP_POLICIES:
        raise ValueError('ตัวเลือกจัดการเพลงซ้ำไม่ถูกต้อง')
    with SongPlan() as plan, library.connect() as db:
        plan.db.execute("""CREATE TABLE staged(path TEXT PRIMARY KEY, planned_id INTEGER,
            size_key TEXT, digest TEXT, identity TEXT, code TEXT)""")
        plan.db.execute('CREATE TABLE duplicate_pairs(a INTEGER,b TEXT,c INTEGER,d TEXT,e TEXT)')
        plan.db.execute('CREATE TABLE missing(path TEXT PRIMARY KEY, old_id INTEGER, digest TEXT)')
        # Cache is optional. Recreating reports never requires reindexing or
        # opening song files on an offline drive.
        cache_file = _cache_path(library)
        cache = sqlite3.connect(cache_file) if cache_file.exists() else None
        try:
            for record in db.execute("SELECT * FROM songs WHERE duplicate_state NOT IN ('deleted','moved','recycled','excluded')"):
                stopped(cancelled)
                cached = None
                if cache is not None:
                    try:
                        cached = cache.execute('SELECT size_key,digest FROM checked WHERE path=?',
                                               (record['path'],)).fetchone()
                    except sqlite3.OperationalError:
                        cache.close()
                        cache = None
                size_key = cached[0] if cached else ''
                digest = cached[1] if cached else None
                if record['duplicate_state'] == 'missing':
                    plan.db.execute('INSERT INTO missing VALUES (?,?,?)',
                                    (record['path'], record['id'], digest))
                else:
                    plan.db.execute('INSERT INTO staged VALUES (?,?,?,?,?,?)',
                        (record['path'], record['id'], size_key, digest,
                         identity(record['title'], record['artist'], record['key_signature'])
                         or 'path:' + record['path'], str(record['code'] or '').strip().casefold()))
            # Respect actual keeper mappings in hide mode; show/review are
            # reconstructed from available exact digests (not title matching).
            rows = plan.db.execute('SELECT digest FROM staged WHERE digest IS NOT NULL GROUP BY digest HAVING count(*)>1')
            for (digest,) in rows:
                stopped(cancelled)
                group = list(plan.db.execute('SELECT planned_id,path FROM staged WHERE digest=? ORDER BY planned_id',
                                            (digest,)))
                keeper = group[0]
                for item in group[1:]:
                    plan.db.execute('INSERT INTO duplicate_pairs VALUES (?,?,?,?,?)',
                                    (keeper[0], keeper[1], item[0], item[1], digest))
            plan.db.commit()
            paths = _write_reports(library, plan, duplicate_policy)
            if cache is not None:
                with cache:
                    cache.execute("""CREATE TABLE IF NOT EXISTS settings
                        (key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
                    cache.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',
                                  ('report_policy', duplicate_policy))
            return paths
        finally:
            if cache is not None:
                cache.close()


def build_fast_catalog(library, source, songs_root, mode='fast', *, copy_external=False,
                       duplicate_policy='hide', cancelled=None, events=None, protected=(),
                       strict_shutdown_check=False):
    """Atomic index update, content-exact dedupe, and optional verified copy.

    Modes: quick indexes changed files without SHA/CSV and queues verification;
    fast verifies duplicate media and exports reports; full re-reads media;
    safe_rebuild re-reads selected files without touching other folders.
    """
    if mode not in SCANNED_MODES:
        raise ValueError('โหมดสร้างรายการเพลงไม่ถูกต้อง')
    duplicate_policy = 'review'  # v0.9.43: indexing never changes visibility.
    if duplicate_policy not in DUP_POLICIES:
        raise ValueError('ตัวเลือกจัดการเพลงซ้ำไม่ถูกต้อง')
    if mode == 'quick':
        from .quick_catalog import build_quick_catalog
        return build_quick_catalog(library, source, songs_root,
            copy_external=copy_external, duplicate_policy=duplicate_policy,
            cancelled=cancelled, events=events, protected=protected,
            strict_shutdown_check=strict_shutdown_check)
    emit = events or (lambda event: None)
    source = Path(canonical(Path(source)))
    managed = Path(canonical(Path(songs_root)))
    metrics = dict(unchanged=0,added=0,updated=0,failed=0,duplicates=0,
                   digest_reused=0,hashed=0,copied=0,staged_new_rows=0,
                   skipped_protected=0,outside_kept=0,outside_unavailable=0,
                   missing=0,missing_changed=0,recovered_keepers=0,scanned=0,warnings=[])
    stopped(cancelled)
    if copy_external:
        raise ValueError('v0.9.43 ไม่คัดลอกเพลงอัตโนมัติ กรุณาจัดวางไฟล์ใน Songs ด้วยตนเอง')
    with SongPlan() as plan, library.connect() as db:
        version = db.execute('PRAGMA main.data_version').fetchone()[0]
        cache = _make_cache(_cache_path(library))
        try:
            _scan(plan, library, db, cache, source, managed, mode, copy_external,
                  cancelled, emit, metrics)
            metrics['scanned'] = plan.count()
            _hash_candidates(plan, cache, cancelled, emit, metrics)
            if copy_external:
                _copy_external(plan, managed, cancelled, emit, metrics)
                # Copying creates new same-size candidates and precomputed hashes.
                _hash_candidates(plan, cache, cancelled, emit, metrics)
            if mode == 'safe_rebuild' and metrics['failed']:
                raise ValueError('สร้างใหม่ไม่ได้เพราะตรวจไฟล์บางรายการไม่สำเร็จ')
            _allocate_ids(plan, db)
            _duplicates(plan, duplicate_policy, set(protected), cancelled, emit, metrics)
            _plan_replacements(plan, db, cancelled, metrics)
            stopped(cancelled)
            changed = (mode != 'fast' or metrics['added'] > 0 or metrics['updated'] > 0
                       or metrics['visibility_changed'] > 0 or metrics['missing_changed'] > 0
                       or metrics['recovered_keepers'] > 0 or metrics['staged_new_rows'] > 0)
            if changed:
                emit(dict(type='phase', phase='สำรองฐานข้อมูลก่อนบันทึก', total=None))
                library.backup_before_rebuild(cancelled)
                stopped(cancelled)
                emit(dict(type='phase', phase='ตรวจไฟล์ที่เปลี่ยนก่อนบันทึก', total=None))
                _verify_changed_files(plan, cancelled)
                emit(dict(type='phase', phase='บันทึกฐานเพลงแบบ Transaction', total=None))
                _commit(library, plan, db, version, mode, duplicate_policy, cancelled)
            else:
                if db.execute('PRAGMA main.data_version').fetchone()[0] != version:
                    raise ValueError('ฐานเพลงถูกแก้ไขระหว่างตรวจ กรุณาเริ่มใหม่')
                stopped(cancelled)
                emit(dict(type='phase', phase='ไม่มีรายการเปลี่ยน — ข้ามการสำรองและเขียนฐานใหม่', total=None))
            # The live DB may already be committed. Subsequent report/cache
            # failures must NEVER be surfaced as if the entire build rolled back.
            metrics['catalog_committed'] = bool(changed)
            metrics['post_commit_errors'] = []
            paths = []
            try:
                integrity = db.execute('PRAGMA quick_check').fetchone()[0]
                if integrity != 'ok':
                    raise sqlite3.DatabaseError('ตรวจความสมบูรณ์ฐานเพลงไม่ผ่าน: ' + str(integrity))
                metrics['cache_writes'] = _persist_cache(cache, plan, clear_pending=(metrics['failed']==0))
            except (OSError, ValueError, sqlite3.Error) as error:
                metrics['post_commit_errors'].append('ตรวจฐาน/อัปเดตแคชไม่สำเร็จ: ' + str(error))
                metrics['cache_writes'] = None
            try:
                report_row = cache.execute("SELECT value FROM settings WHERE key='report_policy'").fetchone()
                names = ('catalog-exact-duplicates.csv','catalog-possible-versions.csv',
                         'catalog-code-collisions.csv','catalog-missing-files.csv')
                if not changed and report_row and report_row[0] == duplicate_policy and all(
                        (library.path.parent/name).is_file() for name in names):
                    paths = [str(library.path.parent/name) for name in names]
                    metrics['reports_reused'] = True
                else:
                    paths = _write_reports(library, plan, duplicate_policy)
                    with cache:
                        cache.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('report_policy', duplicate_policy))
                    metrics['reports_reused'] = False
            except (OSError, ValueError, sqlite3.Error) as error:
                metrics['post_commit_errors'].append('ส่งออกรายงานไม่สำเร็จ: ' + str(error))
                metrics['reports_reused'] = False
            # Recheck ALL selected bundles only for the opt-in automatic shutdown.
            # A drive disconnected during/after scanning must disable power off.
            if strict_shutdown_check:
                emit(dict(type='phase', phase='ตรวจความพร้อมเพลงก่อนปิดเครื่อง', total=None))
                try:
                    _verify_changed_files(plan, cancelled, strict=True)
                except ValueError as error:
                    metrics['post_commit_errors'].append(str(error))
            else:
                try:
                    _verify_changed_files(plan, cancelled)
                except ValueError as error:
                    metrics['post_commit_errors'].append(str(error))
            metrics['pending'] = cache.execute('SELECT count(*) FROM pending').fetchone()[0]
            count = library.count()
            metrics['catalog'] = count
            errors = metrics['warnings']
            summary = (f'รายการที่ค้นหาได้ {count:,} · ไม่เปลี่ยน {metrics["unchanged"]:,} · '
                       f'ใหม่ {metrics["added"]:,} · เปลี่ยน {metrics["updated"]:,} · '
                       f'ซ้ำจริง {metrics["duplicates"]:,} · ไฟล์หาย {metrics["missing"]:,} · '
                       f'ไม่รองรับ {plan.omitted:,} · อ่านไม่ได้ {metrics["failed"]:,} · '
                       f'คัดลอก {metrics["copied"]:,}')
            notes = [summary]
            if paths:
                notes += ['รายงานเพลงซ้ำ: ' + paths[0], 'รายงานเพลงชื่อเดียวกัน: ' + paths[1],
                          'รายงานรหัสชนกัน: ' + paths[2], 'รายงานไฟล์ที่หาย: ' + paths[3]]
            notes += errors
            if metrics['post_commit_errors']:
                notes.insert(1, ('ฐานเพลงบันทึกแล้ว แต่ขั้นตอนหลังบันทึกไม่สมบูรณ์: ' if changed
                                 else 'สร้างรายการแล้ว แต่การตรวจขั้นสุดท้ายไม่สมบูรณ์: ') +
                             '; '.join(metrics['post_commit_errors']))
            metrics['unsupported'] = plan.omitted
            metrics['result_status'] = ('success' if not (metrics['failed'] or metrics['missing'] or
                plan.omitted or not metrics['scanned'] or metrics['post_commit_errors']) else 'partial')
            return CatalogBuildResult(count, metrics['duplicates']+metrics['failed']+plan.omitted+metrics['missing'],
                                      notes, safe_to_shutdown=(metrics['result_status']=='success'
                                                               and not (cancelled and cancelled.is_set())),
                                      duplicate_report=(paths[0] if paths else None), metrics=metrics)
        finally:
            cache.close()
