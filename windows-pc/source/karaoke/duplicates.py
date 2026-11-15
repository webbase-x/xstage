"""Exact-content duplicate groups. Never delete media during indexing."""
from pathlib import Path
from collections import defaultdict
import ctypes
import hashlib
import json
import os
import shutil
import uuid
from .ingest import Inspector
from .library import canonical, write_json, SearchCancelled, MIDI_EXT


def digest(path, cancelled=None, events=None):
    path = Path(path)
    before = path.stat()
    if not path.is_file() or path.is_symlink():
        raise ValueError('ไม่ใช้ไฟล์ลิงก์ในการจัดการเพลงซ้ำ: ' + str(path))
    h = hashlib.sha256()
    consumed=0
    with path.open('rb') as stream:
        while True:
            if cancelled and cancelled.is_set():
                raise SearchCancelled()
            data = stream.read(1024*1024)
            if not data:
                break
            h.update(data)
            consumed+=len(data)
            if events:events(dict(type='progress',path=str(path),bytes_done=consumed,bytes_total=before.st_size))
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError('ไฟล์เปลี่ยนระหว่างตรวจ: ' + str(path))
    return h.hexdigest()


def bundle(path, inspector=None):
    inspector = inspector or Inspector()
    path = Path(path)
    parts = {'media': path}
    kind = 'midi' if path.suffix.lower() in MIDI_EXT - {'.emk'} else path.suffix.lower()
    if kind == 'midi':
        lyr, cur = inspector.ncn_pair(path)
        def exists(file):
            return file.name.casefold() in inspector.listing(file.parent) and file.is_file()
        has_lyr,has_cur=exists(lyr),exists(cur)
        if has_lyr != has_cur:
            raise ValueError('ชุด NCN ไม่ครบ LYR/CUR: ' + str(path))
        if has_lyr:
            parts.update(lyrics=lyr, cursor=cur)
    for extension in ('.lrc', '.snf'):
        companion = inspector.sibling(path.with_suffix(extension))
        if companion.name.casefold() in inspector.listing(companion.parent) and companion.is_file():
            parts[extension[1:]] = companion
    return kind, parts


def fingerprint(path, cancelled=None, events=None, validate=True, inspector=None):
    inspector = inspector or Inspector()
    # Reject a corrupt/incomplete playable format before treating it as a keeper.
    if validate:
        inspector.inspect(path)
    kind, parts = bundle(path, inspector)
    hashes = {role: digest(file, cancelled, events) for role, file in parts.items()}
    return (kind, tuple(sorted(hashes.items()))), parts, hashes


