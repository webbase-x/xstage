"""Disk-backed title/artist grouping; never changes the song database."""
import json
import re
import sqlite3
import tempfile
import unicodedata
from pathlib import Path
from .library import SearchCancelled


def musical_key(value):
    text=unicodedata.normalize('NFC',str(value or '')).strip().replace('♯','#').replace('♭','b')
    text=re.sub(r'^(?:key|คีย์)\s*[:=]?\s*','',text,flags=re.I)
    match=re.fullmatch(r'([A-G])([#b]?)(?:\s*(m|minor|min|major|maj))?',text,flags=re.I)
    if not match:return None
    note,accidental,mode=match.groups();accidental=accidental.lower();pitch={'C':0,'D':2,'E':4,'F':5,'G':7,'A':9,'B':11}[note.upper()]
    pitch=(pitch+(1 if accidental=='#' else -1 if accidental=='b' else 0))%12
    return str(pitch)+('m' if mode is not None and mode!='M' and mode.lower() in ('m','minor','min') else 'M')


_LEGACY=object()
def identity(title,artist,key=_LEGACY):
    def clean(value):return ' '.join(unicodedata.normalize('NFC',str(value or '')).casefold().split())
    title,artist=clean(title),clean(artist)
    if not title or not artist:return None
    if key is _LEGACY:return json.dumps((title,artist),ensure_ascii=False)
    key=musical_key(key)
    return json.dumps((title,artist,key),ensure_ascii=False) if key else None


class NameIndex:
    def __init__(self,include_key=True):
        self.include_key=include_key
        self.temp=tempfile.TemporaryDirectory(prefix='xstage-names-')
        self.db=sqlite3.connect(str(Path(self.temp.name)/'names.sqlite3'))
        self.db.execute('CREATE TABLE names(id INTEGER PRIMARY KEY,k TEXT NOT NULL,visible INTEGER NOT NULL)')
        self.db.execute('CREATE INDEX by_name ON names(k,visible DESC,id)')
        self.version=None
    def close(self):self.db.close();self.temp.cleanup()
    def add(self,row):
        self.db.execute('DELETE FROM names WHERE id=?',(row['id'],))
        key=identity(row.get('title'),row.get('artist'),row.get('key_signature')) if self.include_key else identity(row.get('title'),row.get('artist'))
        if key and row.get('duplicate_state') not in ('moved','recycled','deleted','excluded','invalid'):
            self.db.execute('INSERT INTO names VALUES (?,?,?)',(row['id'],key,int(not row.get('duplicate_of',0))))
    def refresh(self,connection,cancelled=lambda:False):
        version=connection.execute('PRAGMA data_version').fetchone()[0]
        if version==self.version:return
        self.db.execute('DELETE FROM names')
        cursor=connection.execute("SELECT id,title,artist,key_signature,duplicate_of,duplicate_state FROM songs WHERE duplicate_state NOT IN ('moved','recycled','deleted','excluded','invalid','missing') ORDER BY id")
        try:
            while True:
                rows=cursor.fetchmany(500)
                if not rows:break
                if cancelled():raise SearchCancelled()
                for row in rows:self.add(dict(row))
            self.db.commit();self.version=version
        except BaseException:
            self.db.rollback();self.version=None;raise
        finally:cursor.close()
    def lookup(self,title,artist,key_signature=None):
        key=identity(title,artist,key_signature) if self.include_key else identity(title,artist)
        if key is None:return None,0
        first=self.db.execute('SELECT id FROM names WHERE k=? ORDER BY visible DESC,id LIMIT 1',(key,)).fetchone()
        count=self.db.execute('SELECT count(*) FROM names WHERE k=?',(key,)).fetchone()[0]
        return (first[0] if first else None),count
    def candidates(self,title,artist,key_signature):
        key=identity(title,artist,key_signature) if self.include_key else identity(title,artist)
        if key is None:return []
        return [row[0] for row in self.db.execute('SELECT id FROM names WHERE k=? ORDER BY visible DESC,id',(key,))]
    def annotate(self,rows):
        for row in rows:
            keeper,count=self.lookup(row.get('title'),row.get('artist'),row.get('key_signature'))
            row['name_duplicate_count']=count;row['name_keeper_id']=keeper
        return rows
