"""Phase-one index: make new/changed songs searchable before exact deduplication.

This deliberately never guesses that equal names/sizes mean equal songs, never
hides a pending entry, and never deletes a media file. The normal `fast` catalog
pass remains the authoritative phase-two verifier; work is persisted in the
fast-catalog cache so it can resume after restarting X-Stage.
"""
from __future__ import annotations

import json
import sqlite3
import os
import time
from contextlib import closing
from pathlib import Path

from .catalog_maintenance import COLUMNS, _inspect
from .index_plan import SongPlan
from .ingest import Inspector
from .incremental import signature, trusted_stamp
from .legacy import catalog_location
from .library import SearchCancelled, canonical, normalize
from .managed_import import catalog_hints, stopped
from .fast_catalog import CACHE_REV, CatalogBuildResult, _cache_path, _make_cache, _stage


def pending_count(library):
    """Number of changes awaiting the exact-content/duplicate verification."""
    path = _cache_path(library)
    if not path.is_file():
        return 0
    with closing(_make_cache(path)) as cache:
        return cache.execute('SELECT count(*) FROM pending').fetchone()[0]


def _quick_commit(library, plan, db, version, cancelled):
    """Only changed rows and scoped missing IDs are written in one transaction."""
    plan.db.commit()
    db.execute('ATTACH DATABASE ? AS quick_plan', (str(Path(plan.temp.name) / 'plan.db'),))
    try:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('PRAGMA main.data_version').fetchone()[0] != version:
            raise ValueError('ฐานเพลงถูกเปลี่ยนระหว่างสร้างรายการ กรุณาเริ่มใหม่')
        stopped(cancelled)
        db.execute('''CREATE TABLE IF NOT EXISTS catalog_id_sequence
                      (id INTEGER PRIMARY KEY CHECK(id=1), last_id INTEGER NOT NULL)''')
        db.execute('''UPDATE songs SET
            duplicate_of=CASE WHEN duplicate_state='manual_hidden' THEN duplicate_of ELSE 0 END,
            duplicate_state=CASE WHEN duplicate_state='manual_hidden' THEN duplicate_state ELSE 'missing' END,
            playable=0 WHERE id IN (SELECT old_id FROM quick_plan.missing)
              AND (duplicate_state<>'missing' OR duplicate_of<>0 OR playable<>0)''')
        # A missing keeper cannot keep the only live copy hidden. Showing a
        # previously verified copy is safe; phase two may choose its keeper.
        db.execute('''UPDATE songs SET duplicate_of=0, duplicate_state=''
            WHERE duplicate_of IN (SELECT old_id FROM quick_plan.missing)
              AND playable=1 AND duplicate_state='kept'
              AND path IN (SELECT path FROM quick_plan.files)''')
        columns = ','.join(COLUMNS)
        sql = ('INSERT INTO songs(id,' + columns + ') VALUES (' + ','.join('?' for _ in range(len(COLUMNS)+1)) + ') '
               'ON CONFLICT(path) DO UPDATE SET ' + ','.join(
                   name + '=' + (
                     "CASE WHEN songs.duplicate_state='manual_hidden' THEN songs.duplicate_state ELSE excluded.duplicate_state END"
                     if name == 'duplicate_state' else
                     "CASE WHEN songs.duplicate_state='manual_hidden' THEN songs.duplicate_of ELSE excluded.duplicate_of END"
                     if name == 'duplicate_of' else 'excluded.' + name)
                   for name in COLUMNS if name != 'path'))
        data = []
        for sid, path, encoded in db.execute('SELECT planned_id,path,data FROM quick_plan.staged ORDER BY path'):
            stopped(cancelled)
            record = json.loads(encoded)
            record['path'] = path
            record['duplicate_of'] = 0
            record['duplicate_state'] = ''
            record['search'] = normalize(' '.join(str(record.get(name) or '')
                for name in ('code','title','artist','first_lyric','rhythm')))
            values = tuple(record.get(name, 0 if name in (
                'user_edited','favorite','duplicate_preferred','duplicate_of') else '') for name in COLUMNS)
            data.append((sid, *values))
            if len(data) == 256:
                db.executemany(sql, data)
                data.clear()
        if data:
            db.executemany(sql, data)
        # An existing alias must not redirect an original that is now present.
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='catalog_song_alias'").fetchone():
            db.execute('DELETE FROM catalog_song_alias WHERE old_id IN (SELECT old_id FROM quick_plan.staged)')
        last = plan.db.execute('SELECT max(planned_id) FROM staged').fetchone()[0] or 0
        previous = db.execute('SELECT last_id FROM catalog_id_sequence WHERE id=1').fetchone()
        db.execute('INSERT OR REPLACE INTO catalog_id_sequence VALUES (1,?)',
                   (max(last, previous[0] if previous else 0),))
        stopped(cancelled)
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise
    finally:
        db.execute('DETACH DATABASE quick_plan')