def scan(library, protected=(), cancelled=None, progress=None, events=None, *, verify_only=True):
    """Read-only content-exact duplicate report; never change catalog visibility."""
    if not verify_only:
        raise ValueError('รุ่น v0.9.43 ไม่อนุญาตให้การตรวจเพลงซ้ำซ่อนรายการเอง ให้ใช้คำสั่งผู้ใช้แยกต่างหาก')
    protected = set(protected)
    with library.connect() as db:
        rows = [dict(row) for row in db.execute("SELECT * FROM songs WHERE duplicate_of=0 AND duplicate_state NOT IN ('moved','recycled','deleted','excluded','missing','invalid') ORDER BY id")]
    buckets, groups, errors = defaultdict(list), [], []
    inspector = Inspector()
    if events:events(dict(type='phase',phase='จัดกลุ่มขนาดไฟล์เพื่อตรวจซ้ำ',total=len(rows)))
    try:
        for n, row in enumerate(rows, 1):
            if cancelled and cancelled.is_set():
                raise SearchCancelled()
            try:
                kind, parts = bundle(row['path'], inspector)
                sizes = tuple((role, file.stat().st_size) for role, file in sorted(parts.items()))
                buckets[(kind, sizes)].append(row)
            except (OSError, ValueError) as error:
                errors.append(str(error))
            if events:events(dict(type='progress',done=n,total=len(rows),path=row['path']))
            if progress and n % 100 == 0:
                progress(n)
        target=sum(len(items) for items in buckets.values() if len(items)>1)
        if events:events(dict(type='phase',phase='ตรวจเนื้อหาเพลงซ้ำ',total=target))
        n = 0
        for candidates in buckets.values():
            if len(candidates) < 2:
                continue
            matched = defaultdict(list)
            for row in candidates:
                if cancelled and cancelled.is_set():
                    raise SearchCancelled()
                if events:events(dict(type='progress',done=n,total=target,path=row['path']))
                try:
                    key, _, _ = fingerprint(row['path'], cancelled, events, validate=False, inspector=inspector)
                    matched[key].append(row)
                except (OSError, ValueError, EOFError) as error:
                    errors.append(str(error))
                n += 1
                if events:events(dict(type='progress',done=n,total=target,path=row['path']))
                if progress:
                    progress(n)
            for expected, members in matched.items():
                if len(members) < 2:
                    continue
                members.sort(key=lambda row: (not row['duplicate_preferred'], row['id'] not in protected, not row['user_edited'],
                                              not row['favorite'], row['id']))
                try:
                    # Identical bytes and sidecars require one format parse per group,
                    # not a second MIDI parse for every imported copy.
                    validated, _, _ = fingerprint(members[0]['path'], cancelled, inspector=inspector)
                    if validated != expected:
                        raise ValueError('ไฟล์หลักเปลี่ยนระหว่างตรวจกลุ่ม')
                except (OSError, ValueError, EOFError) as error:
                    errors.append('ไม่ซ่อนกลุ่มที่ตรวจความพร้อมไม่ได้: '+str(error))
                    continue
                groups.append(members)
        if cancelled and cancelled.is_set():
            raise SearchCancelled()
    except SearchCancelled:
        return None, errors
    if events:events(dict(type='phase',phase='บันทึกผลเพลงซ้ำ',total=None))
    # Report generation never changes the library; explicit action commands
    # re-check Song Bundle hashes immediately before altering any state.
    return groups, errors


def groups(library):
    with library.connect() as db:
        return [dict(row) for row in db.execute('SELECT d.*, k.path AS keeper_path, k.title AS keeper_title '
                    'FROM songs d JOIN songs k ON k.id=d.duplicate_of WHERE d.duplicate_of<>0 ORDER BY d.duplicate_of,d.id')]


def choose_keeper(library, song_id):
    row = library.get(song_id)
    if not row or not row['duplicate_of'] or row['duplicate_state'] != 'kept':
        raise ValueError('เลือกชุดซ้ำที่ยังอยู่ที่เดิมเท่านั้น')
    old_id = row['duplicate_of']
    expected = fingerprint(row['path'])[0]
    with library.connect() as db:
        rows = [dict(r) for r in db.execute("SELECT * FROM songs WHERE (id=? OR duplicate_of=?) AND duplicate_state NOT IN ('moved','recycled','deleted')", (old_id, old_id))]
    for member in rows:
        if fingerprint(member['path'])[0] != expected:
            raise ValueError('ไฟล์ในกลุ่มเปลี่ยน ต้องตรวจเพลงซ้ำใหม่')
    library.backup_before_rebuild()
    with library.connect() as db:
        db.executemany("UPDATE songs SET duplicate_preferred=0 WHERE id=?", [(member['id'],) for member in rows])
        db.executemany("UPDATE songs SET duplicate_of=?,duplicate_state='kept' WHERE id=?",
                       [(song_id, member['id']) for member in rows if member['id'] != song_id])
        db.execute("UPDATE songs SET duplicate_of=0,duplicate_state='',duplicate_preferred=1 WHERE id=?", (song_id,))
        # Moved/recycled records remain hidden but should reference the new keeper.
        db.execute("UPDATE songs SET duplicate_of=? WHERE duplicate_of=?", (song_id, old_id))


