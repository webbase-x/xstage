"""Explicit import policies and verified, no-overwrite managed song copies."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid
from .library import canonical,normalize,SUPPORTED,MIDI_EXT,VIDEO_EXT,SearchCancelled,write_json
from .ingest import Inspector
from .duplicates import bundle,digest
from .incremental import IncrementalIndex,signature,content_key,READER_REVISION,trusted_stamp
from .name_duplicates import NameIndex


def category(path):
    ext=Path(path).suffix.lower()
    return 'MIDI' if ext in MIDI_EXT else 'Video' if ext in VIDEO_EXT else 'Audio'


def stopped(cancelled):
    if cancelled and cancelled.is_set():raise SearchCancelled()


def safe_directory(path):
    path=Path(path)
    for item in (path,*path.parents):
        if item.is_symlink() or getattr(item,'is_junction',lambda:False)():raise ValueError('ไม่คัดลอกผ่านโฟลเดอร์ลิงก์: '+str(item))


def copy_song(source,songs_root,cancelled=None,events=None,avoid_paths=()):
    """Preserve available NCN/LRC/SNF companions; publish only verified files."""
    source=Path(source);songs_root=Path(songs_root).absolute();safe_directory(songs_root)
    inspector=Inspector();inspector.inspect(source)
    kind,parts=bundle(source,inspector)
    for file in parts.values():safe_directory(file.parent)
    expected={role:digest(file,cancelled,events) for role,file in parts.items()}
    folder=songs_root/category(source);safe_directory(folder);folder.mkdir(parents=True,exist_ok=True)
    role_ext={'lyrics':'.lyr','cursor':'.cur','lrc':'.lrc','snf':'.snf'}
    def destinations(number):
        stem=source.stem if number==1 else source.stem+' ('+str(number)+')'
        media=folder/(stem+source.suffix.lower())
        return media,{role:media if role=='media' else folder/(stem+role_ext[role]) for role in parts}
    for number in range(1,10001):
        stopped(cancelled);media,targets=destinations(number)
        reserved=[media,*(media.with_suffix(ext) for ext in role_ext.values())]
        if any(p.exists() or p.is_symlink() for p in reserved):
            if all(p.is_file() and not p.is_symlink() for p in targets.values()):
                try:
                    _,existing=bundle(media,Inspector())
                    if canonical(media) not in avoid_paths and set(existing)==set(parts) and all(digest(existing[k],cancelled)==expected[k] for k in parts):return media,False
                except (OSError,ValueError):pass
            continue
        break
    else:raise ValueError('ชื่อไฟล์ชนกันมากเกินไป')
    stage=folder/('.xstage-import-'+uuid.uuid4().hex);stage.mkdir();published=[]
    try:
        for role,file in parts.items():
            stopped(cancelled);target=stage/targets[role].name
            h=hashlib.sha256()
            with file.open('rb') as incoming,target.open('xb') as outgoing:
                while True:
                    stopped(cancelled);block=incoming.read(1024*1024)
                    if not block:break
                    outgoing.write(block);h.update(block)
                outgoing.flush();os.fsync(outgoing.fileno())
            if h.hexdigest()!=expected[role]:raise ValueError('ไฟล์ต้นทางเปลี่ยนระหว่างคัดลอก')
        for role,target in targets.items():
            stopped(cancelled)
            # Hard-link publication is atomic, exclusive and on the same volume.
            os.link(stage/target.name,target)
            stat=target.stat();published.append((target,stat.st_dev,stat.st_ino,expected[role]))
        if any(digest(target,cancelled)!=expected[role] for role,target in targets.items()):raise ValueError('ตรวจไฟล์ที่คัดลอกไม่ผ่าน')
        return media,True
    except BaseException:
        for target,dev,ino,key in published:
            try:
                stat=target.stat()
                if (stat.st_dev,stat.st_ino)==(dev,ino) and digest(target)==key:target.unlink()
            except (OSError,ValueError):pass
        raise
    finally:
        # Only the private staging directory created above is removed.
        if stage.resolve().is_relative_to(songs_root.resolve()):shutil.rmtree(stage,ignore_errors=True)


class PolicyRejected(ValueError):
    pass


class ImportSession:
    def __init__(self,library,songs_root,copy_files=False,cancelled=None,events=None,decide=None,replaced=None,force=False,protected=(),strict=True):
        if copy_files:
            raise PolicyRejected('v0.9.43 ไม่คัดลอกเพลงเข้า Songs ให้วางเพลงด้วยตนเองก่อนนำเข้า')
        self.library=library;self.songs_root=Path(songs_root);self.copy_files=False;self.cancelled=cancelled;self.events=events;self.decide=decide;self.replaced=replaced;self.strict=strict
        self.names=NameIndex(include_key=strict);self.index=IncrementalIndex(library,events,cancelled,protected,force)
        self.inspector=Inspector();self.notes=[];self.selected_id=None
        self.stats=dict(added=0,updated=0,replaced=0,reused=0,copied=0,skipped=0,failed=0)
        self.names.db.execute('CREATE TABLE managed(path TEXT PRIMARY KEY,size TEXT)');self.names.db.execute('CREATE INDEX managed_size ON managed(size)')
        self.index.db.execute('CREATE TABLE IF NOT EXISTS quality(path TEXT PRIMARY KEY,stamp TEXT,metadata TEXT,revision TEXT,result TEXT)');self.index.db.commit()
    def close(self):
        try:self.index.close()
        finally:self.names.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def prepare(self):
        if self.events:self.events(dict(type='phase',phase='ตรวจชื่อ นักร้อง คีย์ และไฟล์เดิม',total=None))
        self.names.refresh(self.index.read,lambda:bool(self.cancelled and self.cancelled.is_set()))
        self.index.inventory()
        if self.copy_files and self.songs_root.is_dir():
            safe_directory(self.songs_root)
            for root,dirs,files in os.walk(self.songs_root,followlinks=False):
                stopped(self.cancelled);safe_directory(root)
                dirs[:]=[n for n in dirs if not n.startswith('.') and not (Path(root)/n).is_symlink() and not getattr(Path(root)/n,'is_junction',lambda:False)()]
                for name in files:
                    p=Path(root)/name
                    if p.suffix.lower() not in SUPPORTED:continue
                    try:
                        _,size=signature(p,self.inspector)
                        self.names.db.execute('INSERT OR IGNORE INTO managed VALUES (?,?)',(canonical(p),size))
                    except (OSError,ValueError):pass
            self.names.db.commit()
    def quality(self,path,record):
        from .song_policy import assess,REVISION
        meta=json.dumps([record.get(k,'') for k in ('title','artist','key_signature','user_edited')],ensure_ascii=False)
        try:stamp,_=signature(path,Inspector())
        except (OSError,ValueError):return assess(path,record,self.cancelled,self.inspector)
        reliable=trusted_stamp(stamp)
        cached=self.index.db.execute('SELECT * FROM quality WHERE path=?',(canonical(Path(path)),)).fetchone()
        if cached and not self.index.force and reliable and cached['stamp']==stamp and cached['metadata']==meta and cached['revision']==REVISION:
            try:
                value=json.loads(cached['result'])
                if isinstance(value,dict) and value.get('status')=='valid' and value.get('_validated_stamp')==stamp:return value
            except (ValueError,TypeError):pass
        before_key=None if reliable else content_key(path,Inspector(),self.cancelled)
        value=assess(path,record,self.cancelled,self.inspector)
        after,_=signature(path,Inspector())
        if stamp!=after:raise PolicyRejected('ไฟล์หรือส่วนประกอบเปลี่ยนระหว่างตรวจ จึงไม่รับผลตรวจนี้')
        if before_key is not None and content_key(path,Inspector(),self.cancelled)!=before_key:raise PolicyRejected('เนื้อหาเปลี่ยนระหว่างตรวจ จึงไม่รับผลตรวจนี้')
        value['_validated_stamp']=stamp
        self.index.db.execute('INSERT OR REPLACE INTO quality VALUES (?,?,?,?,?)',(canonical(Path(path)),stamp,meta,REVISION,json.dumps(value,ensure_ascii=False)));self.index.db.commit()
        return value
    def require_quality(self,path,record):
        if not self.strict:return None
        result=self.quality(path,record)
        if result['status']=='valid':
            for field,value in result.get('metadata',{}).items():
                if not record.get(field):record[field]=value
        if result['status']!='valid':raise PolicyRejected(('ไม่สมบูรณ์: ' if result['status']=='invalid' else 'ต้องตรวจเพิ่ม: ')+'; '.join(result['reasons']))
        return result
    def exact(self,key,size):
        rows=self.index.db.execute("SELECT c.* FROM files c JOIN library.songs s ON s.id=c.song_id WHERE c.size_key=? AND s.duplicate_of=0 AND s.duplicate_state NOT IN ('moved','recycled','deleted') ORDER BY s.id",(size,)).fetchall()
        for data in rows:
            stopped(self.cancelled);cache=dict(data);row=self.index.row(song_id=cache['song_id'])
            if not row or row['path']!=cache['path']:continue
            try:
                stamp,current_size=signature(row['path'],self.inspector)
                if current_size!=size:continue
                actual=cache['content_key'] if stamp==cache['stamp'] and trusted_stamp(stamp) and cache['content_key'] else content_key(row['path'],self.inspector,self.cancelled,self.events)
                self.index.remember(row['path'],row,stamp,current_size,actual,cache['reader'])
                self.index.db.commit()
                if actual==key and (not self.strict or self.quality(row['path'],row)['status']=='valid'):return row
            except (OSError,ValueError):continue
        self.index.db.commit();return None
    def same(self,record,exclude=None):
        for sid in self.names.candidates(record.get('title'),record.get('artist'),record.get('key_signature')):
            if sid==exclude:continue
            row=self.library.get(sid)
            try:
                if row and (not self.strict or self.quality(row['path'],row)['status']=='valid'):return row
            except (OSError,ValueError):continue
        return None
    def managed_match(self,key,size,record):
        from .name_duplicates import identity
        wanted=identity(record.get('title'),record.get('artist'),record.get('key_signature'))
        for row in self.names.db.execute('SELECT path FROM managed WHERE size=? ORDER BY path',(size,)):
            stopped(self.cancelled)
            try:
                safe_directory(Path(row[0]).parent)
                owner=self.index.row(path=row[0])
                if self.strict and owner and identity(owner.get('title'),owner.get('artist'),owner.get('key_signature'))!=wanted:continue
                if content_key(row[0],Inspector(),self.cancelled)==key:return Path(row[0])
            except (OSError,ValueError):pass
        return None
    def remember(self,row):
        self.inspector.listing.cache_clear();self.names.add(row)
        stamp,size=signature(row['path'],self.inspector);key=content_key(row['path'],self.inspector,self.cancelled)
        self.index.remember(row['path'],row,stamp,size,key,READER_REVISION);self.index.db.commit()
        self.names.db.execute('INSERT OR REPLACE INTO managed VALUES (?,?)',(row['path'],size));self.names.db.commit()
    def refresh_current(self,path,record,warnings,current,key):
        self.index.db.commit();previous=self.index.cached(current['path'])
        if previous and previous.get('content_key')!=key:
            self.index.detach_changed(current,previous.get('content_key'),key)
            self.names.version=None;self.names.refresh(self.index.read)
        cached=type('Inspected',(),{'inspect':lambda _self,_path:(copy.deepcopy(record),list(warnings))})()
        self.library.add_files([path],inspector=cached)
        row=self.library.get(current['id']);self.remember(row);self.stats['updated']+=1
        # Indexing must never hide a candidate automatically. The slow,
        # explicit duplicate review runs after users can search the catalog.
        self.selected_id=self.selected_id or (row['duplicate_of'] or row['id'])
        return row,'อัปเดต'
    def import_one(self,path,single=False,hint=None):
        from .name_duplicates import identity
        stopped(self.cancelled);path=Path(path)
        if path.is_symlink():raise PolicyRejected('ต้องตรวจเพิ่ม: ไม่เพิ่มเพลงผ่าน symbolic link')
        current=self.index.row(path=canonical(path))
        if current and current['duplicate_state'] in ('deleted','moved','recycled','excluded'):
            raise PolicyRejected('รายการนี้เคยถูกนำออกจากฐาน ต้องคืนรายการอย่างชัดเจนก่อนนำเข้า')
        if current and self.strict and current['duplicate_state']=='deleted' and not single:
            kept=self.library.get(current['duplicate_of']) if current['duplicate_of'] else None
            if kept and self.quality(kept['path'],kept)['status']=='valid':return kept,'ซ้ำรายการที่นำออกตามรายงานแล้ว'
            raise PolicyRejected('รายการนี้เคยนำออกตามรายงาน หากต้องการคืนให้เลือกกู้คืนหรือนำเข้าทีละไฟล์')
        if current and not single and not self.strict and (not hint or all(current.get(k)==v for k,v in hint.items() if v not in ('',None))):
            row,result,notes=self.index.process(path);self.index.db.commit();self.notes.extend(notes)
            if row is None:raise ValueError('; '.join(notes) or 'อ่านรายการเดิมไม่สำเร็จ')
            if self.index.touched:self.names.version=None;self.names.refresh(self.index.read);self.index.touched=False
            else:self.names.add(row)
            self.stats['updated']+=1;self.selected_id=self.selected_id or (row['duplicate_of'] or row['id'])
            return row,result
        record,warnings=self.inspector.inspect(path)
        if hint:
            for field,value in hint.items():
                if value not in ('',None):record[field]=value
            record['_rich']=set(record.get('_rich',()))|set(hint)
            if hint.get('source_catalog'):record['_catalog_refresh']=True
        if current:
            if current['user_edited']:
                for field in ('code','title','artist'):record[field]=current[field]
            if current.get('source_catalog') and not record.get('_catalog_refresh'):
                for field in ('code','title','artist','key_signature','first_lyric','bpm'):
                    if current.get(field):record[field]=current[field]
        self.notes.extend('คำเตือน: '+str(path)+': '+note for note in warnings)
        try:quality=self.require_quality(path,record)
        except PolicyRejected as error:
            if current and self.strict and str(error).startswith('ไม่สมบูรณ์:'):
                with self.library.connect() as db:
                    aliases=[dict(row) for row in db.execute("SELECT * FROM songs WHERE duplicate_of=? AND duplicate_state='kept'",(current['id'],))]
                    db.execute("UPDATE songs SET duplicate_of=0,duplicate_state='' WHERE duplicate_of=? AND duplicate_state='kept'",(current['id'],))
                    db.execute("UPDATE songs SET playable=0,duplicate_state='invalid' WHERE id=?",(current['id'],))
                for alias in aliases:self.names.add(dict(alias,duplicate_of=0,duplicate_state=''))
                self.names.add(self.library.get(current['id']))
            raise
        stamp,size=signature(path,Inspector())
        if quality and quality.get('_validated_stamp')!=stamp:raise PolicyRejected('ไฟล์เปลี่ยนหลังตรวจคุณภาพ กรุณานำเข้าใหม่')
        key=content_key(path,Inspector(),self.cancelled,self.events)
        if signature(path,Inspector())[0]!=stamp:raise PolicyRejected('ไฟล์เปลี่ยนระหว่างตรวจเนื้อหา กรุณานำเข้าใหม่')
        # Refreshing an existing path precedes duplicate lookup, including single imports.
        if current:return self.refresh_current(path,record,warnings,current,key)
        same=self.same(record);exact=self.exact(key,size)
        if self.strict and exact and identity(exact.get('title'),exact.get('artist'),exact.get('key_signature'))!=identity(record.get('title'),record.get('artist'),record.get('key_signature')):exact=None
        keeper=same or exact
        exact_for_keeper=bool(exact and keeper and exact['id']==keeper['id'])
        # Batch indexing must never silently remove/hide duplicates before a
        # user reviews their Song Bundles. The path identity is handled above.
        if not single:
            keeper=None
            exact_for_keeper=False
        if keeper:
            choice=self.decide(record,keeper,exact_for_keeper) if single and self.decide else 'existing'
            stopped(self.cancelled)
            if choice=='cancel':raise SearchCancelled()
            if exact_for_keeper or choice=='existing' or (self.strict and choice=='both'):
                self.stats['reused']+=1;self.stats['skipped']+=1;self.selected_id=self.selected_id or keeper['id']
                return keeper,'ซ้ำไฟล์/ชุดเนื้อร้อง' if exact_for_keeper else 'ซ้ำชื่อเพลง + นักร้อง + คีย์' if self.strict else 'ซ้ำชื่อเพลง + นักร้อง'
            if choice not in ('new','both'):raise ValueError('ตัวเลือกเพลงซ้ำไม่ถูกต้อง')
        else:choice='both'
        destination=path;copied=False
        if self.copy_files:
            destination=self.managed_match(key,size,record)
            if destination is None:
                avoid=set()
                if self.strict:
                    prefix=canonical(self.songs_root/category(path)/path.stem)
                    for row in self.index.read.execute("SELECT path,title,artist,key_signature FROM songs WHERE path>=? AND path<? AND duplicate_state NOT IN ('moved','recycled','deleted')",(prefix,prefix+'\uffff')):
                        if identity(row['title'],row['artist'],row['key_signature'])!=identity(record.get('title'),record.get('artist'),record.get('key_signature')):avoid.add(row['path'])
                destination,copied=copy_song(path,self.songs_root,self.cancelled,self.events,avoid)
        if content_key(destination,Inspector(),self.cancelled)!=key:raise ValueError('ไฟล์เปลี่ยนระหว่างนำเข้า กรุณานำเข้าอีกครั้ง')
        self.index.db.commit();target=canonical(destination);record['path']=target;stopped(self.cancelled)
        if keeper and choice=='new':
            with self.library.connect() as db:
                owner=db.execute('SELECT id FROM songs WHERE path=?',(target,)).fetchone()
                if owner and owner['id']!=keeper['id']:raise ValueError('ไฟล์ใหม่อยู่ในคลังอีก ID แล้ว กรุณาเลือกใช้รายการนั้น')
                found=db.execute('SELECT * FROM songs WHERE id=?',(keeper['id'],)).fetchone()
                if found is None:raise ValueError('รายการเดิมเปลี่ยนไปแล้ว กรุณาตรวจใหม่')
                old=dict(found);columns=['path','format','kind','playable','first_lyric','key_signature','bpm','rhythm','source_catalog']
                if not old['user_edited']:columns+=['code','title','artist']
                merged=dict(old,**{k:record.get(k,old.get(k,'')) for k in columns})
                merged['search']=normalize(' '.join(str(merged.get(k,'')) for k in ('code','title','artist','first_lyric','rhythm')));columns+=['search']
                db.execute("UPDATE songs SET duplicate_of=0,duplicate_state='' WHERE duplicate_of=? AND duplicate_state='kept'",(keeper['id'],))
                db.execute('UPDATE songs SET '+','.join(k+'=?' for k in columns)+' WHERE id=?',[merged[k] for k in columns]+[keeper['id']])
            row=self.library.get(keeper['id']);self.names.version=None;self.names.refresh(self.index.read);self.stats['replaced']+=1
            if self.replaced:self.replaced(old['path'],target)
        else:
            cached=type('Inspected',(),{'inspect':lambda _self,_path:(copy.deepcopy(record),list(warnings))})()
            ids=self.library.add_files([destination],inspector=cached)
            if not ids:raise ValueError('เพิ่มรายการเพลงไม่สำเร็จ')
            row=self.library.get(ids[0]);self.stats['added']+=1
        if copied:self.stats['copied']+=1
        self.remember(row);self.selected_id=self.selected_id or row['id']
        return row,'ใช้ไฟล์ใหม่' if keeper and choice=='new' else ('คัดลอกแล้ว' if copied else 'เพิ่มโดยไม่คัดลอก')
    def run(self,plan,single=False):
        accepted=skipped=done=0
        try:
            self.prepare()
            if self.events:self.events(dict(type='phase',phase='ตรวจความสมบูรณ์และป้องกันเพลงซ้ำ',total=plan.count(),target=plan.count()))
            for data in plan.db.execute('SELECT path FROM files ORDER BY path'):
                stopped(self.cancelled);path=data[0];hint=plan.hint(path) if hasattr(plan,'hint') else None
                try:
                    row,result=self.import_one(path,single,hint);duplicate=result.startswith('ซ้ำ')
                    accepted+=not duplicate;skipped+=duplicate
                    if duplicate:self.notes.append(result+' • ใช้รายการแรก #'+str(row['id'])+' • '+path)
                    category='ซ้ำกับรายการเดิม' if duplicate else 'อัปเดต' if result in ('อัปเดต','เดิมไม่เปลี่ยน') else 'เพิ่มใหม่'
                    if self.events:self.events(dict(type='item',ok=not duplicate,result=result,category=category,title=row['title'],artist=row['artist'],path=path,note=result))
                except (OSError,ValueError,EOFError) as error:
                    skipped+=1;self.stats['failed']+=1;self.notes.append('ข้าม: '+path+': '+str(error))
                    if self.events:self.events(dict(type='item',ok=False,path=path,note=str(error),category='อ่านไม่ได้'))
                done+=1
                if self.events:self.events(dict(type='progress',done=done,total=plan.count()))
        except SearchCancelled:pass
        summary='นำเข้า • เพิ่ม '+str(self.stats['added'])+' • ตรวจเดิม '+str(self.stats['updated'])+' • ใช้ใหม่ '+str(self.stats['replaced'])+' • คัดลอก '+str(self.stats['copied'])+' • ซ้ำ/ใช้เดิม '+str(self.stats['reused'])+' • ข้าม/ต้องตรวจเพิ่ม '+str(self.stats['failed'])
        return accepted,skipped+plan.omitted,[summary]+plan.errors+self.notes


def run_plan(library,plan,cancelled=None,events=None,single=False,backup_done=False,**options):
    selected=options.pop('selected',None)
    if not backup_done:
        try:library.backup_before_rebuild(cancelled)
        except SearchCancelled:return 0,0,['ยกเลิกก่อนเริ่มนำเข้า']
    with ImportSession(library,cancelled=cancelled,events=events,**options) as session:
        result=session.run(plan,single)
        if selected and session.selected_id:selected(session.selected_id)
        return result


def catalog_hints(plan,folder,cancelled=None):
    from .legacy import catalog_location,dbf_records,legacy_asset
    dbf,base=catalog_location(folder)
    for row in dbf_records(dbf):
        stopped(cancelled)
        try:
            file,kind,profile,playable=legacy_asset(base,row)
            if file.suffix.lower() not in SUPPORTED:continue
            plan.add_hint(file,dict(code=row.get('CODE',''),title=row.get('TITLE',''),artist=row.get('ARTIST',''),first_lyric=row.get('LYR_TITLE',''),rhythm=row.get('RHYTHM',''),key_signature=row.get('KEY',''),bpm=row.get('TEMPO',''),source_catalog=str(dbf.resolve())))
        except (OSError,ValueError) as error:plan.errors.append('ดัชนีเดิม: '+str(error))
