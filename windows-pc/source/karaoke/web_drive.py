"""Private Google Drive web sync with verified, streaming catalog checkpoints.

Rendering overlaps media upload. The first verified batch becomes playable;
subsequent batches publish small catalog deltas, followed by final compaction.
Only the owner's scoped OAuth client accesses private Google Drive files.
"""
from __future__ import annotations

import json
import hashlib
import os
import sqlite3 as _sqlite3
from collections import deque
import tempfile
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from .google_drive_sync import API, FOLDER_MIME
from .web_assets import BatchRenderer, file_hash, local_candidates

ROOT_NAME = 'XStageWeb'
SCHEMA = 1


class CatalogPublishError(RuntimeError):
    """Abort the entire sync when the visible generation cannot be committed."""



def _json_file(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':'),
                             sort_keys=True).encode('utf-8')
        with temporary.open('wb') as checkpoint:
            checkpoint.write(encoded)
            checkpoint.flush()
            os.fsync(checkpoint.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _file_by_name(drive, parent, name):
    matched = [r for r in drive.children(parent, name) if r['name'] == name]
    if len(matched) > 1:
        raise RuntimeError('Drive มีชื่อไฟล์ซ้ำ: ' + name)
    return matched[0] if matched else None


def _read_file(drive, file_id):
    # Support deterministic memory doubles; production uses authenticated media GET.
    if hasattr(drive, 'download'):
        return drive.download(file_id)
    from .google_drive_sync import _request
    _, _, raw = _request(API + '/' + urllib.parse.quote(file_id, safe='') + '?alt=media',
                         drive.access_token())
    return raw


def _remote_metadata(drive, file_id):
    if hasattr(drive, 'get_metadata'):
        return drive.get_metadata(file_id)
    return drive.json(API + '/' + urllib.parse.quote(file_id, safe='') +
                      '?fields=id,name,mimeType,md5Checksum,size,version,trashed')


def _verified(drive, item, expected_md5=None):
    if not item or not item.get('id'):
        return False
    info = _remote_metadata(drive, item['id'])
    return (not info.get('trashed') and info.get('mimeType') != FOLDER_MIME and
            (expected_md5 is None or info.get('md5Checksum') == expected_md5))


def _folder(drive, root, name):
    return drive.folder(root, name)['id']


def _upload_bytes(drive, parent, name, content, existing=None):
    with tempfile.TemporaryDirectory(prefix='xstage-web-pointer-') as work:
        p = Path(work) / name
        p.write_bytes(content)
        result = drive._upload(p, parent, existing)
        if not result or not result.get('id'):
            raise RuntimeError('Drive ไม่ส่ง File ID หลังอัปโหลด '+name)
        if not _verified(drive, result, hashlib.md5(content).hexdigest()):
            raise RuntimeError('Drive เก็บ '+name+' ไม่ครบหรือ Checksum ไม่ตรง')
        return result


def _load_current(drive, root):
    pointer = _file_by_name(drive, root, 'current.json')
    if not pointer:
        legacy = _file_by_name(drive, root, 'database.json')
        if legacy:
            old = json.loads(_read_file(drive, legacy['id']).decode('utf-8'))
            if old.get('schemaVersion') != SCHEMA or not isinstance(old.get('songs'), list):
                raise ValueError('พบ database.json เดิมที่ไม่รองรับ ต้องตรวจรูปแบบก่อนดำเนินการ')
            for item in old['songs']:
                if not isinstance(item, dict) or not item.get('webSongId') or not (item.get('audio') or {}).get('fileId'):
                    raise ValueError('ฐานเดิมไม่ระบุ Web Song ID/Drive File ID ต้องโยกข้อมูลด้วยขั้นตอนแยก')
            return None, None, old
        return None, None, {'schemaVersion': SCHEMA, 'songs': []}
    current = json.loads(_read_file(drive, pointer['id']).decode('utf-8'))
    if current.get('schemaVersion') != SCHEMA or not isinstance(current.get('catalogFileId'), str):
        raise ValueError('current.json เดิมไม่รองรับ ต้องตรวจด้วยตนเอง ไม่เขียนทับ')
    catalog = json.loads(_read_file(drive, current['catalogFileId']).decode('utf-8'))
    if catalog.get('schemaVersion') != SCHEMA or not isinstance(catalog.get('songs'), list):
        raise ValueError('database.json เดิมมีรูปแบบไม่รองรับ ไม่แก้ไขหรือทับไฟล์เก่า')
    # v1 compatible: legacy clients see the base snapshot; new clients apply
    # immutable deltas. Never publish an unverified media pair in any delta.
    delta_ids = current.get('deltaFileIds', [])
    if not isinstance(delta_ids, list) or len(delta_ids) > 32 or len(delta_ids) != len(set(delta_ids)):
        raise ValueError('รายการ Delta Catalog บน Drive ไม่ถูกต้อง')
    if delta_ids:
        by_id = {row['webSongId']: row for row in catalog['songs']
                 if isinstance(row, dict) and isinstance(row.get('webSongId'), str)}
        for delta_id in delta_ids:
            if not isinstance(delta_id, str) or not delta_id:
                raise ValueError('Delta Catalog ไม่มี Drive File ID')
            patch = json.loads(_read_file(drive, delta_id).decode('utf-8'))
            if (patch.get('schemaVersion') != SCHEMA or not isinstance(patch.get('upserts'), list)
                    or not isinstance(patch.get('removes'), list)):
                raise ValueError('Delta Catalog ไม่รองรับ ไม่เปลี่ยนฐานเว็บเดิม')
            for removed in patch['removes']:
                if not isinstance(removed, str):
                    raise ValueError('Delta Catalog มีรหัสเพลงลบไม่ถูกต้อง')
                by_id.pop(removed, None)
            for row in patch['upserts']:
                if not isinstance(row, dict) or not isinstance(row.get('webSongId'), str):
                    raise ValueError('Delta Catalog มีรายการเพลงไม่ถูกต้อง')
                by_id[row['webSongId']] = row
        catalog = {'schemaVersion': SCHEMA, 'songs': list(by_id.values())}
        if current.get('songCount') != len(by_id):
            raise ValueError('ฐานเว็บที่เผยแพร่เป็นชุดมีจำนวนเพลงไม่ตรงกัน')
    return pointer, current, catalog


def _same_pointer(drive, root, pointer, prior):
    """Optimistic safety check; avoid clobbering another completed sync.

    Drive's files.update is not a compare-and-swap; clients MUST avoid running
    simultaneous publishing on separate PCs, despite this revalidation.
    """
    existing = _file_by_name(drive, root, 'current.json')
    if (not pointer) != (not existing):
        return False
    if pointer is None:
        return True
    if existing['id'] != pointer['id']:
        return False
    now = json.loads(_read_file(drive, existing['id']).decode('utf-8'))
    return now.get('generation') == prior.get('generation')


def _publish(drive, root, latest_pointer, latest_current, songs, cache_dir=None, *, include_pointer=False):
    generation = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    payload = {'schemaVersion': SCHEMA, 'generation': generation, 'totalSongs': len(songs),
               'songs': sorted(songs, key=lambda r: (str(r.get('code', '')), str(r.get('webSongId',''))))}
    catalogs = _folder(drive, root, 'catalogs')
    encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if cache_dir is not None:
        # Retain a local copy even if Drive becomes unreachable mid-publication.
        _json_file(Path(cache_dir) / 'catalogs' / ('database-' + generation + '.json'), payload)
    catalog_file = _upload_bytes(drive, catalogs, 'database-' + generation + '.json', encoded)
    pointer = {'schemaVersion': SCHEMA, 'generation': generation,
               'catalogFileId': catalog_file['id'], 'songCount': len(songs)}
    # Check again after slow upload. Non-atomic across multiple simultaneous
    # desktops, but never overwrite if a change has already become visible.
    if not _same_pointer(drive, root, latest_pointer, latest_current):
        raise RuntimeError('Catalog ถูกเปลี่ยนจากเครื่องอื่นระหว่างซิงก์ หยุดเผยแพร่เพื่อป้องกันเขียนทับ')
    _upload_bytes(drive, root, 'current.json',
                  json.dumps(pointer, ensure_ascii=False).encode('utf-8'), latest_pointer)
    if cache_dir is not None:
        _json_file(Path(cache_dir) / 'database.json', payload)
        _json_file(Path(cache_dir) / 'current.json', pointer)
    return (generation, pointer) if include_pointer else generation


def _publish_delta(drive, root, latest_pointer, latest_current, upserts, removes, total_songs,
                   cache_dir=None):
    """Publish verified new/changed song rows as one immutable incremental batch.

    A single update of current.json makes the entire batch visible to new web
    clients. A crash before the pointer update leaves an orphan delta but does
    not expose incomplete records. No original media or local database upload.
    """
    if latest_current is None or not latest_current.get('catalogFileId'):
        raise ValueError('ต้องสร้าง Catalog ชุดแรกก่อนเผยแพร่แบบส่วนเพิ่ม')
    deltas = list(latest_current.get('deltaFileIds') or [])
    if len(deltas) >= 24:
        raise ValueError('Delta Catalog มีจำนวนมาก ต้องสร้าง Snapshot ใหม่ก่อน')
    generation = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    document = {'schemaVersion': SCHEMA, 'generation': generation,
                'upserts': sorted(upserts, key=lambda row: str(row['webSongId'])),
                'removes': sorted(set(removes))}
    encoded = json.dumps(document, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    catalog_folder = _folder(drive, root, 'catalogs')
    delta_file = _upload_bytes(drive, catalog_folder, 'delta-'+generation+'.json', encoded)
    pointer = {'schemaVersion': SCHEMA, 'generation': generation,
               'catalogFileId': latest_current['catalogFileId'],
               'deltaFileIds': [*deltas, delta_file['id']], 'songCount': total_songs}
    if not _same_pointer(drive, root, latest_pointer, latest_current):
        raise RuntimeError('ฐานเว็บถูกปรับจากเครื่องอื่นระหว่างซิงค์ หยุดเพื่อป้องกันข้อมูลสูญหาย')
    _upload_bytes(drive, root, 'current.json',
                  json.dumps(pointer, ensure_ascii=False).encode('utf-8'), latest_pointer)
    if cache_dir is not None:
        _json_file(Path(cache_dir) / 'current.json', pointer)
    return generation, pointer


def _place(drive, parent, name, source):
    """Reuse remote object only if Drive confirms matching MD5; no file copy."""
    existing = _file_by_name(drive, parent, name)
    expected = file_hash(source, 'md5')
    if existing and existing.get('mimeType') == FOLDER_MIME:
        raise ValueError('ชื่อไฟล์ซ้ำกับโฟลเดอร์: '+name)
    if existing and _verified(drive, existing, expected):
        return existing['id'], False, expected
    result = drive._upload(source, parent, existing)
    if file_hash(source, 'md5') != expected:
        raise IOError('ไฟล์ต้นทางเปลี่ยนระหว่างอัปโหลด: '+name)
    if not _verified(drive, result, expected):
        raise IOError('ตรวจสอบไฟล์บน Drive ไม่ผ่าน: ' + name)
    return result['id'], True, expected


def _remote_ready(drive, old):
    if not old or not old.get('sourceSignature'):
        return False
    audio = old.get('audio') or {}; lyrics = old.get('lyrics') or {}
    try:
        return (_verified(drive, {'id':audio['fileId']}, audio['md5']) and
                _verified(drive, {'id':lyrics['fileId']}, lyrics['md5']))
    except (KeyError, ValueError, OSError):
        return False


class DriveMediaInventory:
    """Read-only, per-run metadata index grouped by Drive subfolder.

    One paginated listing per audio/lyrics bucket replaces two metadata GETs
    *per old song*. Never trust a filename alone; check exact file ID and MD5.
    An inaccessible folder/listing is an error, not proof a song is missing.
    """
    def __init__(self, drive, root):
        self.drive = drive
        self.root = root
        self._parents = {}
        self._buckets = {}

    def _parent(self, kind):
        if kind not in self._parents:
            item = _file_by_name(self.drive, self.root, kind)
            self._parents[kind] = (item['id'] if item and item.get('mimeType') == FOLDER_MIME else None)
        return self._parents[kind]

    def _bucket(self, kind, code):
        key=(kind, re_bucket(code))
        if key not in self._buckets:
            parent=self._parent(kind)
            folder = _file_by_name(self.drive, parent, key[1]) if parent else None
            if folder is not None and folder.get('mimeType') != FOLDER_MIME:
                folder = None
            entries = self.drive.children(folder['id']) if folder else ()
            self._buckets[key] = {f['id']: f for f in entries if isinstance(f,dict) and f.get('id')}
        return self._buckets[key]

    def valid(self, row):
        if not isinstance(row,dict) or not row.get('sourceSignature'):
            return False
        code = row.get('code')
        if not code:
            return False
        for kind, field in (('audio','audio'),('lyrics','lyrics')):
            item = row.get(field) or {}
            fid, md5 = item.get('fileId'), item.get('md5')
            if not isinstance(fid,str) or not fid or not isinstance(md5,str) or len(md5)!=32:
                return False
            entry=self._bucket(kind,code).get(fid)
            if (not entry or entry.get('trashed') or entry.get('mimeType')==FOLDER_MIME or
                    entry.get('md5Checksum') != md5):
                return False
        return True


def verify_web_catalog(drive, root, *, progress=None, cancel=None):
    """Audit every published song against actual private Drive IDs and hashes.

    Returns the exact checked/invalid count. Does not silently remove or mark
    missing songs as repaired. Missing source files require user intervention.
    """
    _pointer, current, catalog = _load_current(drive,root)
    if current is None:
        return {'checked':0,'valid':0,'issues':[], 'generation':None}
    inventory=DriveMediaInventory(drive,root)
    issues=[]
    songs=catalog['songs']
    for number,row in enumerate(songs,1):
        if cancel is not None and cancel.is_set():
            raise RuntimeError('ยกเลิกการตรวจความถูกต้องของเพลงเว็บ')
        if hasattr(drive,'check_cancelled'):
            drive.check_cancelled()
        if not inventory.valid(row):
            issues.append({'webSongId':row.get('webSongId',''),
                           'libraryId':row.get('libraryId'),
                           'sourceId':row.get('sourceId'),
                           'code':row.get('code',''),
                           'reason':'ไฟล์เสียงหรือเนื้อร้องไม่พบ / MD5 ไม่ตรง'})
        if progress and (number == 1 or number % 250 == 0 or number==len(songs)):
            progress('ตรวจความครบของเพลงเว็บ: '+str(number)+'/'+str(len(songs)), number,len(songs))
    return {'checked':len(songs),'valid':len(songs)-len(issues),
            'issues':issues, 'generation':current['generation']}


def verify_and_repair_web_catalog(drive, root, db_path, song_roots, native,
                                  settings,soundfont,cache_dir, *, ffmpeg='ffmpeg',
                                  progress=None,cancel=None,renderer_factory=None,
                                  workers=1,song_types=None):
    """Full audit; rerender/reupload damaged songs whose local source is known.

    Repairs are journaled and published via the same verified pipeline. If a
    source is unavailable, report an unresolved issue rather than claiming 100%.
    """
    report=verify_web_catalog(drive,root,progress=progress,cancel=cancel)
    if not report['issues']:
        return {**report,'repaired':0,'complete':True}
    try:
        library_id=str(json.loads((Path(cache_dir)/'library-identity.json').read_text(encoding='utf-8'))['id'])
    except (ValueError, OSError, KeyError):
        library_id=None
    sources={int(issue['sourceId']) for issue in report['issues']
             if library_id and issue.get('libraryId')==library_id and
             str(issue.get('sourceId','')).isdigit()}
    if sources:
        if progress:progress('ตรวจพบไฟล์ไม่ครบ • กำลังซ่อม '+str(len(sources))+' เพลงจากต้นฉบับในเครื่อง')
        sync_web_assets(drive,db_path,song_roots,native,settings,soundfont,cache_dir,
            ffmpeg=ffmpeg,progress=progress,cancel=cancel,renderer_factory=renderer_factory,
            workers=workers,song_types=song_types,repair_source_ids=sources,
            verify_integrity=False)
        after=verify_web_catalog(drive,root,progress=progress,cancel=cancel)
    else:
        after=report
    return {**after,'repaired':max(0,len(report['issues'])-len(after['issues'])),
            'complete':not bool(after['issues'])}


def sync_web_assets(drive, db_path, song_roots, native, settings, soundfont,
                    cache_dir, *, ffmpeg='ffmpeg', progress=None, cancel=None,
                    renderer_factory=None, workers=1, song_types=None,
                    first_batch_size=10, batch_size=200, publish_interval=90,
                    storage_progress=None, repair_source_ids=None, verify_integrity=True,
                    upload_workers=2):
    """Render/upload concurrently; publish verified chunks for immediate web playback.

    Default: first 10 verified songs, then batches of 200 songs or
    90 seconds (whichever comes first). R18 also overlaps up to three *song*
    uploads with later conversions, while the main thread exclusively commits
    verified pairs into SQLite and the visible catalog. A crash leaves the
    last published current.json intact; next run reuses verified remote files.
    """
    def emit(msg, done=0, total=0):
        if progress: progress(msg, done, total)
    def check():
        if cancel is not None and cancel.is_set():
            raise RuntimeError('ยกเลิกการซิงก์ X-Stage Web')
        if hasattr(drive, 'check_cancelled'):
            drive.check_cancelled()

    check()
    # Name-filtered Drive query avoids listing unrelated personal files.  The
    # preflight must emit *real* checkpoints because each remote call can take
    # many seconds on a congested connection. Do not report fake percentages.
    emit('กำลังค้นหาโฟลเดอร์ XStageWeb บน Google Drive…')
    roots = [x for x in drive.children('root', ROOT_NAME)
             if x.get('name', ROOT_NAME) == ROOT_NAME and x.get('mimeType') == FOLDER_MIME]
    check()
    if len(roots) > 1:
        raise ValueError('มี XStageWeb หลายโฟลเดอร์ กรุณาจัดการก่อนซิงก์')
    if not roots:
        emit('ไม่พบโฟลเดอร์ XStageWeb เดิม • กำลังสร้างโฟลเดอร์สำหรับเพลงเว็บ…')
    root = roots[0]['id'] if roots else _folder(drive, 'root', ROOT_NAME)
    emit('พบโฟลเดอร์ XStageWeb • กำลังอ่านดัชนีเพลงบน Google Drive…')
    current_file, current, previous = _load_current(drive, root)
    check()
    emit(f'อ่านดัชนี Drive แล้ว {len(previous["songs"]):,} เพลง • กำลังตรวจไฟล์ต้นทางในเครื่อง…')
    # Do not recognize old backup web-manifest as a new-format catalog.
    inventory = DriveMediaInventory(drive,root)
    old_rows = {row['webSongId']: row for row in previous['songs'] if isinstance(row, dict)
                and isinstance(row.get('webSongId'), str)}
    # Preserve previously published records that are not present locally,
    # including songs uploaded from another PC. Explicit local hide removes by
    # same local source ID (and only within the matching local library).
    result_rows = dict(old_rows)
    from .online_preflight import visible_row_count
    # The row-count is optional UI metadata, never a prerequisite for sync.
    # A test/legacy adapter may provide a candidate plan without a readable
    # SQLite file. The real local_candidates() still rejects an invalid DB.
    try:
        source_rows = visible_row_count(db_path)
    except (OSError, ValueError, _sqlite3.Error):
        source_rows = 0
    def planning_progress(scanned):
        check()
        # visible_song_plan emits once per 250 rows, including rejected rows.
        # The count is explicitly *database rows*, not files uploaded.
        measured = (f'{scanned:,}/{source_rows:,}' if source_rows else f'{scanned:,}')
        emit(f'กำลังตรวจไฟล์ต้นทาง • อ่านแล้ว {measured} แถวฐานเพลง', scanned, source_rows)
    candidates, rejected = local_candidates(db_path, song_roots,
                                            song_types=song_types,
                                            progress=planning_progress)
    check()
    if repair_source_ids is not None:
        target_ids={int(value) for value in repair_source_ids}
        candidates=[(song,parts) for song,parts in candidates if int(song['id']) in target_ids]
        # Repair mode keeps the other published rows exactly as they were.
        rejected=[]
    total = len(candidates)
    emit(f'พบเพลงที่เข้าข่ายซิงก์ {total:,} เพลง • ข้ามรายการไม่พร้อม {len(rejected):,} รายการ')
    emit('กำลังตรวจโฟลเดอร์เสียงและเนื้อร้องบน Google Drive…')
    audio_folder = _folder(drive, root, 'audio')
    lyric_folder = _folder(drive, root, 'lyrics')
    # Folder IDs cannot change within this sync. Avoid two Drive name queries
    # per song when 70,000 songs share a small number of first-letter buckets.
    bucket_folders = {}
    def bucket_parent(kind, code):
        bucket = re_bucket(code)
        key = (kind, bucket)
        if key not in bucket_folders:
            bucket_folders[key] = _folder(drive,
                audio_folder if kind == 'audio' else lyric_folder, bucket)
        return bucket_folders[key]
    check()
    emit(f'ตรวจโฟลเดอร์บน Drive ครบ • เริ่มตรวจ/แปลง/อัปโหลด {total:,} เพลง', 0, total)
    # Persistent local library identity distinguishes IDs from other computers.
    identity_file = Path(cache_dir) / 'library-identity.json'
    try:
        library_id = str(json.loads(identity_file.read_text(encoding='utf-8'))['id'])
    except (KeyError, OSError, ValueError):
        import uuid
        library_id = str(uuid.uuid4())
        _json_file(identity_file, {'id':library_id})
    # A SQLite journal writes one verified song per transaction, not a growing
    # JSON blob. Crucial for libraries with 70,000+ songs and abrupt power loss.
    from .web_resume import VerifiedUploadJournal
    # The journal is account-scoped and contains only verified metadata, never
    # access/refresh tokens. A crash after uploading and before publishing can
    # therefore resume without re-encoding every completed song.
    def recover_uploaded_row(song, web_id, signature_value):
        entry = journal.get(web_id)
        if not isinstance(entry, dict) or entry.get('state') != 'uploaded':
            return None
        row = entry.get('row')
        if not isinstance(row, dict):
            return None  # legacy journal: let the hash-addressed remote upload be reused
        if (entry.get('signature') != signature_value or
                row.get('webSongId') != web_id or
                row.get('sourceSignature') != signature_value or
                row.get('libraryId') != library_id or
                row.get('sourceId') != int(song['id']) or
                str(row.get('code')) != str(song.get('code') or song['id'])):
            return None
        if not inventory.valid(row):
            return None
        return row

    def recover_prior_upload_with_local_proof(song, web_id, signature_value):
        """Rebuild a missing catalog row for verified legacy Drive uploads.

        A matching file name alone is NOT proof: require a content-addressed
        stem, full local proof hashes, valid lyrics, and matching Drive MD5 for
        both objects. If the local proof was lost, fall back to the normal
        renderer + _place() path, which independently verifies and reuses
        matching remote objects rather than trusting an unverified pair.
        """
        from .web_assets import safe_stem
        stem = safe_stem(song.get('code') or song['id'], signature_value)
        cache = Path(cache_dir) / signature_value[:2]
        audio_path = cache / (stem + '.m4a')
        lyric_path = cache / (stem + '.json')
        proof_path = cache / (stem + '.proof.json')
        if not all(p.is_file() for p in (audio_path, lyric_path, proof_path)):
            return None
        try:
            proof = json.loads(proof_path.read_text(encoding='utf-8'))
            lyrics = json.loads(lyric_path.read_text(encoding='utf-8'))
            if (proof.get('fingerprint') != signature_value or
                    proof.get('audio_sha256') != file_hash(audio_path) or
                    proof.get('lyrics_sha256') != file_hash(lyric_path) or
                    lyrics.get('schemaVersion') != SCHEMA or
                    str(lyrics.get('id')) != str(song.get('code') or song['id']) or
                    not isinstance(lyrics.get('lines'), list) or not lyrics['lines'] or
                    audio_path.stat().st_size <= 256):
                return None
            duration = float(lyrics.get('duration') or 0)
            if not (0 < duration <= 4 * 3600 + 30):
                return None
        except (OSError, ValueError, TypeError, KeyError):
            return None
        code = str(song.get('code') or song['id'])
        audio_parent = bucket_parent('audio', code)
        lyric_parent = bucket_parent('lyrics', code)
        audio_file = _file_by_name(drive, audio_parent, stem + '.m4a')
        lyric_file = _file_by_name(drive, lyric_parent, stem + '.json')
        if not audio_file or not lyric_file:
            return None
        audio_md5 = file_hash(audio_path, 'md5')
        lyric_md5 = file_hash(lyric_path, 'md5')
        if not (_verified(drive, audio_file, audio_md5) and
                _verified(drive, lyric_file, lyric_md5)):
            return None
        code = str(song.get('code') or song['id'])
        return {
            'webSongId': web_id, 'libraryId': library_id,
            'sourceId': int(song['id']), 'code': code,
            'title': song.get('title') or code, 'artist': song.get('artist') or '',
            'type': song.get('format') or 'MIDI', 'duration': duration,
            'sourceSignature': signature_value,
            'audio': {'fileId': audio_file['id'], 'md5': audio_md5, 'mimeType': 'audio/mp4'},
            'lyrics': {'fileId': lyric_file['id'], 'md5': lyric_md5, 'schemaVersion': SCHEMA},
        }

    def replace_local_version(web_id, song):
        # A different soundfont/source signature replaces only the catalog row
        # from this exact local library. Remote media remains untouched.
        for old_key, old_row in list(result_rows.items()):
            if (old_key != web_id and old_row.get('libraryId') == library_id and
                    old_row.get('sourceId') == int(song['id'])):
                result_rows.pop(old_key, None)
                pending_upserts.pop(old_key, None)
                if old_key in published_rows:
                    pending_removes.add(old_key)

    completed, uploaded, failures, reused = 0, 0, [], 0
    storage_samples = deque(maxlen=120)
    added_upload_bytes = 0
    def report_storage(song_bytes=0, *, force=False):
        # A zero-byte sample represents a song safely reused on Drive. A real
        # file upload counts only after the remote MD5 was verified. Never use
        # original MIDI size as a prediction for compressed M4A size.
        storage_samples.append(max(0, int(song_bytes)))
        if storage_progress and (force or len(storage_samples) < 15 or completed % 10 == 0):
            storage_progress({
                'processed': completed, 'total': total,
                'uploaded_bytes': added_upload_bytes,
                'sample_songs': len(storage_samples),
                'sample_uploads': sum(1 for size in storage_samples if size > 0),
                'sample_bytes': sum(storage_samples),
            })
    first_batch_size = max(1, min(1000, int(first_batch_size)))
    batch_size = max(1, min(2000, int(batch_size)))
    publish_interval = max(5, float(publish_interval))
    published_rows = dict(old_rows)
    pending_upserts, pending_removes = {}, set()
    first_batch_published = False
    last_published_at = time.monotonic()
    batches_published = 0

    def record_upsert(row):
        key = row['webSongId']
        pending_removes.discard(key)
        if row == published_rows.get(key):
            pending_upserts.pop(key, None)
        else:
            pending_upserts[key] = row

    def publish_ready_batch(force=False):
        nonlocal current, current_file, first_batch_published
        nonlocal last_published_at, batches_published
        if not pending_upserts and not pending_removes:
            return
        check()
        changes = len(pending_upserts) + len(pending_removes)
        required = batch_size if first_batch_published else first_batch_size
        if not force and changes < required and time.monotonic() - last_published_at < publish_interval:
            return
        emit(f'กำลังเผยแพร่ฐานเพลงชุด {batches_published+1:,} • พร้อมเล่นแล้ว {len(result_rows):,} เพลง',
             completed, total)
        try:
            if current is None or len(current.get('deltaFileIds', [])) >= 20:
                generation, pointer = _publish(drive, root, current_file, current,
                                               list(result_rows.values()), cache_dir,
                                               include_pointer=True)
            else:
                generation, pointer = _publish_delta(drive, root, current_file, current,
                                                     list(pending_upserts.values()),
                                                     list(pending_removes),len(result_rows),cache_dir)
            if current_file is None:
                current_file = _file_by_name(drive, root, 'current.json')
                if current_file is None:
                    raise RuntimeError('เผยแพร่แล้วแต่ค้นหา current.json ไม่พบ')
        except Exception as error:
            raise CatalogPublishError('เผยแพร่ฐานเพลงชุดไม่สำเร็จ: '+str(error)) from error
        current = pointer
        for key in pending_removes:
            published_rows.pop(key, None)
        published_rows.update(pending_upserts)
        pending_upserts.clear();pending_removes.clear()
        first_batch_published = True
        batches_published += 1
        last_published_at = time.monotonic()
        emit(f'เผยแพร่ฐานเพลงรุ่น {generation} • เว็บไซต์เปิดเพลงได้แล้ว {len(result_rows):,} เพลง • เผยแพร่ชุด {batches_published:,} • กำลังแปลงชุดถัดไป',
             completed,total)

    factory = renderer_factory or BatchRenderer
    workers = max(1, min(4, int(workers)))
    use_pool = workers > 1 and renderer_factory is None
    from contextlib import ExitStack
    from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
    from .web_assets import signature, safe_stem
    # The render queue and bounded upload queue are separate. The main thread
    # alone updates the SQLite journal and publishes pointers. Upload threads
    # use Drive APIs only for distinct content-addressed media filenames.
    with ExitStack() as resources:
        journal = resources.enter_context(VerifiedUploadJournal(cache_dir, root))
        if use_pool:
            from .web_assets import init_render_worker, render_worker_song
            executor = resources.enter_context(ProcessPoolExecutor(
                max_workers=workers, initializer=init_render_worker,
                initargs=(native, settings, soundfont, cache_dir, ffmpeg)))
            submit_render = lambda song, parts: executor.submit(render_worker_song, song, parts)
        else:
            # Renderer closes only after all queued conversion futures complete.
            renderer = resources.enter_context(factory(native, settings, soundfont,
                                                        cache_dir, ffmpeg=ffmpeg))
            executor = resources.enter_context(ThreadPoolExecutor(max_workers=1,
                                               thread_name_prefix='xstage-web-render'))
            submit_render = lambda song, parts: executor.submit(renderer.build, song, parts, cancel=cancel)
        # Never launch an unbounded upload queue: memory and outstanding Drive
        # requests must remain predictable for slow links and huge libraries.
        upload_workers = max(1, min(3, int(upload_workers)))
        upload_executor = resources.enter_context(ThreadPoolExecutor(
            max_workers=upload_workers, thread_name_prefix='xstage-web-upload'))
        in_flight = deque()
        queued = {}
        prefetch_size = max(2, workers * 2)

        def upload_verified_pair(audio_parent, lyric_parent, m4a, lyr):
            # A single job owns both files, but the pair is never declared
            # complete until *both* Drive MD5s and IDs have been validated.
            sound_id, new_audio, sound_md5 = _place(drive, audio_parent, m4a.name, m4a)
            lyric_id, new_lyrics, lyric_md5 = _place(drive, lyric_parent, lyr.name, lyr)
            return sound_id, new_audio, sound_md5, lyric_id, new_lyrics, lyric_md5

        def finalize_oldest_upload():
            nonlocal completed, uploaded, added_upload_bytes
            song, web_id, sig, duration, m4a, lyr, future = in_flight.popleft()
            code = str(song.get('code') or song['id'])
            song_uploaded_bytes = 0
            try:
                check()
                (sound_id, new_audio, sound_md5,
                 lyric_id, new_lyrics, lyric_md5) = future.result()
                check()
                if new_audio:
                    song_uploaded_bytes += m4a.stat().st_size
                if new_lyrics:
                    song_uploaded_bytes += lyr.stat().st_size
                added_upload_bytes += song_uploaded_bytes
                uploaded += int(new_audio) + int(new_lyrics)
                row = {
                    'webSongId':web_id, 'libraryId':library_id,
                    'sourceId':int(song['id']), 'code':code,
                    'title':song.get('title') or code, 'artist':song.get('artist') or '',
                    'type':song.get('format') or 'MIDI', 'duration':duration,
                    'sourceSignature':sig,
                    'audio':{'fileId':sound_id, 'md5':sound_md5, 'mimeType':'audio/mp4'},
                    'lyrics':{'fileId':lyric_id, 'md5':lyric_md5, 'schemaVersion':SCHEMA}}
                # This is the only writer of SQLite and the published catalog.
                # No partial upload or asynchronous task may commit a song.
                journal[web_id] = {'state':'uploaded', 'signature':sig,
                    'audioId':sound_id, 'lyricsId':lyric_id, 'row':row}
                replace_local_version(web_id, song)
                result_rows[web_id] = row
                record_upsert(row)
            except Exception as exc:
                if isinstance(exc, CatalogPublishError) or (cancel is not None and cancel.is_set()):
                    raise
                failures.append((code, str(exc)))
            completed += 1
            report_storage(song_uploaded_bytes, force=completed == total)
            # A catalog publishing failure aborts the run, never treated as a
            # failed song. Already finished media remain available for resume.
            publish_ready_batch()
            emit('ตรวจสอบการอัปโหลดแล้ว '+str(completed)+'/'+str(total), completed, total)


        def prefetch(start):
            for i in range(start, min(total, start + prefetch_size)):
                if i in queued:
                    continue
                song, parts = candidates[i]
                try:
                    sg = signature(parts, soundfont, settings)
                    key = safe_stem(song.get('code') or song['id'], sg)
                    # A verified local proof may let the main thread rebuild a
                    # missing legacy catalog directly from Drive file IDs.
                    # Do not preemptively rerender such a song in a worker.
                    if (Path(cache_dir) / sg[:2] / (key + '.proof.json')).is_file():
                        continue
                    previous_row = old_rows.get(key)
                    if previous_row and previous_row.get('sourceSignature') == sg:
                        # Main loop checks remote media via the bucket inventory;
                        # avoid doubling the number of Drive requests here.
                        continue
                    # It may be present in a crash journal although the new
                    # catalog generation was never activated on Google Drive.
                    pending = journal.get(key)
                    if (isinstance(pending, dict) and pending.get('state') == 'uploaded' and
                            pending.get('signature') == sg and isinstance(pending.get('row'), dict)):
                        continue
                except (OSError, ValueError, KeyError):
                    # Let the main loop report this individual song as failed.
                    continue
                queued[i] = submit_render(song, parts)

        prefetch(0)
        for index, (song, parts) in enumerate(candidates):
            check()
            song_uploaded_bytes = 0
            prefetch(index)
            code = str(song.get('code') or song['id'])
            emit('กำลังตรวจเพลง ' + code, completed, total)
            try:
                from .web_assets import signature, safe_stem
                sig = signature(parts, soundfont, settings)
                web_id = safe_stem(code, sig)
                previous_row = old_rows.get(web_id)
                if previous_row and previous_row.get('sourceSignature') == sig and inventory.valid(previous_row):
                    result_rows[web_id] = previous_row; reused += 1
                    completed += 1; emit('ข้ามเพลงเดิม '+code, completed, total)
                    report_storage(force=completed==total)
                    continue
                resumed = recover_uploaded_row(song, web_id, sig)
                if resumed is None:
                    resumed = recover_prior_upload_with_local_proof(song, web_id, sig)
                if resumed is not None:
                    replace_local_version(web_id, song)
                    result_rows[web_id] = resumed
                    record_upsert(resumed)
                    # A previous version may have uploaded both files before
                    # saving its journal/catalog. Persist the recovered mapping.
                    journal[web_id] = {'state':'uploaded', 'signature':sig,
                                       'audioId':resumed['audio']['fileId'],
                                       'lyricsId':resumed['lyrics']['fileId'], 'row':resumed}
                    reused += 1
                    completed += 1
                    publish_ready_batch()
                    emit('กู้คืนเพลงที่อัปโหลดครบแล้ว '+code, completed, total)
                    report_storage(force=completed==total)
                    continue
                emit('กำลังแปลงเพลง ' + code, completed, total)
                future = queued.pop(index, None)
                identity, m4a, lyr, duration = (future.result() if future is not None else
                                                submit_render(song, parts).result())
                # Conversion can already continue as this song uploads.
                prefetch(index + 1)
                if identity != sig or signature(parts, soundfont, settings) != sig:
                    raise ValueError('ไฟล์ต้นฉบับหรือ SoundFont เปลี่ยนระหว่างแปลงเพลง')
                folder = re_bucket(code)
                # Create folders on the main thread, avoiding concurrent folder
                # creation races and duplicate folders on a new Drive library.
                audio_parent = bucket_parent('audio', code)
                lyrics_parent = bucket_parent('lyrics', code)
                # If this source appears twice with the same content identity,
                # finish prior tasks before another worker touches that path.
                while any(item[1] == web_id for item in in_flight):
                    finalize_oldest_upload()
                check()
                emit('กำลังอัปโหลด M4A และ Lyrics JSON ' + code, completed, total)
                task = upload_executor.submit(upload_verified_pair, audio_parent,
                                              lyrics_parent, m4a, lyr)
                in_flight.append((song, web_id, sig, duration, m4a, lyr, task))
                if len(in_flight) >= upload_workers:
                    finalize_oldest_upload()
                # The upload remains asynchronous while the next song renders.
                continue
            except Exception as exc:
                if isinstance(exc, CatalogPublishError) or (cancel is not None and cancel.is_set()):
                    raise
                failures.append((code, str(exc)))
            completed += 1
            report_storage(song_uploaded_bytes, force=completed == total)
            # Publishing is outside the per-song error handler: a Drive
            # catalog failure is fatal for the batch, not a failed media item.
            publish_ready_batch()
            emit('เตรียมไฟล์แล้ว '+str(completed)+'/'+str(total), completed, total)
        # The final catalog may include only pairs that completed verification.
        while in_flight:
            finalize_oldest_upload()
    check()
    # Original names with sourceId previously published by THIS local library
    # but now marked hidden/excluded are removed from view (files remain).
    import sqlite3
    from contextlib import closing
    # sqlite3.Connection.__exit__ commits but does not close the handle.
    # On Windows an unclosed connection prevents removal of songs.sqlite3.
    # A single read snapshot also avoids opening an extra handle per hidden song.
    with closing(sqlite3.connect(db_path, timeout=10)) as db:
        known = {int(song_id): (state, str(code)) for song_id, state, code in
                 db.execute('SELECT id, duplicate_state, code FROM songs')}
    for key, row in list(result_rows.items()):
        source_id = row.get('sourceId')
        local = known.get(source_id)
        if (row.get('libraryId') == library_id and local is not None and
                local[0] in ('manual_hidden', 'excluded', 'deleted', 'moved', 'recycled') and
                local[1] == str(row.get('code'))):
            result_rows.pop(key, None)
    if rejected or failures:
        error_log = Path(cache_dir) / 'errors.log'
        error_log.parent.mkdir(parents=True, exist_ok=True)
        with error_log.open('a', encoding='utf-8') as log:
            log.write('['+datetime.now(timezone.utc).isoformat()+'] Web Sync\n')
            for code, reason in [*rejected, *failures]:
                log.write(str(code).replace('\n',' ') + ': ' + str(reason).replace('\n',' ')[:4000] + '\n')
    if failures:
        emit(str(len(failures))+' เพลงผิดพลาด; จะลงฐานเฉพาะเพลงที่ตรวจครบ',completed,total)
    if not result_rows and failures:
        # Do not create an empty active catalog when every upload failed.
        raise RuntimeError('ไม่มีเพลงพร้อมเผยแพร่; อัปโหลดล้มเหลวทั้งหมด Catalog เดิมไม่เปลี่ยน')
    check()
    # Publish the final complete snapshot, applying visibility changes only
    # here. It also compacts all deltas so the next run reads just one catalog.
    def attach_integrity(result):
        if not verify_integrity:
            return result
        emit('กำลังตรวจความถูกต้องของเพลงและฐานเว็บทั้งหมด…',completed,total)
        inspection=verify_and_repair_web_catalog(drive,root,db_path,song_roots,
            native,settings,soundfont,cache_dir,ffmpeg=ffmpeg,progress=emit,
            cancel=cancel,renderer_factory=renderer_factory,workers=workers,
            song_types=song_types)
        _json_file(Path(cache_dir)/'integrity-report.json',inspection)
        if inspection.get('generation'):
            result['generation']=inspection['generation']
        result['integrity_checked']=inspection['checked']
        result['integrity_valid']=inspection['valid']
        result['integrity_repaired']=inspection['repaired']
        result['integrity_unresolved']=len(inspection['issues'])
        if inspection['issues']:
            result['failed'].extend((str(row.get('code') or row.get('webSongId')),
                'ตรวจพบไฟล์บน Drive ไม่ครบหรือ MD5 ไม่ตรง • ไม่มีต้นฉบับที่ซ่อมได้ในรอบนี้')
                for row in inspection['issues'])
            emit('ตรวจครบแล้ว แต่ยังมี '+str(len(inspection['issues']))+' เพลงต้องซ่อม',completed,total)
        else:
            emit('ตรวจและซ่อมเสร็จ • '+str(inspection['valid'])+'/'+str(inspection['checked'])+
                 ' เพลงในฐานเว็บมีไฟล์ครบและ MD5 ตรง',completed,total)
        return result

    if current is not None and result_rows == published_rows and not current.get('deltaFileIds'):
        emit('ชุดเพลงทั้งหมดอยู่บนเว็บไซต์แล้ว' if batches_published else
             'ฐานเว็บปัจจุบันตรงกับเพลงที่ตรวจแล้ว ไม่ต้องอัปโหลดฐานซ้ำ', total, total)
        return attach_integrity({'generation':current['generation'], 'total':len(result_rows), 'scanned':total,
                'reused':reused, 'uploaded_files':uploaded, 'failed':failures,
                'skipped':rejected, 'drive_root':root, 'catalog_unchanged':batches_published == 0,
                'batches_published':batches_published})
    emit('กำลังรวมฐานเพลงและเผยแพร่ Catalog ฉบับสมบูรณ์…', total, total)
    generation = _publish(drive, root, current_file, current, list(result_rows.values()), cache_dir)
    emit('เผยแพร่ฐานเพลงรุ่น '+generation+' • Catalog ฉบับสมบูรณ์พร้อมเล่นแล้ว', total, total)
    return attach_integrity({'generation':generation, 'total':len(result_rows), 'scanned':total,
            'reused':reused, 'uploaded_files':uploaded, 'failed':failures,
            'skipped':rejected, 'drive_root':root, 'batches_published':batches_published})


def re_bucket(code):
    first = str(code)[:1].upper()
    return first if first.isascii() and first.isalnum() else '_'