def prepare_action(library, song_id, protected=(), keeper_id=None):
    row = library.get(song_id)
    if not row or row['duplicate_state'] in ('moved','recycled','deleted','excluded','missing'):
        raise ValueError('รายการที่เลือกไม่ได้อยู่ในคลังที่ใช้งาน')
    if keeper_id is None:
        # Preserve the old API for legacy exact-duplicate actions.
        if not row['duplicate_of'] or row['duplicate_state'] not in ('kept','manual_hidden'):
            raise ValueError('ต้องเลือกชุดเพลงซ้ำที่ตรวจยืนยันแล้ว')
        keeper_id = row['duplicate_of']
    keeper_id = int(keeper_id)
    if keeper_id <= 0 or keeper_id == song_id:
        raise ValueError('ต้องเก็บชุดหลักที่เป็นคนละรายการ')
    if song_id in set(protected) or row['favorite'] or row['user_edited']:
        raise ValueError('รายการนี้มีคิว เพลงโปรด หรือข้อมูลที่แก้ไว้ ให้เก็บรายการนี้และจัดการชุดอื่นแทน')
    keeper = library.get(keeper_id)
    if not keeper or keeper['duplicate_state'] in ('deleted','moved','recycled','missing','excluded') or not keeper['playable']:
        raise ValueError('ไม่พบชุดหลักที่พร้อมเล่นและเก็บรักษาไว้')
    left, parts, hashes = fingerprint(row['path'])
    right, _, _ = fingerprint(keeper['path'])
    if left != right:
        raise ValueError('เนื้อหาไม่ตรงกับชุดหลักแล้ว ต้องตรวจเพลงซ้ำใหม่')
    # Sidecars, hardlinks and aliased paths referenced by another record are shared.
    sources = {canonical(path) for path in parts.values()}
    with library.connect() as db:
        others = db.execute("SELECT id,path FROM songs WHERE id<>? AND duplicate_state NOT IN ('moved','recycled','deleted')", (song_id,)).fetchall()
    for other in others:
        try:
            _, used = bundle(other['path'])
        except (OSError, ValueError):
            # Still protect known media and sidecars of incomplete NCN records.
            media = Path(other['path']); lyr, cur = Inspector().ncn_pair(media)
            used = {'media': media, 'lyr': lyr, 'cur': cur, 'lrc': media.with_suffix('.lrc'), 'snf': media.with_suffix('.snf')}
        for used_path in used.values():
            if canonical(used_path) in sources:
                raise ValueError('มีรายการอื่นใช้ไฟล์ชุดนี้ร่วมกัน จึงไม่ย้ายหรือลบ')
            if used_path.exists() and any(os.path.samefile(used_path, source) for source in parts.values()):
                raise ValueError('ไฟล์เชื่อมกับรายการอื่น จึงไม่ย้ายหรือลบ')
    return row, parts, hashes


def move_duplicate(library, song_id, destination, protected=()):
    """Disabled in v0.9.43; restore_move remains for old quarantine plans."""
    raise ValueError('v0.9.43 ยกเลิกโฟลเดอร์กักแยกเพลงซ้ำ ให้เลือกซ่อน/ถังรีไซเคิล/ลบถาวร')


def restore_move(library, manifest):
    manifest = Path(manifest).resolve()
    data = json.loads(manifest.read_text(encoding='utf-8'))
    if data.get('version') != 1 or data.get('state') not in ('planned','moving','moved') or data.get('library') != str(library.path.resolve()):
        raise ValueError('ไม่ใช่บันทึกย้ายของฐานข้อมูลนี้ หรือกู้คืนแล้ว')
    row = library.get(int(data['song_id']))
    if not row or row['duplicate_state'] not in ('kept','moved'):
        raise ValueError('สถานะรายการไม่ตรงกับบันทึก')
    files = data['files']
    if not files or not any(item['role']=='media' and canonical(Path(item['source']))==canonical(Path(row['path'])) for item in files):
        raise ValueError('ตำแหน่งต้นทางไม่ตรงกับรายการ')
    pending = []
    for item in files:
        if not Path(item['target']).resolve().is_relative_to(manifest.parent):
            raise ValueError('ไฟล์ย้ายอยู่นอกโฟลเดอร์บันทึก')
        source, target = Path(item['source']), Path(item['target'])
        if source.exists():
            if data['state'] == 'moved' or target.exists() or digest(source) != item['sha256']:
                raise ValueError('ต้นทางมีไฟล์อยู่แล้ว ไม่เขียนทับ: ' + item['source'])
            continue  # An interrupted job had not moved this component yet.
        if digest(target) != item['sha256']:
            raise ValueError('ไฟล์ที่ย้ายเปลี่ยนไปแล้ว')
        pending.append(item)
    restored = []
    try:
        for item in pending:
            Path(item['source']).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(item['target'], item['source']); restored.append(item)
        with library.connect() as db:
            db.execute("UPDATE songs SET duplicate_state='kept',playable=1 WHERE id=?", (row['id'],))
        data['state']='restored';write_json(manifest,data)
    except Exception:
        for item in reversed(restored):
            if Path(item['source']).exists() and not Path(item['target']).exists():
                shutil.move(item['source'],item['target'])
        raise
    return len(restored)


