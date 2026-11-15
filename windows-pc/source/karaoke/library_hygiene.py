"""Immutable review plans; selected permanent deletion only after token confirmation.
All file operations have verified backups and a durable per-item execution journal.
"""
import csv
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import uuid
from contextlib import closing
from .library import canonical,write_json,SearchCancelled
from .song_policy import assess,available_parts,check_cancel,REVISION
from .name_duplicates import identity
from .ingest import Inspector
from .duplicates import digest
from .verified_delete import delete_verified

INACTIVE=('moved','recycled','deleted')
STATUS_LABELS={'valid':'สมบูรณ์','duplicate':'ซ้ำชื่อ/นักร้อง/คีย์','invalid':'ไม่สมบูรณ์','review':'ต้องตรวจเพิ่ม','blocked':'ป้องกันไว้'}
def os_error_detail(error):
    """Stable operator-facing OS detail for cleanup/recovery logs."""
    parts=[type(error).__name__,str(error)]
    for name in ('errno','winerror','filename','filename2'):
        value=getattr(error,name,None)
        if value is not None:parts.append(f'{name}={value}')
    return ' | '.join(parts)


def pending_cleanup_plans(report_root):
    """Single source of truth for interrupted cleanup journal detection."""
    from .pending_cleanup import find_pending
    return find_pending(report_root)

def encode(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))

def readonly(path):return sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=10)

def file_state(path,cancelled=None):
    path=Path(path)
    if path.is_symlink() or any(p.is_symlink() or getattr(p,'is_junction',lambda:False)() for p in path.parents):raise ValueError('ไฟล์/โฟลเดอร์ลิงก์ ไม่อนุญาตลบ')
    before=path.stat();key=digest(path,cancelled);after=path.stat()
    stamp=lambda s:(s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_dev,s.st_ino)
    if stamp(before)!=stamp(after):raise ValueError('ไฟล์เปลี่ยนระหว่างตรวจ')
    return dict(path=canonical(path),sha256=key,size=after.st_size,mtime=after.st_mtime_ns,device=after.st_dev,inode=after.st_ino)

def verify_file(item):
    actual=file_state(item['path'])
    if any(actual[k]!=item[k] for k in ('sha256','size','mtime','device','inode')):raise ValueError('ไฟล์เปลี่ยนหลังตรวจรายงาน: '+item['path'])

def snapshot_files(path,cancelled=None,inspector=None):
    return [dict(role=role,**file_state(file,cancelled)) for role,file in available_parts(path,inspector).items() if file.is_file()]

def csv_safe(value):
    value=str(value)
    return "'"+value if value.lstrip().startswith(('=','+','-','@')) else value


_WORKER_INSPECTOR=None

def assess_worker(row):
    global _WORKER_INSPECTOR
    if _WORKER_INSPECTOR is None:
        _WORKER_INSPECTOR=Inspector()
        if os.name=='nt':
            import ctypes
            try:
                kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.GetCurrentProcess.restype=ctypes.c_void_p;kernel.SetPriorityClass.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
                kernel.SetPriorityClass(kernel.GetCurrentProcess(),0x4000)
            except Exception:pass
    result=assess(row['path'],row,inspector=_WORKER_INSPECTOR,crosscheck_metadata=True)
    try:parts=[canonical(file) for file in available_parts(row['path'],_WORKER_INSPECTOR).values()];error=None
    except (OSError,ValueError) as exc:parts=[];error=str(exc)
    return row,result,parts,error


def assessed_rows(cursor,cancelled,inspector,probe,workers):
    if workers<=1 or probe is not None:
        for item in cursor:
            check_cancel(cancelled);row=dict(item);quality=assess(row['path'],row,cancelled,inspector,probe,crosscheck_metadata=True)
            try:parts=[canonical(file) for file in available_parts(row['path'],inspector).values()];error=None
            except (OSError,ValueError) as exc:parts=[];error=str(exc)
            yield row,quality,parts,error
        return
    import multiprocessing
    from collections import deque
    from concurrent.futures import ProcessPoolExecutor
    pool=ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn'));pending=deque()
    iterator=iter(cursor)
    def fill():
        while len(pending)<workers*2:
            try:row=dict(next(iterator))
            except StopIteration:break
            pending.append(pool.submit(assess_worker,row))
    try:
        fill()
        while pending:
            check_cancel(cancelled);future=pending.popleft()
            while not future.done():
                check_cancel(cancelled)
                import time;time.sleep(.05)
            yield future.result();fill()
    finally:pool.shutdown(wait=True,cancel_futures=True)


