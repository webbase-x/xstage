"""Count and spool work once; bounded memory and batched SQLite writes."""
import os
import json
import sqlite3
import tempfile
from pathlib import Path
from .library import SUPPORTED, canonical
from .ingest import Inspector

class SongPlan:
    def __init__(self):
        self.temp=tempfile.TemporaryDirectory(prefix='xstage-plan-')
        self.db=sqlite3.connect(str(Path(self.temp.name)/'plan.db'))
        self.db.execute('PRAGMA journal_mode=OFF')
        self.db.execute('CREATE TABLE files(path TEXT PRIMARY KEY, existing INTEGER NOT NULL DEFAULT 0) WITHOUT ROWID')
        self.db.execute('CREATE TABLE omitted(path TEXT PRIMARY KEY) WITHOUT ROWID')
        self.db.execute('CREATE TABLE hints(path TEXT PRIMARY KEY,data TEXT)')
        self.total=0
        self.omitted=0
        self.errors=[]
    def close(self):
        self.db.close();self.temp.cleanup()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def add(self,path):
        before=self.db.total_changes
        self.db.execute('INSERT OR IGNORE INTO files(path) VALUES (?)',(canonical(Path(path)),))
        self.total+=self.db.total_changes-before
    def folder(self,folder,extensions=None,cancelled=None,events=None):
        allowed=SUPPORTED if extensions is None else extensions
        examined=0
        if not Path(folder).is_dir():
            self.errors.append('ไม่พบโฟลเดอร์: '+str(folder));return
        def onerror(error):self.errors.append(str(error))
        for root,dirs,files in os.walk(folder,followlinks=False,onerror=onerror):
            if cancelled and cancelled.is_set():break
            if '.xstage-duplicate-quarantine' in files:
                dirs[:]=[];continue
            dirs[:]=[name for name in dirs if not name.startswith('.')]
            batch=[]
            for name in files:
                if cancelled and cancelled.is_set():break
                ext=Path(name).suffix.lower()
                if ext in allowed:
                    batch.append((canonical(Path(root)/name),))
                elif ext in {'.xmk','.xak','.xvk','.rms','.kmid'}:
                    path=canonical(Path(root)/name)
                    before=self.db.total_changes
                    self.db.execute('INSERT OR IGNORE INTO omitted VALUES (?)',(path,))
                    if self.db.total_changes>before:
                        self.omitted+=1
                        self.errors.append('ยังไม่รองรับ: '+path)
                        if events:events(dict(type='notice',ok=False,path=path,title=name,note='ยังไม่รองรับรูปแบบนี้'))
                examined+=1
            before=self.db.total_changes
            self.db.executemany('INSERT OR IGNORE INTO files(path) VALUES (?)',batch)
            self.total+=self.db.total_changes-before
            if events:
                events(dict(type='progress',phase='นับจำนวนเพลง',done=self.count(),total=None,path=str(root)))
        self.db.commit()
    def add_hint(self,path,record):
        self.add(path)
        self.db.execute('INSERT OR REPLACE INTO hints VALUES (?,?)',(canonical(Path(path)),json.dumps(record,ensure_ascii=False)))
    def hint(self,path):
        row=self.db.execute('SELECT data FROM hints WHERE path=?',(canonical(Path(path)),)).fetchone()
        return json.loads(row[0]) if row else None
    def count(self):return self.total
    def run(self,library,cancelled=None,events=None,progress=None,force=False,protected=(),incremental=True):
        if incremental:
            from .incremental import IncrementalIndex
            with IncrementalIndex(library,events,cancelled,protected,force) as index:
                return index.run(self,progress)
        total=self.count()
        if events:events(dict(type='phase',phase='อ่านข้อมูลเพลง',total=total,target=total))
        inspector=Inspector()
        accepted=processed=0
        def inspected(event):
            nonlocal processed
            processed+=1
            if events:events(event)
        cursor=self.db.execute('SELECT path FROM files ORDER BY path')
        while not (cancelled and cancelled.is_set()):
            rows=cursor.fetchmany(100)
            if not rows:break
            ids=library.add_files([row[0] for row in rows],inspector,self.errors,cancelled,
                                  inspected=inspected,events=events)
            accepted+=len(ids)
            if progress:progress(processed)
        if events:events(dict(type='progress',done=processed,total=total))
        return accepted,self.omitted,self.errors