def recycle_files(paths):
    """IFileOperation with RECYCLEONDELETE; no permanent-delete fallback."""
    if os.name != 'nt':
        raise OSError('ถังรีไซเคิลรองรับเฉพาะ Windows 8 ขึ้นไป')
    from ctypes import wintypes
    class GUID(ctypes.Structure):
        _fields_ = [('bytes', ctypes.c_ubyte * 16)]
        def __init__(self, value):
            super().__init__()
            self.bytes[:] = uuid.UUID(value).bytes_le
    def check(result):
        if result < 0:
            raise OSError('Windows Recycle Bin ไม่สำเร็จ: 0x%08X' % (result & 0xffffffff))
    def call(obj, index, argtypes=(), *args):
        table = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        fn = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(table[index])
        return fn(obj, *args)
    ole = ctypes.OleDLL('ole32')
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole.CoInitializeEx.restype = ctypes.c_long
    initialized = ole.CoInitializeEx(None, 2)  # worker-owned STA
    check(initialized)
    operation = ctypes.c_void_p()
    items = []
    try:
        ole.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p, wintypes.DWORD,
                                        ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
        ole.CoCreateInstance.restype = ctypes.c_long
        check(ole.CoCreateInstance(ctypes.byref(GUID('3ad05575-8857-4850-9277-11b85bdb8e09')), None, 1,
              ctypes.byref(GUID('947aab5f-0a5c-4c13-b4d6-4bf7836fc9f8')), ctypes.byref(operation)))
        # RECYCLEONDELETE | ADDUNDORECORD | EARLYFAILURE | NOERRORUI |
        # SILENT | NOCONFIRMATION. Confirmation is owned by our review window.
        check(call(operation,5,(wintypes.DWORD,),0x80000|0x20000000|0x100000|0x400|0x4|0x10))
        shell = ctypes.WinDLL('shell32')
        create = shell.SHCreateItemFromParsingName
        create.argtypes = [wintypes.LPCWSTR,ctypes.c_void_p,ctypes.POINTER(GUID),ctypes.POINTER(ctypes.c_void_p)]
        create.restype = ctypes.c_long
        for path in paths:
            item = ctypes.c_void_p()
            check(create(str(Path(path).resolve()),None,ctypes.byref(GUID('43826d1e-e718-42ee-bc55-a1e261c37bfe')),ctypes.byref(item)))
            items.append(item)
            check(call(operation,18,(ctypes.c_void_p,ctypes.c_void_p),item,None))
        check(call(operation,21))
        aborted = wintypes.BOOL()
        check(call(operation,22,(ctypes.POINTER(wintypes.BOOL),),ctypes.byref(aborted)))
        if aborted.value:
            raise OSError('Windows ยกเลิกการส่งเข้าถังรีไซเคิล กรุณาตรวจรายงาน')
    finally:
        for item in items:
            call(item,2)
        if operation:
            call(operation,2)
        ole.CoUninitialize()


def recycle_duplicate(library, song_id, protected=()):
    row, parts, hashes = prepare_action(library,song_id,protected)
    library.backup_before_rebuild()
    report=library.path.parent / ('recycle-'+uuid.uuid4().hex+'.json')
    data=dict(song_id=song_id,keeper_id=row['duplicate_of'],state='requested',
              files=[dict(path=str(path),sha256=hashes[role]) for role,path in parts.items()])
    write_json(report,data)
    try:
        recycle_files(list(parts.values()))
    finally:
        remaining=[str(path) for path in parts.values() if path.exists()]
        data.update(state='recycled' if not remaining else 'incomplete',remaining=remaining)
        write_json(report,data)
        if not Path(row['path']).exists():
            with library.connect() as db:
                db.execute("UPDATE songs SET duplicate_state='recycled',playable=0 WHERE id=?",(song_id,))
    return report
