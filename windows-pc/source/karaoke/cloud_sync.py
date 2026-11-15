"""Local-first Google Drive Desktop sync package using the existing .py schema.

The application never opens SQLite from Drive. It creates a complete per-user
snapshot in a Drive-synced folder and restores it through the existing recovery
pipeline.
"""
import hashlib, json, os, re, shutil, sqlite3, uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from .library import write_json
from .first_run import write_transfer_metadata
from .restore import validate_backup, stage_restore

def find_drive_root():
    home = Path(os.environ.get('USERPROFILE') or Path.home())
    for candidate in (home/'Google Drive'/'My Drive',home/'Google Drive',home/'My Drive',home/'GoogleDrive',Path('G:/My Drive'),Path('G:/'),Path('H:/My Drive'),Path('H:/')):
        if candidate.is_dir(): return candidate
    return None

def _copy_tree(source, target, progress=None, label=''):
    if source is None:return 0
    source=Path(source);target=Path(target)
    if not source.is_dir():return 0
    count=0
    for item in source.rglob('*'):
        if item.is_file():
            dest=target/item.relative_to(source);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(item,dest);count+=1
            if progress: progress(label,count)
    return count

def _safe_user_id(user_id):
    """Convert a Google account label into one safe, stable folder name."""
    value=re.sub(r'[^A-Za-z0-9@._-]+','_',str(user_id).strip())
    value=value[:180].strip(' ._-')
    if not value or value in {'.','..'}: raise ValueError('บัญชี Google ไม่ถูกต้อง')
    if value.upper().split('.')[0] in {'CON','PRN','AUX','NUL'}: raise ValueError('บัญชี Google เป็นชื่อสงวนของ Windows')
    if re.fullmatch(r'(COM|LPT)[1-9]',value.upper().split('.')[0]): raise ValueError('บัญชี Google เป็นชื่อสงวนของ Windows')
    return value

def _media_proof(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or any(
        parent.is_symlink() or getattr(parent, 'is_junction', lambda: False)()
        for parent in path.parents):
        raise ValueError('ไฟล์เพลงเป็นลิงก์หรือหายไป: '+str(path))
    before=path.stat()
    sha=hashlib.sha256(); md5=hashlib.md5()
    with path.open('rb') as stream:
        while True:
            block=stream.read(1024*1024)
            if not block:break
            sha.update(block);md5.update(block)
    after=path.stat()
    if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns) != (
        after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):
        raise ValueError('ไฟล์เพลงเปลี่ยนระหว่างตรวจ: '+str(path))
    return {'size': before.st_size, 'sha256':sha.hexdigest(), 'md5':md5.hexdigest()}


def _safe_relative(path):
    from pathlib import PurePosixPath
    if not isinstance(path,str) or not path or '\\' in path or ':' in path:
        raise ValueError('เส้นทางไฟล์เพลงไม่ปลอดภัย')
    rel=PurePosixPath(path)
    if rel.is_absolute() or any(component in ('','.','..') for component in path.split('/')):
        raise ValueError('เส้นทางไฟล์เพลงนอกชุดสำรอง: '+str(path))
    return rel


