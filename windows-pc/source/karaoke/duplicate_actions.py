"""Explicit post-index Song Bundle actions. Nothing deletes automatically.

No copies/quarantine of media are made. Permanent deletion is opt-in and audited.
"""
import json
import os
import time
import uuid
import threading
from contextlib import contextmanager
from pathlib import Path
from .duplicates import prepare_action, digest, recycle_files
from .library import canonical, write_json


_batch = threading.local()


@contextmanager
def action_batch(library):
    """Share a single verified database backup across one UI action batch."""
    previous = getattr(_batch, 'state', None)
    _batch.state = {'library': str(library.path.resolve()), 'backed_up': False}
    try:
        yield
    finally:
        _batch.state = previous


def _backup(library):
    state = getattr(_batch, 'state', None)
    if state is not None and state['library'] == str(library.path.resolve()):
        if state['backed_up']:
            return
        library.backup_before_rebuild()
        state['backed_up'] = True
    else:
        library.backup_before_rebuild()


def _guard_file(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError('ไฟล์ไม่อยู่หรือเป็นลิงก์: ' + str(path))
    if any(parent.is_symlink() or getattr(parent, 'is_junction', lambda: False)()
           for parent in path.parents):
        raise ValueError('ไม่จัดการไฟล์ภายใต้โฟลเดอร์ลิงก์: ' + str(path))


def _protected(value):
    return set(value() if callable(value) else value)


def _pair(library, song_id, keeper_id, protected):
    return prepare_action(library, song_id, protected=_protected(protected), keeper_id=keeper_id)


def hide_exact(library, song_id, keeper_id, *, protected=()):
    row, parts, _ = _pair(library, song_id, keeper_id, protected)
    _backup(library)
    with library.connect() as db:
        db.execute("UPDATE songs SET duplicate_of=?,duplicate_state='manual_hidden' WHERE id=?",
                   (keeper_id, song_id))
    return len(parts)


def show_song(library, song_id):
    row = library.get(song_id)
    if not row or row['duplicate_state'] != 'manual_hidden':
        raise ValueError('รายการนี้ไม่ได้ถูกซ่อนโดยผู้ใช้')
    with library.connect() as db:
        db.execute("UPDATE songs SET duplicate_of=0,duplicate_state='' WHERE id=?", (song_id,))


def exclude_from_index(library, song_id, *, protected=()):
    row = library.get(song_id)
    if row is None or row['duplicate_state'] in ('deleted','recycled','moved'):
        raise ValueError('รายการนี้ไม่สามารถนำออกจากฐานได้')
    if song_id in _protected(protected) or row['favorite'] or row['user_edited']:
        raise ValueError('รายการที่ใช้งานอยู่ เพลงโปรดหรือแก้ไขเองต้องจัดการก่อน')
    _backup(library)
    with library.connect() as db:
        # A tombstone prevents next index from silently importing the file again.
        db.execute("UPDATE songs SET duplicate_of=0,duplicate_state='excluded',playable=0 WHERE id=?", (song_id,))
    return True


def restore_to_index(library, song_id):
    row = library.get(song_id)
    if not row or row['duplicate_state'] != 'excluded':
        raise ValueError('รายการนี้ไม่ใช่รายการที่นำออกจากฐาน')
    if not Path(row['path']).is_file():
        raise ValueError('ไฟล์ต้นฉบับไม่อยู่แล้ว')
    from .ingest import Inspector
    record, warnings = Inspector().inspect(row['path'])
    if not record.get('playable'):
        raise ValueError('เพลงยังเล่นไม่ได้ ไม่สามารถคืนเข้าผลค้นหา')
    with library.connect() as db:
        db.execute("UPDATE songs SET duplicate_of=0,duplicate_state='',playable=1 WHERE id=?", (song_id,))


def _audit(library, operation, row, keeper_id, parts, hashes):
    parent = library.path.parent / 'duplicate-action-logs'
    parent.mkdir(exist_ok=True)
    journal = parent / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex + '.json')
    record = dict(version=1, action=operation, song_id=row['id'], keeper_id=keeper_id,
                  status='prepared', files=[dict(role=role,path=str(path),sha256=hashes[role])
                                             for role,path in parts.items()],
                  deleted=[], failures=[], no_media_backup=True)
    write_json(journal, record)
    return journal, record


