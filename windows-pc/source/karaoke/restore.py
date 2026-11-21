"""Validate and stage backups; apply only before the application opens its data."""
import json
import os
import tempfile
import shutil
import sqlite3
import uuid
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from .library import QueueItem, write_json, parse_json
from .settings_schema import validate_settings

FILES=('songs.sqlite3','settings.json','queue.json')
OPTIONAL_FILES=('history.json','play_stats.sqlite3')

def readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)


def validate_backup(folder):
    folder=Path(folder)
    if folder.is_symlink() or getattr(folder, 'is_junction', lambda: False)():
        raise ValueError('โฟลเดอร์ชุดสำรองเป็นลิงก์ที่ไม่ปลอดภัย')
    if not folder.is_dir():
        raise ValueError('ไม่พบโฟลเดอร์ชุดสำรอง')
    for name in FILES + OPTIONAL_FILES:
        source = folder/name
        # A backup must be self-contained. Do not follow symlinks/junctions
        # that could silently read or restore files outside the selected set.
        if source.is_symlink() or getattr(source, 'is_junction', lambda: False)():
            raise ValueError('ชุดสำรองมีไฟล์ลิงก์ที่ไม่ปลอดภัย: '+name)
    for name in FILES:
        if not (folder/name).is_file():raise ValueError('ชุดสำรองไม่ครบ: '+name)
    with closing(readonly(folder/FILES[0])) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('ฐานข้อมูลสำรองเสียหาย')
        columns={row[1] for row in db.execute('PRAGMA table_info(songs)')}
        if not {'id','path','code','title','artist','kind','search','favorite'}<=columns:
            raise ValueError('ไม่ใช่ฐานข้อมูลเพลง X-Stage')
        count=db.execute('SELECT COUNT(*) FROM songs').fetchone()[0]
        settings=validate_settings(parse_json((folder/FILES[1]).read_text(encoding='utf-8-sig')))
        raw=parse_json((folder/FILES[2]).read_text(encoding='utf-8-sig'))
        if isinstance(raw,dict):
            if raw.get('format') not in ('xstage.playlist','newKaraoke.playlist'):raise ValueError('รูปแบบคิวไม่ถูกต้อง')
            raw=raw.get('tracks')
        if not isinstance(raw,list):raise ValueError('ไฟล์คิวไม่ถูกต้อง')
        queue=[]
        for row in raw:
            if not isinstance(row,dict):raise ValueError('รายการคิวไม่ถูกต้อง')
            try:item=QueueItem.from_dict(row)
            except (KeyError,ValueError,TypeError,OverflowError) as error:raise ValueError('รายการคิวไม่ถูกต้อง') from error
            song=db.execute('SELECT path FROM songs WHERE id=?',(item.song_id,)).fetchone()
            if not song or ('path' in row and row['path']!=song[0]):raise ValueError('คิวไม่ตรงกับฐานข้อมูลสำรอง')
            # Restored requests are local queue items, not old mobile session identities.
            item.request_id='';queue.append(asdict(item))
    # Optional files keep legacy v0.9.37 backups valid. If present they must
    # be sound before anything is staged or applied.
    if (folder/'history.json').is_file():
        from .performance_features import read_history_snapshot
        read_history_snapshot(folder/'history.json')
    if (folder/'play_stats.sqlite3').is_file():
        from .play_stats import validate_stats
        validate_stats(folder/'play_stats.sqlite3')
    return dict(songs=count,queue=queue,settings=settings)


def copy_database(source,target):
    with closing(readonly(source)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)


