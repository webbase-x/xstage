"""Persistent file signatures and exact-content preflight before metadata parsing."""
import hashlib
import json
import sqlite3
import stat as stat_module
from collections import OrderedDict
from pathlib import Path
from .ingest import Inspector
from .duplicates import bundle, fingerprint
from .library import canonical, normalize, SearchCancelled
from .file_signature import change_time

# Bump only when metadata-reading rules change, not on every UI release.
READER_REVISION = 'metadata-4'


def encode(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'))


def metadata_complete(row):
    return bool(row and row.get('playable') and str(row.get('title','')).strip()
                and row.get('title')!=row.get('code') and str(row.get('artist','')).strip())


def signature(path, inspector=None):
    kind,parts=bundle(path,inspector)
    stamps=[];sizes=[]
    for role,file in sorted(parts.items()):
        stat=file.stat()
        if not stat_module.S_ISREG(stat.st_mode):raise ValueError('ไม่ใช่ไฟล์เพลง: '+str(file))
        stamps.append((role,canonical(file),stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns,stat.st_dev,stat.st_ino,change_time(file,stat)))
        sizes.append((role,stat.st_size))
    return encode((kind,stamps)),encode((kind,sizes))


def trusted_stamp(stamp):
    try:return all(part[-1] is not None for part in json.loads(stamp)[1])
    except (TypeError,ValueError,IndexError):return False


def content_key(path,inspector,cancelled=None,events=None):
    value,_,_=fingerprint(path,cancelled,events,validate=False,inspector=inspector)
    return hashlib.sha256(encode(value).encode('utf-8')).hexdigest()


class IncrementalIndex:
    def __init__(self,library,events=None,cancelled=None,protected=(),force=False):
        self.library=library;self.events=events;self.cancelled=cancelled
        self.protected=set(protected);self.force=force;self.inspector=Inspector()
        self.path=library.path.with_name(library.path.stem+'-index-cache.sqlite3')
        self.db=sqlite3.connect(self.path)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=NORMAL')
        self.db.execute('''CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, song_id INTEGER,
            stamp TEXT NOT NULL, size_key TEXT NOT NULL, content_key TEXT, reader TEXT NOT NULL,
            complete INTEGER NOT NULL DEFAULT 0)''')
        self.db.execute('CREATE INDEX IF NOT EXISTS cache_content ON files(content_key)')
        self.db.execute('CREATE INDEX IF NOT EXISTS cache_size ON files(size_key)')
        self.db.execute('CREATE TABLE IF NOT EXISTS catalogs(path TEXT PRIMARY KEY, stamp TEXT NOT NULL)')
        self.db.commit()
        self.read=sqlite3.connect(library.path,isolation_level=None)
        self.read.row_factory=sqlite3.Row
        self.db.execute('ATTACH DATABASE ? AS library',(str(library.path.resolve()),))
        self.counts=dict(unchanged=0,added=0,updated=0,duplicates=0,failed=0)
        self.touched=False
        self.keepers=OrderedDict()
    def close(self):
        self.db.commit();self.read.close();self.db.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def emit(self,**event):
        if self.events:self.events(event)
    def check_cancel(self):
        if self.cancelled and self.cancelled.is_set():raise SearchCancelled()
    def row(self,path=None,song_id=None):
        found=self.read.execute('SELECT * FROM songs WHERE '+('path=?' if path is not None else 'id=?'),
                                (path if path is not None else song_id,)).fetchone()
        return dict(found) if found else None
    def cached(self,path):
        row=self.db.execute('SELECT * FROM files WHERE path=?',(path,)).fetchone()
        return dict(row) if row else None
    def remember(self,path,row,stamp,size,key=None,reader=None):
        self.db.execute('INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?)',
            (path,row['id'],stamp,size,key,reader or '',int(metadata_complete(row))))
    def inventory(self):
        """Seed missing old records with stat data only; no full-library file reads."""
        sql="""FROM library.songs s LEFT JOIN files c ON c.path=s.path
            WHERE (c.path IS NULL OR c.song_id<>s.id) AND s.duplicate_state NOT IN ('moved','recycled','deleted','excluded')"""
        total=self.db.execute('SELECT count(*) '+sql).fetchone()[0]
        if not total:return
        self.emit(type='phase',phase='เตรียมดัชนีไฟล์เดิมครั้งแรก',total=total)
        last=done=0
        while True:
            self.check_cancel()
            rows=self.db.execute('SELECT s.* '+sql+' AND s.id>? ORDER BY s.id LIMIT 100',(last,)).fetchall()
            if not rows:break
            for data in rows:
                self.check_cancel();row=dict(data)
                try:stamp,size=signature(row['path'],self.inspector)
                except (OSError,ValueError):stamp=size=''
                self.remember(row['path'],row,stamp,size)
                done+=1;last=row['id']
                self.emit(type='progress',done=done,total=total,path=row['path'])
            self.db.commit()
    def rank(self,row):
        return (not row.get('duplicate_preferred'),row['id'] not in self.protected,
                not row.get('user_edited'),not row.get('favorite'),row['id'])
    def valid_candidate(self,cache,key,size,rehash=None):
        row=self.row(song_id=cache['song_id'])
        if not row or row['path']!=cache['path'] or row['duplicate_state'] in ('moved','recycled','deleted','excluded'):return None
        try:
            stamp,current_size=signature(row['path'],self.inspector)
            if stamp!=cache['stamp'] or current_size!=size:
                self.detach_changed(row,cache.get('content_key'),'')
                self.db.execute('UPDATE files SET content_key=NULL,complete=0 WHERE path=?',(cache['path'],))
                return None
            should_hash=(self.force if rehash is None else rehash) or not trusted_stamp(stamp)
            if should_hash:
                actual=content_key(row['path'],self.inspector,self.cancelled,self.events)
                if actual!=key:
                    self.remember(row['path'],row,stamp,current_size,actual,'')
                    return None
            return row
        except (OSError,ValueError,EOFError):return None
    def cache_keeper(self,key,row):
        self.keepers[key]=row
        self.keepers.move_to_end(key)
        while len(self.keepers)>128:self.keepers.popitem(last=False)
        return row
    def find_keeper(self,path,key,size):
        previous=self.keepers.get(key)
        if previous and previous['path']!=path:
            cached=self.cached(previous['path'])
            row=self.valid_candidate(cached,key,size,rehash=False) if cached else None
            if row:return self.cache_keeper(key,row)
            self.keepers.pop(key,None)
        best=None;last=0
        while True:
            batch=self.db.execute('SELECT * FROM files WHERE content_key=? AND path<>? AND song_id>? ORDER BY song_id LIMIT 100',
                                  (key,path,last)).fetchall()
            if not batch:break
            for data in batch:
                self.check_cancel();cache=dict(data);last=cache['song_id']
                row=self.valid_candidate(cache,key,size)
                if row and (best is None or self.rank(row)<self.rank(best)):best=row
        if best:return self.cache_keeper(key,best)
        # First use of old records: hash only matching-size candidates, in bounded batches.
        last=0
        while True:
            candidates=self.db.execute('SELECT * FROM files WHERE size_key=? AND content_key IS NULL '
                'AND path<>? AND song_id>? ORDER BY song_id LIMIT 100',(size,path,last)).fetchall()
            if not candidates:break
            for data in candidates:
                self.check_cancel();cache=dict(data);last=cache['song_id']
                row=self.row(song_id=cache['song_id'])
                if not row or row['path']!=cache['path'] or row['duplicate_state'] in ('moved','recycled','deleted','excluded'):continue
                try:
                    stamp,current_size=signature(row['path'],self.inspector)
                    if current_size!=size:
                        self.remember(row['path'],row,stamp,current_size,None,'')
                        continue
                    self.emit(type='progress',path=row['path'])
                    hashed=content_key(row['path'],self.inspector,self.cancelled,self.events)
                    self.remember(row['path'],row,stamp,current_size,hashed,cache['reader'] if stamp==cache['stamp'] else '')
                    if hashed==key:
                        self.db.commit()
                        return self.cache_keeper(key,row)
                except (OSError,ValueError,EOFError):continue
            self.db.commit()
        return None
    def detach_changed(self,row,old_key,new_key):
        if not row or not old_key or old_key==new_key:return
        replacement=None
        protected=sorted(self.protected)[:500]
        priority=('CASE WHEN id IN ('+','.join('?' for _ in protected)+') THEN 0 ELSE 1 END,') if protected else ''
        cursor=self.read.execute("SELECT * FROM songs WHERE duplicate_of=? AND duplicate_state='kept' ORDER BY duplicate_preferred DESC,"
            +priority+'user_edited DESC,favorite DESC,id',(row['id'],*protected))
        try:
            for data in cursor:
                self.check_cancel();copy=dict(data);cache=self.cached(copy['path'])
                if not cache or cache.get('content_key')!=old_key:continue
                try:
                    stamp,_=signature(copy['path'],self.inspector)
                    if stamp!=cache['stamp']:continue
                    self.inspector.inspect(copy['path'])
                    if content_key(copy['path'],self.inspector,self.cancelled)!=old_key:continue
                    replacement=copy;break
                except (OSError,ValueError,EOFError):continue
        finally:cursor.close()
        with self.library.connect() as db:
            if replacement:
                db.execute("UPDATE songs SET duplicate_of=? WHERE duplicate_of=? AND id<>?",(replacement['id'],row['id'],replacement['id']))
                db.execute("UPDATE songs SET duplicate_of=0,duplicate_state='' WHERE id=?",(replacement['id'],))
            else:
                db.execute("UPDATE songs SET duplicate_of=0,duplicate_state='' WHERE duplicate_of=? AND duplicate_state='kept'",(row['id'],))
        self.touched=True;self.keepers.pop(old_key,None)
    def parse(self,path):
        errors=[]
        ids=self.library.add_files([path],self.inspector,errors,self.cancelled)
        if not ids:self.check_cancel()
        return (self.row(song_id=ids[0]) if ids else None),errors
    def ensure_keeper(self,row):
        cache=self.cached(row['path'])
        if not cache or cache['reader']!=READER_REVISION or not metadata_complete(row):
            row,errors=self.parse(row['path'])
            if not row:return None
            stamp,size=signature(row['path'],self.inspector)
            self.remember(row['path'],row,stamp,size,content_key(row['path'],self.inspector,self.cancelled),READER_REVISION)
        return row
    def link(self,row,keeper):
        """An exact match is a *report candidate*, not permission to hide it.

        Keep the public method for older indexers.  User-requested visibility
        changes are performed only by duplicate_actions.
        """
        return self.row(song_id=row['id'])

    def alias(self,path,old,keeper):
        # Clone known metadata after exact-content matching; no second media parse.
        if old:
            merged=dict(keeper)
            if old['user_edited']:
                for name in ('code','title','artist'):merged[name]=old[name]
            merged['search']=normalize(' '.join(str(merged.get(name,'')) for name in ('code','title','artist','first_lyric','rhythm')))
            columns=('code','title','artist','kind','search','format','first_lyric','rhythm','key_signature','bpm','source_catalog')
            with self.library.connect() as db:
                db.execute('UPDATE songs SET '+','.join(name+'=?' for name in columns)+',playable=1 WHERE id=?',
                           [merged.get(name,'') for name in columns]+[old['id']])
            row=self.row(song_id=old['id'])
        else:
            columns=('path','code','title','artist','kind','search','format','playable','first_lyric','rhythm','key_signature','bpm','source_catalog','duplicate_of','duplicate_state')
            values=[path if key=='path' else 0 if key=='duplicate_of' else '' if key=='duplicate_state' else keeper.get(key,'') for key in columns]
            with self.library.connect() as db:
                db.execute('INSERT INTO songs('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',values)
                row=dict(db.execute('SELECT * FROM songs WHERE path=?',(path,)).fetchone())
            if not keeper['duplicate_of']:
                self.touched=True
                return row
        return self.link(row,keeper)
    def merge_missing(self,keeper,row):
        if keeper['user_edited']:return keeper
        title=keeper['title'];artist=keeper['artist'];code=keeper['code']
        if (not title or title==code or title==Path(keeper['path']).stem) and row['title'] and row['title']!=row['code']:
            title=row['title']
        artist=artist or row['artist'];code=code or row['code']
        with self.library.connect() as db:
            db.execute('UPDATE songs SET code=?,title=?,artist=?,search=? WHERE id=?',
                (code,title,artist,normalize(' '.join(str(x) for x in (code,title,artist,keeper['first_lyric'],keeper['rhythm']))),keeper['id']))
        return self.row(song_id=keeper['id'])
    def process(self,path):
        self.check_cancel();path=canonical(Path(path));old=self.row(path=path);cache=self.cached(path)
        self.emit(type='progress',path=path)
        try:stamp,size=signature(path,self.inspector)
        except (OSError,ValueError) as error:
            row,errors=self.parse(path)
            self.counts['updated' if old else 'added']+=bool(row)
            self.counts['failed']+=not bool(row)
            self.db.execute('DELETE FROM files WHERE path=?',(path,))
            return row,'อัปเดต' if old and row else 'เพิ่มใหม่' if row else 'อ่านไม่ได้',errors or [str(error)]
        unchanged=(not self.force and old and cache and cache['stamp']==stamp and cache['reader']==READER_REVISION
                   and cache['complete'] and metadata_complete(old) and trusted_stamp(stamp))
        if unchanged:
            if old['duplicate_of']:
                keeper=self.row(song_id=old['duplicate_of'])
                parent_cache=self.cached(keeper['path']) if keeper else None
                available=bool(parent_cache and parent_cache.get('content_key')==cache.get('content_key')
                    and self.valid_candidate(parent_cache,cache['content_key'],size,rehash=False))
                if not available:unchanged=False
            if unchanged:
                self.counts['unchanged']+=1
                return old,'เดิมไม่เปลี่ยน',[]
        try:
            if not self.force and cache and cache['stamp']==stamp and cache.get('content_key') and trusted_stamp(stamp):
                key=cache['content_key']
            else:
                key=content_key(path,self.inspector,self.cancelled,self.events)
        except (OSError,ValueError,EOFError) as error:
            row,errors=self.parse(path)
            self.counts['updated' if old else 'added']+=bool(row)
            self.counts['failed']+=not bool(row)
            self.db.execute('DELETE FROM files WHERE path=?',(path,))
            return row,'อัปเดต' if old and row else 'เพิ่มใหม่' if row else 'อ่านไม่ได้',errors or [str(error)]
        if signature(path,self.inspector)[0]!=stamp:
            self.detach_changed(old,cache.get('content_key') if cache else None,'')
            row,errors=self.parse(path)
            self.db.execute('DELETE FROM files WHERE path=?',(path,))
            self.counts['updated' if old else 'added']+=bool(row)
            self.counts['failed']+=not bool(row)
            return row,'อัปเดต' if old and row else 'เพิ่มใหม่' if row else 'อ่านไม่ได้',errors+['ไฟล์เปลี่ยนระหว่างตรวจ ไม่เก็บผลแคช และจะตรวจใหม่รอบถัดไป']
        if (not self.force and old and cache and cache.get('content_key')==key
                and cache['reader']==READER_REVISION and metadata_complete(old) and not old['duplicate_of']):
            self.remember(path,old,stamp,size,key,READER_REVISION)
            self.counts['unchanged']+=1
            return old,'เดิมไม่เปลี่ยน',['ตรวจเนื้อหาแล้วเหมือนเดิม แม้ข้อมูลเวลาไฟล์เปลี่ยน']
        self.detach_changed(old,cache.get('content_key') if cache else None,key)
        candidate=self.find_keeper(path,key,size)
        prefer_old=bool(old and candidate and self.rank(old)<=self.rank(candidate))
        if candidate and not prefer_old:
            keeper=self.ensure_keeper(candidate)
            if keeper and metadata_complete(keeper):
                row=self.alias(path,old,keeper)
                self.remember(path,row,stamp,size,key,READER_REVISION)
                self.cache_keeper(key,keeper)
                self.counts['duplicates']+=1
                return row,'ซ้ำกับรายการเดิม',[f"เก็บรายการหลัก #{keeper['id']} · ไม่ย้ายหรือลบไฟล์"]
        row,errors=self.parse(path)
        if not row:
            self.counts['failed']+=1
            self.db.execute('DELETE FROM files WHERE path=?',(path,))
            return None,'อ่านไม่ได้',errors
        if signature(path,self.inspector)[0]!=stamp:
            self.db.execute('DELETE FROM files WHERE path=?',(path,))
            errors.append('ไฟล์เปลี่ยนระหว่างอ่าน จะตรวจใหม่ในรอบถัดไป')
            self.counts['updated' if old else 'added']+=1
            return row,'อัปเดต' if old else 'เพิ่มใหม่',errors
        self.remember(path,row,stamp,size,key,READER_REVISION)
        if candidate:
            if prefer_old:
                self.link(candidate,row)
                self.cache_keeper(key,row)
                self.counts['updated']+=1
                result='อัปเดต'
            else:
                candidate=self.merge_missing(candidate,row)
                candidate_stamp,candidate_size=signature(candidate['path'],self.inspector)
                self.remember(candidate['path'],candidate,candidate_stamp,candidate_size,key,READER_REVISION)
                self.link(row,candidate)
                self.cache_keeper(key,candidate)
                self.counts['duplicates']+=1
                result='ซ้ำกับรายการเดิม'
        else:
            self.counts['updated' if old else 'added']+=1
            result='อัปเดต' if old else 'เพิ่มใหม่'
        return self.row(song_id=row['id']),result,errors

    def run(self,plan,progress=None):
        try:self.inventory()
        except SearchCancelled:return 0,plan.omitted,plan.errors
        # Existing files first: updates cannot be displaced by newly encountered copies.
        self.db.commit()
        plan.db.execute('ATTACH DATABASE ? AS cached_index',(str(self.path.resolve()),))
        plan.db.execute('UPDATE files SET existing=1 WHERE path IN (SELECT path FROM cached_index.files WHERE song_id>0)')
        plan.db.commit()
        plan.db.execute('DETACH DATABASE cached_index')
        total=plan.count();self.emit(type='phase',phase='ตรวจทั้งคลัง / อ่านรายละเอียดใหม่' if self.force else 'ตรวจเดิม / ตรวจซ้ำก่อนนำเข้า',total=total,target=total)
        self.emit(type='progress',incremental=True,**self.counts)
        processed=accepted=0
        cursor=plan.db.execute('SELECT path FROM files ORDER BY existing DESC,path')
        try:
            while True:
                self.check_cancel();batch=cursor.fetchmany(100)
                if not batch:break
                for data in batch:
                    self.check_cancel()
                    row,result,errors=self.process(data[0]);processed+=1
                    ok=row is not None;accepted+=ok;plan.errors.extend(errors)
                    self.emit(type='item',ok=ok,result=result,path=data[0],code=row.get('code','') if row else '',
                              title=row.get('title',Path(data[0]).name) if row else Path(data[0]).name,
                              artist=row.get('artist','') if row else '',note='; '.join(errors),category=result)
                    if progress:progress(processed)
                self.db.commit()
        except SearchCancelled:pass
        self.emit(type='progress',done=processed,total=total,**self.counts)
        return accepted,plan.omitted,plan.errors