def _quick_cache(cache, plan):
    """Transactional pending queue, durable across app restarts (no file hashes)."""
    plan.db.commit()
    cache.execute('ATTACH DATABASE ? AS quick_plan', (str(Path(plan.temp.name) / 'plan.db'),))
    try:
        with cache:
            cache.execute('''INSERT INTO checked(path,stamp,size_key,digest,reader)
                SELECT path,stamp,size_key,NULL,? FROM quick_plan.staged WHERE 1
                ON CONFLICT(path) DO UPDATE SET
                  stamp=excluded.stamp,size_key=excluded.size_key,digest=NULL,reader=excluded.reader''', (CACHE_REV,))
            cache.execute('''INSERT INTO pending(path,stamp,size_key)
                SELECT path,stamp,size_key FROM quick_plan.staged WHERE 1
                ON CONFLICT(path) DO UPDATE SET stamp=excluded.stamp,size_key=excluded.size_key''')
        return plan.db.execute('SELECT count(*) FROM staged').fetchone()[0]
    finally:
        cache.execute('DETACH DATABASE quick_plan')


def build_quick_catalog(library, source, songs_root, *, copy_external=False,
                        duplicate_policy='hide', cancelled=None, events=None,
                        protected=(), strict_shutdown_check=False):
    """Quick index. Phase-two verification uses build_fast_catalog(mode='fast').

    Under a quick pass, exact-content status is *unknown* for changed files.
    Report generation, copies and optional poweroff intentionally do not run.
    """
    if copy_external:
        raise ValueError('v0.9.43 ยกเลิกการคัดลอกอัตโนมัติ: คัดลอกไฟล์ลง Songs เองก่อนสร้างรายการ')
    if strict_shutdown_check:
        raise ValueError('โหมดด่วนไม่รองรับปิดเครื่องอัตโนมัติ กรุณาใช้โหมดตรวจละเอียด')
    emit = events or (lambda event: None)
    source = Path(canonical(Path(source)))
    managed = Path(canonical(Path(songs_root)))
    try:
        _, base = catalog_location(source)
    except ValueError:
        base = None
    scan_root = base/'Songs' if base and (base/'Songs').is_dir() else source
    if not scan_root.is_dir():
        raise ValueError('ไม่พบโฟลเดอร์เพลง: ' + str(scan_root))
    metrics = dict(added=0, updated=0, unchanged=0, failed=0, missing=0,
                   duplicates=0, hashed=0, cache_writes=0, catalog_committed=False,
                   result_status='partial', reports_deferred=True, warnings=[], phase='quick')
    start = time.perf_counter()
    with SongPlan() as plan, library.connect() as db:
        version = db.execute('PRAGMA main.data_version').fetchone()[0]
        cache = _make_cache(_cache_path(library))
        try:
            emit(dict(type='phase', phase='ระยะที่ 1/2 — สำรวจชื่อไฟล์เพลง', total=None))
            plan.folder(scan_root, cancelled=cancelled, events=emit)
            if base:
                catalog_hints(plan, source, cancelled)
            stopped(cancelled)
            problems = [note for note in plan.errors if not note.startswith(('ยังไม่รองรับ:', 'ดัชนีเดิม:'))]
            if problems:
                raise ValueError('สแกนโฟลเดอร์ไม่ครบ จึงไม่แก้ฐานเพลง: ' + problems[0])
            metrics['inventory_seconds'] = round(time.perf_counter()-start, 4)
            plan.db.execute('''CREATE TABLE staged(
                path TEXT PRIMARY KEY, old_id INTEGER, planned_id INTEGER, stamp TEXT NOT NULL,
                size_key TEXT NOT NULL, digest TEXT, data TEXT NOT NULL, managed INTEGER NOT NULL,
                scanned INTEGER NOT NULL, code TEXT, identity TEXT,
                verify INTEGER NOT NULL DEFAULT 0)''')
            plan.db.execute('CREATE TABLE missing(path TEXT PRIMARY KEY, old_id INTEGER NOT NULL)')
            # SQL joins leverage path primary keys; unchanged rows never enter staged.
            plan.db.commit()
            plan.db.execute('ATTACH DATABASE ? AS catalog_existing', (str(library.path),))
            plan.db.execute('ATTACH DATABASE ? AS checked_existing', (str(_cache_path(library)),))
            inspector = Inspector()
            emit(dict(type='phase', phase='ระยะที่ 1/2 — ตรวจเฉพาะข้อมูลใหม่และเปลี่ยน', total=plan.count()))
            checked = 0
            try:
                sql = '''SELECT f.path,s.id,s.duplicate_state,c.stamp,c.reader
                    FROM files f LEFT JOIN catalog_existing.songs s ON s.path=f.path
                    LEFT JOIN checked_existing.checked c ON c.path=f.path ORDER BY f.path'''
                for path, old_id, state, cached_stamp, reader in plan.db.execute(sql):
                    stopped(cancelled)
                    if not Path(path).is_relative_to(scan_root):
                        continue  # Ignore out-of-root paths from legacy catalog hints.
                    checked += 1
                    try:
                        if Path(path).is_symlink() or getattr(Path(path), 'is_junction', lambda: False)():
                            raise ValueError('ไม่รองรับลิงก์ไฟล์เพลง')
                        stamp, sizes = signature(path, inspector)
                        if old_id is not None and state not in ('missing','deleted','moved','recycled','excluded') and (
                                cached_stamp == stamp and reader == CACHE_REV and trusted_stamp(stamp)):
                            metrics['unchanged'] += 1
                            continue
                        if state in ('deleted','moved','recycled','excluded'):
                            continue  # Do not resurrect protected tombstones.
                        old = db.execute('SELECT * FROM songs WHERE path=?', (path,)).fetchone()
                        record = _inspect(inspector, plan, path, old)
                        if signature(path, inspector)[0] != stamp:
                            raise ValueError('ไฟล์เปลี่ยนขณะอ่านข้อมูลเพลง')
                        _stage(plan, path, old, stamp, sizes, None, record, managed, verify=1)
                        metrics['updated' if old else 'added'] += 1
                    except SearchCancelled:
                        raise
                    except (OSError, ValueError, EOFError, sqlite3.Error) as error:
                        metrics['failed'] += 1
                        if len(metrics['warnings']) < 30:
                            metrics['warnings'].append(f'{path}: {error}')
                    if checked % 512 == 0 or checked == plan.count():
                        emit(dict(type='progress', done=checked, total=plan.count(), path=path,
                                  added=metrics['added'], updated=metrics['updated']))
                # This JOIN only materializes old paths absent from selected inventory;
                # outside folders/drives are neither checked nor modified.
                sql_missing = '''SELECT s.id,s.path,s.duplicate_state,s.playable,s.duplicate_of
                    FROM catalog_existing.songs s LEFT JOIN files f ON f.path=s.path
                    WHERE s.path>=? AND s.path<? AND f.path IS NULL
                      AND s.duplicate_state NOT IN ('deleted','moved','recycled','excluded')'''
                prefix = str(scan_root).rstrip('\\/') + os.sep
                for sid, path, state, playable, keeper in plan.db.execute(
                        sql_missing, (prefix, prefix + chr(0x10ffff))):
                    stopped(cancelled)
                    if not Path(path).is_relative_to(scan_root):
                        continue
                    if Path(path).is_file():
                        raise ValueError('พบไฟล์เดิมที่ไม่ได้อยู่ในผลสแกน กรุณาเริ่มใหม่: ' + path)
                    if state != 'missing' or playable or keeper:
                        plan.db.execute('INSERT OR IGNORE INTO missing VALUES (?,?)', (path, sid))
                        metrics['missing'] += 1
            finally:
                plan.db.commit()
                plan.db.execute('DETACH DATABASE checked_existing')
                plan.db.execute('DETACH DATABASE catalog_existing')
            metrics['scanned'] = checked
            metrics['read_seconds'] = round(time.perf_counter()-start-metrics['inventory_seconds'], 4)
            changed = bool(metrics['added'] or metrics['updated'] or metrics['missing'])
            if changed:
                stopped(cancelled)
                # Protected IDs and source filenames remain stable. New rows are
                # allocated only after discovering the entire selected inventory.
                from .fast_catalog import _allocate_ids, _verify_changed_files
                _allocate_ids(plan, db)
                # A potentially destructive status change keeps a checked backup;
                # append-only quick updates skip the large full-database snapshot.
                if metrics['updated'] or metrics['missing']:
                    emit(dict(type='phase', phase='สำรองฐานก่อนเปลี่ยนรายการเดิม', total=None))
                    library.backup_before_rebuild(cancelled)
                emit(dict(type='phase', phase='ยืนยันไฟล์ใหม่ก่อนบันทึกฐาน', total=None))
                _verify_changed_files(plan, cancelled)
                emit(dict(type='phase', phase='บันทึกรายการด่วนแบบ Transaction', total=None))
                _quick_commit(library, plan, db, version, cancelled)
                metrics['catalog_committed'] = True
            else:
                if db.execute('PRAGMA main.data_version').fetchone()[0] != version:
                    raise ValueError('ฐานเพลงถูกเปลี่ยนระหว่างสแกน กรุณาเริ่มใหม่')
                emit(dict(type='phase', phase='ไม่พบรายการเปลี่ยน — ไม่เขียนฐานเพลง', total=None))
            # Cache and reports are post-commit operations, never reported as rollback.
            metrics['post_commit_errors'] = []
            if metrics['catalog_committed']:
                try:
                    metrics['cache_writes'] = _quick_cache(cache, plan)
                except (OSError, ValueError, sqlite3.Error) as error:
                    metrics['post_commit_errors'].append('บันทึกคิวตรวจเพลงซ้ำไม่สำเร็จ: ' + str(error))
            metrics['pending'] = cache.execute('SELECT count(*) FROM pending').fetchone()[0]
            metrics['catalog'] = library.count()
            metrics['total_seconds'] = round(time.perf_counter()-start, 4)
            metrics['result_status'] = ('partial' if (metrics['failed'] or plan.omitted or metrics['missing']
                                                      or metrics['post_commit_errors']) else 'success')
            notes = [f'สร้างรายการด่วนแล้ว · ค้นหาได้ {metrics["catalog"]:,} เพลง · '
                     f'เพิ่ม {metrics["added"]:,} · ปรับ {metrics["updated"]:,} · '
                     f'รอตรวจเพลงซ้ำ {metrics["pending"]:,} รายการ',
                     'ยังไม่ยืนยันไฟล์ซ้ำ/ไม่สร้าง CSV ระหว่างสร้างด่วน — เลือก “ตรวจเพลงซ้ำละเอียด” ภายหลัง']
            notes.extend(metrics['warnings'])
            notes.extend(metrics['post_commit_errors'])
            return CatalogBuildResult(metrics['catalog'], metrics['failed']+plan.omitted+metrics['missing'],
                                      notes, safe_to_shutdown=False, duplicate_report=None, metrics=metrics)
        finally:
            cache.close()