def create_snapshot(data_dir, destination, user_id, songs_root=None, fx_root=None, progress=None,
                    *, stage_media=True, media_files_out=None, search_query=None):
    """Create a timestamped, self-contained user snapshot for Drive sync."""
    data_dir=Path(data_dir);destination=Path(destination)
    safe_user=_safe_user_id(user_id)
    base_stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    parent=destination/'X-Stage Karaoke'/'users'/safe_user;parent.mkdir(parents=True,exist_ok=True)
    stamp=base_stamp;index=1
    while (parent/stamp).exists():
        stamp=f'{base_stamp}-{index}';index+=1
    final_root=parent/stamp
    root=parent/(stamp+'.tmp-'+uuid.uuid4().hex)
    root.mkdir(parents=False,exist_ok=False)
    try:
        dbroot=root/'database';dbroot.mkdir()
        with closing(sqlite3.connect(data_dir/'songs.sqlite3')) as source, closing(sqlite3.connect(dbroot/'songs.sqlite3')) as target:source.backup(target)
        for name in ('settings.json','queue.json'):
            shutil.copy2(data_dir/name,dbroot/name)
        # Include both the recent history journal and durable all-time hits.
        # They are optional to keep older installations and backups compatible.
        if (data_dir/'history.json').is_file():
            from .performance_features import read_history_snapshot
            read_history_snapshot(data_dir/'history.json')
            shutil.copy2(data_dir/'history.json',dbroot/'history.json')
        if (data_dir/'play_stats.sqlite3').is_file():
            from .restore import copy_database
            from .play_stats import validate_stats
            validate_stats(data_dir/'play_stats.sqlite3')
            copy_database(data_dir/'play_stats.sqlite3',dbroot/'play_stats.sqlite3')
        write_transfer_metadata(dbroot)
        # v0.9.43 uses only visible catalog entries, not recursive whole-folder
        # traversal.  The direct Google API uploader may stream source files
        # without a second staging copy when stage_media=False.
        from .visible_sync import visible_song_plan
        songs, media_files, skipped = visible_song_plan(
            dbroot/'songs.sqlite3', songs_root, search_query=search_query)
        (root/'Songs').mkdir()
        if media_files_out is not None:
            media_files_out.update(media_files)
        # Proofs describe every source file in the visible Song Bundles. They
        # are also available when the direct Drive uploader skips local staging.
        proofs = {}
        count = 0
        for relative, original in sorted(media_files.items()):
            rel = _safe_relative(relative)
            proof = _media_proof(original)
            if stage_media:
                dest = root/'Songs'/rel
                dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(original,dest)
                if _media_proof(dest) != proof:
                    raise ValueError('ไฟล์เพลงเปลี่ยนระหว่างจัดชุดสำรอง: '+relative)
            proofs[relative] = proof
            count += 1
            if progress: progress('ตรวจชุดเพลงที่ค้นหาได้',count)
        (root/'Fx').mkdir()
        counts = {'songs_files':len(media_files),
                  'indexed_songs':len(songs), 'skipped_songs':len(skipped),
                  'fx_files':_copy_tree(fx_root,root/'Fx',progress,'กำลังคัดลอกเอฟเฟกต์')}
        if progress: progress('กำลังจัดทำรายการเพลง',len(songs))
        write_json(root/'web-manifest.json',{'schema':2,'user_id':safe_user,'songs':songs,'files':proofs,'skipped_count':len(skipped)})
        # Verify exact database bytes after transfer, including optional history.
        checksums={}
        for dbfile in sorted(dbroot.iterdir()):
            if dbfile.is_file():
                digest=hashlib.sha256()
                with dbfile.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024*1024), b''):
                        digest.update(chunk)
                checksums[dbfile.name]=digest.hexdigest()
        manifest={'schema':1,'provider':'google-drive-desktop','user_id':safe_user,'created_at':datetime.now(timezone.utc).isoformat(),'database':'database','counts':counts,'checksums':checksums,'song_scope':'visible' if not search_query else 'filtered-visible','media_staged_locally':bool(stage_media)}
        manifest['web_manifest_sha256']=hashlib.sha256((root/'web-manifest.json').read_bytes()).hexdigest()
        write_json(root/'manifest.json',manifest)
        root.replace(final_root)
        return final_root
    except Exception:
        shutil.rmtree(root,ignore_errors=True)
        raise