def stage_restore(folder,data):
    info=validate_backup(folder)
    from .first_run import settings_for_restore
    info['settings']=settings_for_restore(folder,info['settings'])
    data=Path(data)
    if data.is_symlink() or getattr(data, 'is_junction', lambda: False)():
        raise ValueError('โฟลเดอร์ข้อมูลปลายทางเป็นลิงก์ที่ไม่ปลอดภัย')
    pending=data/'restore-pending'
    if pending.is_symlink() or getattr(pending,'is_junction',lambda:False)():
        raise ValueError('โฟลเดอร์กู้คืนค้างเป็นลิงก์ที่ไม่ปลอดภัย')
    if pending.exists():raise ValueError('มีงานกู้คืนรอเปิดโปรแกรมอยู่แล้ว')
    temp=data/('restore-stage-'+uuid.uuid4().hex);temp.mkdir(parents=True)
    try:
        copy_database(Path(folder)/FILES[0],temp/FILES[0])
        write_json(temp/FILES[1],info['settings']);write_json(temp/FILES[2],info['queue'])
        for name in OPTIONAL_FILES:
            source = Path(folder)/name
            if source.is_file():
                if name.endswith('.sqlite3'):
                    copy_database(source,temp/name)
                else:
                    shutil.copy2(source,temp/name)
        validate_backup(temp)
        write_json(temp/'state.json',dict(status='prepared'))
        temp.rename(pending)
    except Exception:
        shutil.rmtree(temp,ignore_errors=True);raise
    return info


def replace_file(source,target):
    """Atomically replace a regular file without following stale temp links."""
    source, target = Path(source), Path(target)
    if (source.is_symlink() or getattr(source, 'is_junction', lambda: False)()
            or not source.is_file()):
        raise ValueError('ไฟล์ต้นทางกู้คืนไม่ปลอดภัย: ' + source.name)
    if (target.is_symlink() or getattr(target, 'is_junction', lambda: False)()
            or (target.exists() and not target.is_file())):
        raise ValueError('ไฟล์ปลายทางกู้คืนไม่ปลอดภัย: ' + target.name)
    temp = None
    try:
        # Exclusive random creation avoids a predictable .restore-tmp symlink
        # redirecting the copy outside the application's data directory.
        with tempfile.NamedTemporaryFile(
                dir=target.parent, prefix=target.name + '.restore-',
                suffix='.tmp', delete=False) as output:
            temp = Path(output.name)
            with source.open('rb') as input_file:
                shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
        if (target.is_symlink() or getattr(target, 'is_junction', lambda: False)()
                or (target.exists() and not target.is_file())):
            raise ValueError('ไฟล์ปลายทางกู้คืนเปลี่ยนเป็นลิงก์หรือโฟลเดอร์')
        temp.replace(target)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def rollback(data,safety,existed,replaced=FILES):
    for name in replaced:
        target=data/name
        if name.endswith('.sqlite3'):
            for suffix in ('-wal','-shm'):(data/(name+suffix)).unlink(missing_ok=True)
        if name in existed:replace_file(safety/name,target)
        else:target.unlink(missing_ok=True)