def delete_permanently(library, song_id, keeper_id, *, protected=(), confirmation=None):
    """Fail-closed, Windows-only permanent Song Bundle delete via verified handles.

    Never reopen a pathname for unlink after verifying a different handle.
    No media copies or quarantine are created. A journal retains partial failures.
    """
    if confirmation != 'ลบถาวร':
        raise ValueError('ต้องยืนยันด้วยคำว่า ลบถาวร ก่อนดำเนินการ')
    if os.name != 'nt':
        raise OSError('เพื่อความปลอดภัย การลบถาวรรุ่นนี้รองรับเฉพาะ Windows NTFS เท่านั้น')
    from .verified_delete import delete_verified
    row, parts, hashes = _pair(library, song_id, keeper_id, protected)
    proof = {}
    for role, path in parts.items():
        _guard_file(path)
        stat = Path(path).stat()
        if stat.st_nlink != 1:
            raise ValueError('ไฟล์มี hard link หลายชื่อ ไม่อนุญาตลบ: ' + str(path))
        proof[role] = dict(path=str(path), device=stat.st_dev, inode=stat.st_ino,
                           size=stat.st_size, mtime=stat.st_mtime_ns, sha256=hashes[role])
    _backup(library)
    journal, record = _audit(library, 'permanent', row, keeper_id, parts, hashes)
    try:
        for role, path in parts.items():
            if song_id in _protected(protected):
                raise ValueError('รายการเข้าคิวระหว่างลบ')
            _guard_file(path)
            # Validate content AND identity on the same native handle used to delete.
            delete_verified(proof[role])
            record['deleted'].append(str(path))
            record['status'] = 'partial'
            write_json(journal, record)
    except BaseException as error:
        # A native delete can complete before a subsequent close/journal write
        # reports an exception. Reconcile what is actually missing on disk.
        missing=[str(path) for path in parts.values() if not Path(path).exists()]
        record['deleted']=list(dict.fromkeys([*record['deleted'], *missing]))
        record['status'] = 'partial' if record['deleted'] else 'blocked'
        record['failures'].append(str(error)); write_json(journal, record)
        if record['deleted']:
            with library.connect() as db:
                db.execute("UPDATE songs SET duplicate_of=0,duplicate_state='missing',playable=0 WHERE id=?", (song_id,))
        raise
    with library.connect() as db:
        db.execute("UPDATE songs SET duplicate_of=?,duplicate_state='deleted',playable=0 WHERE id=?", (keeper_id,song_id))
    record['status'] = 'deleted'
    write_json(journal, record)
    return journal


def send_to_recycle_bin(library, song_id, keeper_id, *, protected=()):
    row, parts, hashes = _pair(library, song_id, keeper_id, protected)
    original = {}
    for role, path in parts.items():
        _guard_file(path)
        stat = Path(path).stat()
        if stat.st_nlink != 1:
            raise ValueError('ไฟล์มี hard link หลายชื่อ ไม่อนุญาตย้าย: ' + str(path))
        original[role] = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    _backup(library)
    journal, record = _audit(library, 'recycle', row, keeper_id, parts, hashes)
    error = None
    try:
        for role,path in parts.items():
            if song_id in _protected(protected):
                raise ValueError('เพลงถูกเพิ่มเข้าคิวระหว่างตรวจ')
            _guard_file(path)
            stat=Path(path).stat()
            if (stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns) != original[role]:
                raise ValueError('ไฟล์ถูกสลับระหว่างเตรียมเข้าถังรีไซเคิล')
            if digest(path) != hashes[role]:
                raise ValueError('ไฟล์เปลี่ยนก่อนส่งถังรีไซเคิล')
        recycle_files(list(parts.values()))
    except BaseException as exc:
        error = exc
    finally:
        missing = [str(p) for p in parts.values() if not Path(p).exists()]
        record['deleted'] = missing
        record['status'] = 'recycled' if len(missing) == len(parts) and error is None else ('partial' if missing else 'blocked')
        if error is not None:
            record['failures'].append(str(error))
        write_json(journal, record)
        if missing:
            with library.connect() as db:
                db.execute('UPDATE songs SET duplicate_of=?,duplicate_state=?,playable=0 WHERE id=?',
                           (keeper_id, 'recycled' if record['status']=='recycled' else 'missing', song_id))
    if error is not None:
        raise error
    if record['status']!='recycled':
        raise OSError('การย้ายไปถังรีไซเคิลยังไม่เสร็จครบทุกไฟล์: '+str(journal))
    return journal
