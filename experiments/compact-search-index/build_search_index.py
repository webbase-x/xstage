"""Build a compact, derived X-Stage search index from a stable SQLite snapshot.
Never changes the source. Index is for discovery, not proof of media identity.
"""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path

FORMAT = 'xstage-search-index-v1'
PATH = re.compile(r'(?:^|/)xmid/([0-9]+)/([0-9A-Za-z_-]+\.xmid)$', re.I)

def portable_path(value):
    raw = str(value or '').replace('\\', '/')
    if any(p in ('', '.', '..') for p in raw.split('/')) or any(ord(c)<32 for c in raw):
        return None
    m = PATH.search(raw)
    return f'SONGS/MIDI/XMID/{m[1]}/{m[2].lower()}' if m else None

def fingerprint(path):
    wal = Path(str(path) + '-wal')
    if wal.exists() and wal.stat().st_size:
        raise ValueError('Source has uncheckpointed/active WAL; use a stable exported snapshot')
    before = path.stat()
    md5 = hashlib.md5(usedforsecurity=False)
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024*1024):
            md5.update(chunk); sha.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or (wal.exists() and wal.stat().st_size):
        raise ValueError('Source changed during fingerprint')
    return (after.st_size, md5.hexdigest(), sha.hexdigest(), after.st_mtime_ns)

def build(source, destination):
    source, destination = Path(source).resolve(strict=True), Path(destination).resolve()
    if source == destination or destination.exists() or destination.name.lower() == 'songs.sqlite3':
        raise ValueError('Choose a new derived index filename; never overwrite a catalog')
    if not destination.parent.is_dir():
        raise ValueError('Destination directory does not exist')
    original = fingerprint(source)
    fd, tmp = tempfile.mkstemp(prefix='.search-index-', suffix='.sqlite3', dir=destination.parent)
    os.close(fd)
    src = out = None
    try:
        src = sqlite3.connect(source.as_uri()+'?mode=ro&immutable=1', uri=True)
        src.execute('PRAGMA query_only=ON')
        cols = {row[1] for row in src.execute('PRAGMA table_info(songs)')}
        required = {'id','code','title','artist','path','playable'}
        if not required <= cols:
            raise ValueError('Unsupported PC catalog schema')
        if 'web_song_id' in cols:
            raise ValueError('Shared catalog requires its own identity adapter; not supported by this PC exporter')
        out = sqlite3.connect(tmp)
        out.executescript('''PRAGMA journal_mode=DELETE; PRAGMA synchronous=FULL; PRAGMA temp_store=FILE; PRAGMA cache_size=-8192;
        CREATE TABLE index_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL) WITHOUT ROWID;
        CREATE TABLE songs(id INTEGER PRIMARY KEY,code TEXT NOT NULL,title TEXT NOT NULL,artist TEXT NOT NULL,path TEXT NOT NULL,UNIQUE(code,title,artist,path));
        ''')
        scanned = skipped = duplicates = inserted = 0
        for ident,code,title,artist,path in src.execute('SELECT id,code,title,artist,path FROM songs WHERE playable=1 ORDER BY id'):
            scanned += 1
            canonical = portable_path(path)
            if canonical is None or not isinstance(ident,int) or ident<1 or not all(isinstance(x,str) for x in (code,title,artist)):
                skipped += 1; continue
            result=out.execute('INSERT INTO songs VALUES(?,?,?,?,?) ON CONFLICT(code,title,artist,path) DO NOTHING',(ident,code,title,artist,canonical))
            if result.rowcount: inserted+=1
            else: duplicates+=1
        out.executescript('''CREATE INDEX songs_code ON songs(code,id);
        CREATE INDEX songs_title ON songs(title COLLATE NOCASE,id);
        CREATE INDEX songs_artist ON songs(artist COLLATE NOCASE,id);
        CREATE VIRTUAL TABLE song_fts USING fts5(title,artist,content='songs',content_rowid='id',tokenize='trigram');
        INSERT INTO song_fts(song_fts) VALUES('rebuild');
        ''')
        meta={'format':FORMAT,'source_md5':original[1],'source_sha256':original[2],'source_bytes':str(original[0]),'source_schema':'pc-local','count':str(inserted),'duplicates':str(duplicates),'skipped':str(skipped),'search_fields':'code,title,artist','media_identity':'unverified-preview-only'}
        out.executemany('INSERT INTO index_meta VALUES(?,?)',meta.items());out.commit()
        out.execute('VACUUM')
        if out.execute('PRAGMA quick_check').fetchone()!=('ok',): raise ValueError('Derived index integrity check failed')
        out.execute("INSERT INTO song_fts(song_fts,rank) VALUES('integrity-check',1)");out.commit()
        out.close();out=None;src.close();src=None
        if fingerprint(source)!=original: raise ValueError('Source changed during index construction')
        # Publish a complete file atomically without replacing any existing file.
        os.link(tmp,destination);os.unlink(tmp)
        return {'source_bytes':original[0],'source_sha256':original[2],'scanned':scanned,'indexed':inserted,'duplicates':duplicates,'skipped':skipped,'index_bytes':destination.stat().st_size}
    finally:
        if out: out.close()
        if src: src.close()
        for suffix in ('','-journal','-wal','-shm'):
            Path(tmp+suffix).unlink(missing_ok=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path);parser.add_argument('destination',type=Path)
    args=parser.parse_args();print(json.dumps(build(args.source,args.destination),indent=2))
