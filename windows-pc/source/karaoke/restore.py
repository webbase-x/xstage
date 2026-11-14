"""Validate and stage backups; apply only before the application opens its data."""
import json
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
    data=Path(data);pending=data/'restore-pending'
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
    temp=target.with_name(target.name+'.restore-tmp')
    shutil.copyfile(source,temp);temp.replace(target)


def rollback(data,safety,existed,replaced=FILES):
    for name in replaced:
        target=data/name
        if name.endswith('.sqlite3'):
            for suffix in ('-wal','-shm'):(data/(name+suffix)).unlink(missing_ok=True)
        if name in existed:replace_file(safety/name,target)
        else:target.unlink(missing_ok=True)


def apply_pending(data):
    data=Path(data);pending=data/'restore-pending'
    if not pending.exists():return None
    state=parse_json((pending/'state.json').read_text(encoding='utf-8'))
    if state['status']=='applying':
        safety=data/state['safety']
        if safety.parent!=data or not safety.name.startswith('restore-safety-'):raise ValueError('ข้อมูลกู้คืนค้างไม่ถูกต้อง')
        rollback(data,safety,state['existed'],state.get('replaced',FILES))
        pending.rename(data/('restore-interrupted-'+uuid.uuid4().hex))
        raise ValueError('กู้คืนครั้งก่อนถูกขัดจังหวะ คืนข้อมูลเดิมแล้ว กรุณาเลือกชุดสำรองใหม่')
    if state['status']=='complete':
        shutil.rmtree(pending);return None
    if state['status']!='prepared':raise ValueError('สถานะกู้คืนไม่ถูกต้อง')
    info=validate_backup(pending)
    safety=data/('restore-safety-'+uuid.uuid4().hex);safety.mkdir()
    existed=[]
    replaced=FILES+tuple(name for name in OPTIONAL_FILES if (pending/name).is_file())
    for name in replaced:
        source=data/name
        if source.exists():
            if name.endswith('.sqlite3'):copy_database(source,safety/name)
            else:shutil.copyfile(source,safety/name)
            existed.append(name)
    state=dict(status='applying',safety=safety.name,existed=existed,replaced=replaced)
    write_json(pending/'state.json',state)
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