def scan(library_path,report_root,cancelled=None,events=None,protected=(),probe=None,workers=1):
    """Read-only library snapshot; only complete plans can ever be applied."""
    report_root=Path(report_root);report_root.mkdir(parents=True,exist_ok=True)
    folder=report_root/('Cleanup-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]);folder.mkdir()
    db=sqlite3.connect(folder/'plan.sqlite3');db.row_factory=sqlite3.Row
    db.executescript('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE rows(id INTEGER PRIMARY KEY,status TEXT,keeper INTEGER,reason TEXT,old TEXT,quality TEXT,files TEXT);CREATE TABLE owners(path TEXT,id INTEGER,PRIMARY KEY(path,id));CREATE INDEX owner_lookup ON owners(path);CREATE TABLE keepers(k TEXT PRIMARY KEY,id INTEGER);CREATE TABLE witnesses(id INTEGER PRIMARY KEY,old TEXT,files TEXT);')
    db.execute('INSERT INTO meta VALUES (?,?)',('library',canonical(Path(library_path))));db.execute('INSERT INTO meta VALUES (?,?)',('policy',REVISION));db.execute('INSERT INTO meta VALUES (?,?)',('complete','false'));db.commit()
    inspector=Inspector();protected=set(protected);counts=dict(valid=0,duplicate=0,invalid=0,review=0,blocked=0);complete=False
    try:
        with closing(readonly(library_path)) as source:
            source.row_factory=sqlite3.Row;source.execute('BEGIN')
            total=source.execute("SELECT count(*) FROM songs WHERE duplicate_state NOT IN ('moved','recycled','deleted')").fetchone()[0]
            if events:events(dict(type='phase',phase='ตรวจคุณภาพและซ้ำชื่อ นักร้อง คีย์ — ยังไม่ลบไฟล์',total=total,target=total))
            # Prefer the first visible complete ID; existing hidden aliases never replace a visible keeper.
            cursor=source.execute("SELECT * FROM songs WHERE duplicate_state NOT IN ('moved','recycled','deleted') ORDER BY CASE WHEN duplicate_of=0 THEN 0 ELSE 1 END,id")
            for done,(row,quality,parts,owner_error) in enumerate(assessed_rows(cursor,cancelled,inspector,probe,workers),1):
                check_cancel(cancelled)
                status=quality['status'];keeper=None;reason='; '.join(quality['reasons'])
                for file in parts:db.execute('INSERT OR IGNORE INTO owners VALUES (?,?)',(file,row['id']))
                if owner_error:status='review';reason='ตรวจผู้ใช้ไฟล์ร่วมไม่ได้: '+owner_error
                if status=='valid':
                    k=quality.get('identity')
                    first=db.execute('SELECT id FROM keepers WHERE k=?',(k,)).fetchone()
                    if first:
                        keeper=first[0];status='duplicate';reason='ชื่อเพลง นักร้อง และคีย์ตรงกัน; เก็บ #'+str(keeper)
                    else:db.execute('INSERT INTO keepers VALUES (?,?)',(k,row['id']))
                if status in ('duplicate','invalid') and (row['id'] in protected or row.get('favorite') or row.get('user_edited')):
                    reason+=' • ป้องกันคิว/เพลงที่เล่น/เพลงโปรด/ข้อมูลแก้เอง';status='blocked'
                db.execute('INSERT INTO rows VALUES (?,?,?,?,?,?,?)',(row['id'],status,keeper,reason,encode(row),encode(quality),'[]'))
                counts[status]+=1
                if events:
                    events(dict(type='item',ok=status=='valid',path=row['path'],title=row['title'],artist=row['artist'],result=status,note=reason))
                    events(dict(type='progress',done=done,total=total))
                if done%500==0:db.commit()
            cursor.close()
            db.commit()
            candidates=db.execute("SELECT * FROM rows WHERE status IN ('duplicate','invalid') ORDER BY id").fetchall()
            if events:events(dict(type='phase',phase='เก็บ SHA256 รายการที่จะเสนอให้ลบและชุดหลัก',total=len(candidates)))
            for done,item in enumerate(candidates,1):
                check_cancel(cancelled);row=json.loads(item['old'])
                try:
                    files=snapshot_files(row['path'],cancelled,inspector)
                    for file in files:
                        shared=db.execute('SELECT count(*) FROM owners WHERE path=? AND id<>?',(file['path'],row['id'])).fetchone()[0]
                        file['shared']=bool(shared)
                    db.execute('UPDATE rows SET files=? WHERE id=?',(encode(files),row['id']))
                    if item['keeper']:
                        witness=db.execute('SELECT * FROM rows WHERE id=?',(item['keeper'],)).fetchone()
                        kept=json.loads(witness['old'])
                        if not db.execute('SELECT 1 FROM witnesses WHERE id=?',(item['keeper'],)).fetchone():
                            db.execute('INSERT INTO witnesses VALUES (?,?,?)',(item['keeper'],witness['old'],encode(snapshot_files(kept['path'],cancelled,inspector))))
                except (OSError,ValueError) as error:
                    counts[item['status']]-=1;counts['review']+=1
                    db.execute("UPDATE rows SET status='review',reason=? WHERE id=?",('ไฟล์เปลี่ยน/ตรวจ SHA256 ไม่สำเร็จ: '+str(error),row['id']))
                if events:events(dict(type='progress',done=done,total=len(candidates)))
                if done%100==0:db.commit()
        db.execute("UPDATE meta SET value='true' WHERE key='complete'");db.commit();complete=True
    except SearchCancelled:
        db.commit()
    finally:
        # Always leave a readable partial report; it cannot authorize deletion.
        with (folder/'report.csv').open('w',newline='',encoding='utf-8-sig') as stream:
            writer=csv.writer(stream);writer.writerow(['ID','สถานะ','เก็บ ID','ชื่อเพลง','นักร้อง','คีย์','เหตุผล','ไฟล์'])
            for item in db.execute('SELECT * FROM rows ORDER BY id'):
                row=json.loads(item['old']);measured=json.loads(item['quality']).get('metadata',{});row={**row,**{k:v for k,v in measured.items() if not row.get(k)}};writer.writerow([row['id'],STATUS_LABELS[item['status']],item['keeper'] or '',*[csv_safe(row.get(k,'')) for k in ('title','artist','key_signature')],csv_safe(item['reason']),csv_safe(row['path'])])
        db.close()
    token=digest(folder/'plan.sqlite3')
    summary=dict(version=1,policy=REVISION,library=canonical(Path(library_path)),complete=complete,counts=counts,plan_sha256=token,report=str(folder/'report.csv'))
    write_json(folder/'summary.json',summary)
    return folder


def validate_plan(folder,token):
    folder=Path(folder).resolve();summary=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
    if not summary.get('complete') or summary.get('policy')!=REVISION or summary.get('plan_sha256')!=token or digest(folder/'plan.sqlite3')!=token:raise ValueError('แผนไม่ครบ/เปลี่ยนหลังรายงาน ต้องตรวจใหม่และยืนยันใหม่')
    return folder,summary


def apply(library,folder,selected_ids,token,protected=(),cancelled=None,events=None,data_lock=None):
    from .instance_lock import DataDirectoryLock
    owned=data_lock is None
    lock=DataDirectoryLock(library.path.parent).acquire() if owned else data_lock
    try:
        if canonical(lock.path.parent)!=canonical(library.path.parent) or lock.file is None or lock.file.closed:raise ValueError('ไม่มี Data lock ที่ถูกต้องสำหรับงานลบ')
        return _apply_locked(library,folder,selected_ids,token,protected,cancelled,events)
    finally:
        if owned:lock.close()


def _apply_locked(library,folder,selected_ids,token,protected=(),cancelled=None,events=None):
    """Explicit selected deletion. A single write lease keeps ownership stable."""
    folder,summary=validate_plan(folder,token)
    if canonical(library.path)!=summary['library']:raise ValueError('แผนเป็นของฐานข้อมูลอื่น')
    ids=sorted(set(selected_ids))
    if not ids:raise ValueError('ยังไม่ได้เลือกรายการที่ตรวจรายงานแล้ว')
    with closing(readonly(folder/'plan.sqlite3')) as check:
        for sid in ids:
            if not check.execute("SELECT 1 FROM rows WHERE id=? AND status IN ('duplicate','invalid')",(sid,)).fetchone():raise ValueError('การเลือกมี ID ที่ไม่ได้เสนอให้ลบ: '+str(sid))
    from .library import parse_json,validate_queue
    queue_path=library.path.parent/'queue.json'
    persistent_queue={item.song_id for item in validate_queue(parse_json(queue_path.read_text(encoding='utf-8-sig')))} if queue_path.is_file() else set()
    if events:events(dict(type='phase',phase='สำรองฐานข้อมูลก่อนลบตามรายงาน',total=None))
    snapshot=folder/'database-before-delete.sqlite3'
    snapshot_info=folder/'database-backup.json'
    if snapshot.is_symlink():raise ValueError('ตำแหน่งสำรองฐานข้อมูลเป็นลิงก์')
    if snapshot_info.is_symlink():raise ValueError('ข้อมูลสำรองเป็นลิงก์')
    if not snapshot.exists():
        # Exclusive reservation; never replace a pre-existing backup.
        with snapshot.open('xb'):pass
        try:
            with closing(readonly(library.path)) as original,closing(sqlite3.connect(snapshot)) as saved:
                def progress(*_):check_cancel(cancelled)
                original.backup(saved,pages=256,progress=progress)
                if saved.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('ตรวจสำรองฐานข้อมูลไม่ผ่าน')
        except BaseException:
            snapshot.unlink(missing_ok=True);raise
        write_json(snapshot_info,dict(library=summary['library'],plan=token,sha256=digest(snapshot)))
    else:
        if not snapshot_info.is_file():raise ValueError('พบสำรองที่ยังไม่ได้ยืนยัน ต้องตรวจงานค้างก่อน')
        info=json.loads(snapshot_info.read_text(encoding='utf-8'))
        if info.get('library')!=summary['library'] or info.get('plan')!=token or info.get('sha256')!=digest(snapshot):raise ValueError('สำรองฐานข้อมูลเปลี่ยนไป จึงไม่ลบ')
    backup=folder/'deletion-backup'
    if backup.is_symlink() or getattr(backup,'is_junction',lambda:False)():raise ValueError('โฟลเดอร์สำรองเป็นลิงก์')
    backup.mkdir(exist_ok=True)
    if (folder/'execution.sqlite3').is_symlink():raise ValueError('บันทึกงานเป็นลิงก์')
    journal=sqlite3.connect(folder/'execution.sqlite3');journal.row_factory=sqlite3.Row
    journal.execute('PRAGMA synchronous=FULL');journal.execute('CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY,state TEXT,data TEXT,error TEXT)');journal.commit()
    done_ids=[];blocked=0;promoted={}
    def protected_now():return set(protected() if callable(protected) else protected)|persistent_queue
    def unchanged(actual,expected,sid):
        return actual==expected or sid in promoted and expected==promoted[sid]['original'] and actual==promoted[sid]['updated']
    try:
        with closing(readonly(folder/'plan.sqlite3')) as plan,library.connect() as source:
            plan.row_factory=sqlite3.Row;source.execute('BEGIN IMMEDIATE')
            owned={};inspector=Inspector()
            for row in source.execute("SELECT id,path FROM songs WHERE duplicate_state NOT IN ('moved','recycled','deleted')"):
                check_cancel(cancelled)
                for role,file in available_parts(row['path'],inspector).items():owned.setdefault(canonical(file),set()).add(row['id'])
            for sid in ids:
                if cancelled and cancelled.is_set():break
                item=plan.execute("SELECT * FROM rows WHERE id=? AND status IN ('duplicate','invalid')",(sid,)).fetchone()
                if item is None:raise ValueError('ID ไม่ใช่รายการที่เสนอให้ลบ: '+str(sid))
                previous=journal.execute('SELECT * FROM actions WHERE id=?',(sid,)).fetchone()
                if previous and previous['state']=='applied':continue
                if previous and previous['state']!='restored':raise ValueError('พบงานค้าง ID '+str(sid)+' ต้องกู้คืนสำรองก่อนทำใหม่')
                old=json.loads(item['old']);files=json.loads(item['files']);keeper=item['keeper']
                action=dict(old=old,keeper=keeper,files=files,backups=[],deleted=[],retained=[])
                new_promotions={}
                source.execute('SAVEPOINT cleanup_item')
                try:
                    if sid in protected_now() or old.get('favorite') or old.get('user_edited'):raise ValueError('ป้องกันคิว/เพลงโปรด/ข้อมูลแก้เอง')
                    current=source.execute('SELECT * FROM songs WHERE id=?',(sid,)).fetchone()
                    if current is None or not unchanged(dict(current),old,sid):raise ValueError('ข้อมูลรายการเปลี่ยนหลังตรวจ ต้องตรวจใหม่')
                    action['entry_row']=dict(current)
                    actual_parts={(role,canonical(file)) for role,file in available_parts(old['path'],Inspector()).items() if file.is_file()}
                    if actual_parts!={(f['role'],f['path']) for f in files}:raise ValueError('ชุดไฟล์ประกอบเปลี่ยนหลังตรวจ ต้องตรวจใหม่')
                    if keeper:
                        witness=plan.execute('SELECT * FROM witnesses WHERE id=?',(keeper,)).fetchone()
                        if witness is None:raise ValueError('ไม่มีหลักฐานชุดหลัก')
                        kept=json.loads(witness['old']);present=source.execute('SELECT * FROM songs WHERE id=?',(keeper,)).fetchone()
                        if present is None or not unchanged(dict(present),kept,keeper):raise ValueError('รายการหลักเปลี่ยนหลังตรวจ')
                        kept_files=json.loads(witness['files'])
                        present_parts={(role,canonical(file)) for role,file in available_parts(kept['path'],Inspector()).items() if file.is_file()}
                        if present_parts!={(f['role'],f['path']) for f in kept_files}:raise ValueError('ชุดหลักมีส่วนประกอบเปลี่ยนหลังตรวจ')
                        for part in kept_files:verify_file(part)
                        kept_quality=assess(kept['path'],kept,inspector=inspector,crosscheck_metadata=True)
                        candidate_quality=assess(old['path'],old,inspector=inspector,crosscheck_metadata=True)
                        if kept_quality['status']!='valid' or candidate_quality['status']!='valid' or kept_quality.get('identity')!=candidate_quality.get('identity'):raise ValueError('ชุดหลัก/ชุดซ้ำไม่สมบูรณ์หรือชื่อ นักร้อง คีย์ไม่ตรงแล้ว จึงไม่ลบ')
                    elif assess(old['path'],old,inspector=inspector,crosscheck_metadata=True)['status']!='invalid':raise ValueError('ยังยืนยันว่าไม่สมบูรณ์ไม่ได้ ต้องตรวจใหม่')
                    for part in files:
                        verify_file(part)
                        if owned.get(part['path'],set())-{sid}:
                            action['retained'].append(part['path']);continue
                        target=backup/str(sid)/(part['role']+'-'+Path(part['path']).name)
                        if target.is_symlink() or any(parent.is_symlink() or getattr(parent,'is_junction',lambda:False)() for parent in target.parents):raise ValueError('ตำแหน่งสำรองเป็นลิงก์')
                        target.parent.mkdir(parents=True,exist_ok=True)
                        if target.exists():
                            if digest(target)!=part['sha256']:raise ValueError('สำรองชื่อชนและเนื้อหาต่างกัน')
                        else:
                            made=None
                            try:
                                with target.open('xb') as output:
                                    made=target.stat()
                                    with Path(part['path']).open('rb') as incoming:shutil.copyfileobj(incoming,output,1024*1024)
                                    output.flush();os.fsync(output.fileno())
                            except BaseException:
                                if made is not None and target.exists() and target.stat().st_ino==made.st_ino:target.unlink()
                                raise
                        if digest(target)!=part['sha256']:raise ValueError('ตรวจสำรองไม่ผ่าน จึงไม่ลบต้นฉบับ')
                        action['backups'].append(dict(source=part['path'],backup=str(target),sha256=part['sha256']))
                    journal.execute('INSERT OR REPLACE INTO actions VALUES (?,?,?,?)',(sid,'backed_up',encode(action),''));journal.commit()
                    for part in files:
                        if part['path'] in action['retained']:continue
                        check_cancel(cancelled)
                        if sid in protected_now():raise ValueError('รายการถูกใช้ในคิวระหว่างงาน จึงหยุดลบ')
                        verify_file(part)
                        delete_verified(part);action['deleted'].append(part['path'])
                        journal.execute('UPDATE actions SET data=? WHERE id=?',(encode(action),sid));journal.commit()
                    # Never leave a surviving alias pointing to a removed row.
                    children=source.execute("SELECT * FROM songs WHERE duplicate_of=? AND duplicate_state='kept'",(sid,)).fetchall()
                    for child in children:
                        original=dict(child);updated=dict(original,duplicate_of=0,duplicate_state='')
                        new_promotions.setdefault(child['id'],promoted.get(child['id']));promoted[child['id']]=dict(original=original,updated=updated)
                        source.execute("UPDATE songs SET duplicate_of=0,duplicate_state='' WHERE id=?",(child['id'],))
                    action['promoted_alias_ids']=[child['id'] for child in children]
                    if keeper:
                        entry=dict(source.execute('SELECT * FROM songs WHERE id=?',(keeper,)).fetchone())
                        updated=dict(entry,duplicate_of=0,duplicate_state='',playable=1)
                        if updated!=entry:
                            new_promotions.setdefault(keeper,promoted.get(keeper))
                            origin=promoted[keeper]['original'] if keeper in promoted else entry
                            promoted[keeper]=dict(original=origin,updated=updated)
                            source.execute("UPDATE songs SET duplicate_of=0,duplicate_state='',playable=1 WHERE id=?",(keeper,))
                    source.execute("UPDATE songs SET duplicate_of=?,duplicate_state='deleted',playable=0 WHERE id=?",(keeper or 0,sid))
                    for part in files:owned.get(part['path'],set()).discard(sid)
                    journal.execute("UPDATE actions SET state='files_deleted',data=? WHERE id=?",(encode(action),sid));journal.commit();source.execute('RELEASE cleanup_item');done_ids.append(sid)
                except (OSError,ValueError,sqlite3.Error,SearchCancelled) as error:
                    source.execute('ROLLBACK TO cleanup_item');source.execute('RELEASE cleanup_item')
                    for child_id,prior in new_promotions.items():
                        if prior is None:promoted.pop(child_id,None)
                        else:promoted[child_id]=prior
                    journal.execute('INSERT OR REPLACE INTO actions VALUES (?,?,?,?)',(sid,'blocked' if not action['deleted'] else 'partial',encode(action),os_error_detail(error)));journal.commit();blocked+=1
                    if events:events(dict(type='notice',ok=False,path=old['path'],title=old['title'],note=os_error_detail(error)))
                    if isinstance(error,SearchCancelled):break
                if events:events(dict(type='progress',done=len(done_ids)+blocked,total=len(ids)))
        # Only a committed database can be marked fully applied in the independent journal.
        journal.executemany("UPDATE actions SET state='applied' WHERE id=?",[(sid,) for sid in done_ids]);journal.commit()
    finally:journal.close()
    return dict(applied=len(done_ids),blocked=blocked,journal=str(folder/'execution.sqlite3'),backup=str(backup))


def restore_action(library,folder,song_id,data_lock=None):
    from .instance_lock import DataDirectoryLock
    owned=data_lock is None
    lock=DataDirectoryLock(library.path.parent).acquire() if owned else data_lock
    try:
        if canonical(lock.path.parent)!=canonical(library.path.parent) or lock.file is None or lock.file.closed:raise ValueError('ไม่มี Data lock ที่ถูกต้องสำหรับกู้คืน')
        return _restore_locked(library,folder,song_id)
    finally:
        if owned:lock.close()


def _restore_locked(library,folder,song_id):
    """Explicit recovery; restore only absent paths from this plan's verified backups."""
    folder=Path(folder).resolve();summary=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
    validate_plan(folder,summary['plan_sha256'])
    if canonical(library.path)!=summary['library']:raise ValueError('ฐานข้อมูลไม่ตรงแผน')
    if (folder/'execution.sqlite3').is_symlink() or not (folder/'execution.sqlite3').is_file():raise ValueError('ไม่มีบันทึกงานลบปกติให้กู้คืน')
    with closing(sqlite3.connect(folder/'execution.sqlite3')) as journal:
        row=journal.execute('SELECT state,data FROM actions WHERE id=?',(song_id,)).fetchone()
        if not row or row[0]=='restored':raise ValueError('ไม่มีรายการลบที่กู้คืนได้')
        action=json.loads(row[1]);old=action['old']
        entry=action.get('entry_row',old)
        if entry not in (old,dict(old,duplicate_of=0,duplicate_state='')):raise ValueError('สถานะก่อนลบใน journal ไม่ตรงแผน')
        with closing(readonly(folder/'plan.sqlite3')) as plan:
            item=plan.execute('SELECT old,files,keeper FROM rows WHERE id=?',(song_id,)).fetchone()
        if not item or old!=json.loads(item[0]) or action['keeper']!=item[2]:raise ValueError('journal ไม่ตรงแผนที่ยืนยัน')
        approved={f['path']:f['sha256'] for f in json.loads(item[1])}
        for item in action['backups']:
            if approved.get(item['source'])!=item['sha256']:raise ValueError('ตำแหน่งกู้คืนไม่ตรงแผน')
        for item in action['backups']:
            target=Path(item['backup']).resolve()
            if not target.is_relative_to(folder/'deletion-backup') or digest(target)!=item['sha256']:raise ValueError('สำรองอยู่นอกแผนหรือ hash ไม่ตรง')
            source=Path(item['source'])
            if any(parent.is_symlink() or getattr(parent,'is_junction',lambda:False)() for parent in source.parents):raise ValueError('เส้นทางกู้คืนเปลี่ยนเป็นลิงก์ ไม่เขียนผ่าน')
            if source.exists() and digest(source)!=item['sha256']:raise ValueError('ต้นทางมีไฟล์อื่นอยู่แล้ว ไม่เขียนทับ')
        with library.connect() as db:
            db.execute('BEGIN IMMEDIATE');current=db.execute('SELECT * FROM songs WHERE id=?',(song_id,)).fetchone()
            allowed=dict(old,duplicate_state='deleted',duplicate_of=action['keeper'] or 0,playable=0)
            if current is None or dict(current) not in (entry,allowed):raise ValueError('รายการต้นทางเปลี่ยน ไม่กู้คืนทับ')
            # Keep every file checked until all row validation has passed.
            for item in action['backups']:
                source=Path(item['source'])
                if source.exists():continue
                source.parent.mkdir(parents=True,exist_ok=True)
                with Path(item['backup']).open('rb') as incoming,source.open('xb') as output:shutil.copyfileobj(incoming,output,1024*1024)
                if digest(source)!=item['sha256']:raise ValueError('ตรวจไฟล์กู้คืนไม่ผ่าน')
            db.execute('UPDATE songs SET '+','.join(k+'=?' for k in entry if k!='id')+' WHERE id=?',[entry[k] for k in entry if k!='id']+[song_id])
        journal.execute("UPDATE actions SET state='restored' WHERE id=?",(song_id,));journal.commit()
    return True