def validate_snapshot(root):
    root=Path(root);manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema')!=1 or not manifest.get('user_id'):raise ValueError('แพ็กเกจคลาวด์ไม่ถูกต้อง')
    checksums=manifest.get('checksums',{})
    mandatory={'songs.sqlite3','settings.json','queue.json','transfer-meta.json'}
    if not isinstance(checksums,dict) or not mandatory.issubset(checksums):
        raise ValueError('รายการ SHA-256 ของฐานข้อมูล/การตั้งค่า/คิว/การโอนย้ายไม่ครบ')
    for name, expected in checksums.items():
        # Only compare direct children of database; no relative paths allowed.
        if not isinstance(name,str) or name not in ('songs.sqlite3','settings.json','queue.json',
                                                   'history.json','play_stats.sqlite3','transfer-meta.json'):
            raise ValueError('ชื่อไฟล์สำรองไม่ถูกต้อง')
        if not isinstance(expected,str) or not re.fullmatch(r'[0-9a-f]{64}',expected):
            raise ValueError('ค่า SHA-256 ไม่ถูกต้อง')
        path=root/'database'/name
        if not path.is_file():raise ValueError('ไฟล์สำรองหายไป: '+name)
        digest=hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024*1024),b''):
                digest.update(chunk)
        if digest.hexdigest()!=expected:raise ValueError('ไฟล์สำรองไม่ผ่าน SHA-256: '+name)
    # Metadata checksums are insufficient for a restore-ready backup.
    if not isinstance(manifest.get('web_manifest_sha256'),str) or not re.fullmatch('[0-9a-f]{64}',manifest['web_manifest_sha256']):
        raise ValueError('ไม่มีค่า SHA-256 ของรายการ Song Bundle')
    raw_web=(root/'web-manifest.json').read_bytes()
    if hashlib.sha256(raw_web).hexdigest()!=manifest['web_manifest_sha256']:
        raise ValueError('SHA-256 ของรายการ Song Bundle ไม่ตรง')
    web=json.loads(raw_web.decode('utf-8'))
    if web.get('schema')!=2 or web.get('user_id')!=manifest['user_id']:
        raise ValueError('ไม่มีรายการไฟล์เพลงแบบตรวจความครบถ้วน v0.9.43')
    songs=web.get('songs');files=web.get('files')
    if not isinstance(songs,list) or not isinstance(files,dict):
        raise ValueError('รูปแบบรายการ Song Bundle ไม่ถูกต้อง')
    referenced=[]
    for song in songs:
        if not isinstance(song,dict) or not isinstance(song.get('files'),dict) or 'media' not in song['files']:
            raise ValueError('Song Bundle ไม่มีไฟล์หลัก')
        referenced.extend(song['files'].values())
    if set(referenced)!=set(files) or len(files)!=manifest.get('counts',{}).get('songs_files') or len(songs)!=manifest.get('counts',{}).get('indexed_songs'):
        raise ValueError('บัญชีไฟล์เพลงและรายการใน Manifest ไม่ตรงกัน')
    for relative, proof in files.items():
        rel=_safe_relative(relative)
        if not isinstance(proof,dict) or not isinstance(proof.get('size'),int) or proof['size']<0 or not re.fullmatch('[0-9a-f]{64}',str(proof.get('sha256',''))) or not re.fullmatch('[0-9a-f]{32}',str(proof.get('md5',''))):
            raise ValueError('หลักฐานตรวจไฟล์เพลงไม่ถูกต้อง: '+relative)
        path=root/'Songs'/rel
        actual=_media_proof(path)  # missing files must invalidate restore readiness
        if actual['size']!=proof['size'] or actual['sha256']!=proof['sha256']:
            raise ValueError('SHA-256 ไฟล์เพลงไม่ตรง หรือไฟล์ถูกแก้ไข: '+relative)
    info=validate_backup(root/'database')
    return {'root':str(root),'user_id':manifest['user_id'],'songs':info['songs'],
            'queue':len(info['queue']),'media_verified':True,'media_files':len(files)}

def stage_snapshot(root, data_dir):
    """Validate first, then stage database/settings/queue for next startup."""
    validate_snapshot(root)
    web=json.loads((Path(root)/'web-manifest.json').read_text(encoding='utf-8'))
    if web.get('songs'):
        # SQLite contains original absolute source paths. Staging it without
        # restoring/remapping the media would create a misleading broken library.
        raise ValueError('ชุดสำรองมีเพลง: ต้องกู้คืนไฟล์เพลงและกำหนดพาธใหม่ก่อนนำฐานมาใช้ ไม่อนุญาตกู้เฉพาะ SQLite')
    return stage_restore(Path(root)/'database',data_dir)