def apply_pending(data):
    data=Path(data);pending=data/'restore-pending'
    if data.is_symlink() or getattr(data,'is_junction',lambda:False)():
        raise ValueError('โฟลเดอร์ข้อมูลปลายทางเป็นลิงก์ที่ไม่ปลอดภัย')
    if pending.is_symlink() or getattr(pending,'is_junction',lambda:False)():
        raise ValueError('โฟลเดอร์กู้คืนค้างเป็นลิงก์ที่ไม่ปลอดภัย')
    if not pending.exists():return None
    if not pending.is_dir():raise ValueError('โฟลเดอร์กู้คืนค้างไม่ถูกต้อง')
    state_file=pending/'state.json'
    if (state_file.is_symlink() or getattr(state_file,'is_junction',lambda:False)()
            or not state_file.is_file()):
        raise ValueError('ไฟล์สถานะกู้คืนไม่ปลอดภัยหรือไม่ครบ')
    state=parse_json(state_file.read_text(encoding='utf-8'))
    if not isinstance(state,dict) or state.get('status') not in ('prepared','applying','complete'):
        raise ValueError('สถานะกู้คืนไม่ถูกต้อง')
    if state['status']=='applying':
        safety_name=state.get('safety')
        if (not isinstance(safety_name,str) or not safety_name.startswith('restore-safety-')
                or Path(safety_name).name!=safety_name):
            raise ValueError('ข้อมูลกู้คืนค้างไม่ถูกต้อง')
        safety=data/safety_name
        if safety.is_symlink() or getattr(safety,'is_junction',lambda:False)() or not safety.is_dir():
            raise ValueError('โฟลเดอร์สำรองเพื่อย้อนคืนไม่ปลอดภัย')
        existed=state.get('existed')
        replaced=state.get('replaced',FILES)
        allowed=set(FILES+OPTIONAL_FILES)
        if (not isinstance(existed,list) or not isinstance(replaced,(list,tuple))
                or any(not isinstance(name,str) for name in replaced)
                or any(not isinstance(name,str) for name in existed)
                or len(set(replaced))!=len(replaced) or len(set(existed))!=len(existed)
                or any(name not in allowed for name in replaced)
                or any(name not in replaced for name in existed)):
            raise ValueError('รายการไฟล์กู้คืนค้างไม่ถูกต้อง')
        for name in existed:
            source=safety/name
            if not source.is_file() or source.is_symlink() or getattr(source,'is_junction',lambda:False)():
                raise ValueError('ไฟล์สำรองเพื่อย้อนคืนไม่ปลอดภัย: '+name)
        # A crash can leave the live target replaced by a link before restart.
        # Never follow it while rolling back; require operator intervention.
        for name in replaced:
            target=data/name
            if (target.is_symlink() or getattr(target,'is_junction',lambda:False)()
                    or (target.exists() and not target.is_file())):
                raise ValueError('ไฟล์ปลายทางย้อนคืนไม่ปลอดภัย: '+name)
        rollback(data,safety,existed,replaced)
        pending.rename(data/('restore-interrupted-'+uuid.uuid4().hex))
        raise ValueError('กู้คืนครั้งก่อนถูกขัดจังหวะ คืนข้อมูลเดิมแล้ว กรุณาเลือกชุดสำรองใหม่')
    if state['status']=='complete':
        shutil.rmtree(pending);return None
    if state['status']!='prepared':raise ValueError('สถานะกู้คืนไม่ถูกต้อง')
    info=validate_backup(pending)
    replaced=FILES+tuple(name for name in OPTIONAL_FILES if (pending/name).is_file())
    # Validate all live inputs before allocating a safety directory. A failed
    # snapshot must not leave an orphan directory or a half-written journal.
    for name in replaced:
        source=data/name
        if source.is_symlink() or getattr(source,'is_junction',lambda:False)():
            raise ValueError('ไฟล์ข้อมูลปัจจุบันเป็นลิงก์ที่ไม่ปลอดภัย: '+name)
        if source.exists() and not source.is_file():
            raise ValueError('ไฟล์ข้อมูลปัจจุบันไม่ถูกต้อง: '+name)
    safety=data/('restore-safety-'+uuid.uuid4().hex);safety.mkdir()
    existed=[]
    try:
        for name in replaced:
            source=data/name
            if source.exists():
                if name.endswith('.sqlite3'):copy_database(source,safety/name)
                else:shutil.copyfile(source,safety/name)
                existed.append(name)
    except BaseException:
        shutil.rmtree(safety,ignore_errors=True)
        raise
    state=dict(status='applying',safety=safety.name,existed=existed,replaced=replaced)
    try:
        write_json(pending/'state.json',state)
    except BaseException:
        # The live files have not been touched yet. Keep the original
        # prepared journal and remove the unused safety snapshot.
        shutil.rmtree(safety,ignore_errors=True)
        raise
    try:
        for name in replaced:
            if name.endswith('.sqlite3'):
                for suffix in ('-wal','-shm'):(data/(name+suffix)).unlink(missing_ok=True)
            replace_file(pending/name,data/name)
        validate_backup(data)
        write_json(pending/'state.json',{**state,'status':'complete'})
    except Exception:
        rollback(data,safety,existed,replaced)
        write_json(pending/'state.json',dict(status='prepared'))
        raise
    shutil.rmtree(pending)
    return dict(songs=info['songs'],queue=len(info['queue']),safety=str(safety))
