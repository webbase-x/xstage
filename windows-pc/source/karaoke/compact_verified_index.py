"""Create a verified playback sidecar without rebuilding the PC song catalog.

The operator must supply the authoritative original XMID directory, not an
untrusted mirror. Every newly verified package is read and validated once.
A separate local journal allows safe resume. Nothing writes to songs.sqlite3.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import unicodedata
from contextlib import closing
from pathlib import Path

from .xmid_reader import read_xmid
from .file_signature import change_time

PATH = re.compile(r'SONGS/MIDI/XMID/([0-9]+)/([0-9A-Za-z_-]+\.xmid)', re.I)
FORMAT = 'xstage-verified-compact-v1'

def stop(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError('Cancelled: verified journal retained; original untouched')

def no_link(p):
    return not p.is_symlink() and not getattr(p, 'is_junction', lambda: False)()

def stamp(p):
    s = p.stat()
    c = change_time(p, s)
    return json.dumps([s.st_size,s.st_mtime_ns,c,s.st_ino,s.st_dev]) if c is not None else None

def hashes(p, cancel=None):
    md5 = hashlib.md5(usedforsecurity=False)
    sha = hashlib.sha256()
    n = 0
    with p.open('rb') as f:
        while chunk := f.read(1024*1024):
            stop(cancel); n += len(chunk); md5.update(chunk); sha.update(chunk)
    return n, md5.hexdigest(), sha.hexdigest()

def stable_source(p, cancel=None):
    wal = Path(str(p)+'-wal')
    before = stamp(p)
    if wal.exists() and wal.stat().st_size:
        raise ValueError('Source WAL is active; export a stable snapshot first')
    result = hashes(p,cancel)
    if before is None or stamp(p)!=before or (wal.exists() and wal.stat().st_size):
        raise ValueError('Source changed or has no stable change stamp')
    return result

def verify_package(original, portable, code, title, artist, cancel=None):
    match = PATH.fullmatch(portable)
    if not match:
        raise ValueError('Unsafe XMID path')
    folder = original / match[1]
    p = folder / match[2]
    if not no_link(folder) or not no_link(p) or not p.is_file():
        raise ValueError('Original file missing or unsafe')
    before = stamp(p)
    if before is None:
        raise ValueError('Cannot verify stable original file')
    stop(cancel)
    _, doc = read_xmid(p)
    # Never substitute guessed code, display title or artist.
    if (str(doc.get('code') or ''),str(doc.get('title') or ''),str(doc.get('artist') or '')) != (code,title,artist):
        raise ValueError('Original package code/title/artist differs from catalog')
    size, md5, sha = hashes(p,cancel)
    if stamp(p)!=before:
        raise ValueError('Original changed during verification')
    return {'path':portable,'size':size,'md5Checksum':md5,'sha256':sha}, before

def build(source, compact, original, output, journal, *, cancel=None, progress=None):
    source,compact,original,output,journal = map(lambda x:Path(x).absolute(),(source,compact,original,output,journal))
    if not original.is_dir() or not no_link(original) or original.resolve()!=original:
        raise ValueError('Select the actual authoritative original XMID directory')
    if output.name.lower()!='songs.verified.sqlite3' or output.exists() or not no_link(output):
        raise ValueError('Use a new songs.verified.sqlite3 output; never overwrite a database')
    if len({x.resolve() for x in (source,compact,output,journal)})!=4 or journal.name.lower() in ('songs.sqlite3','songs.search.sqlite3','songs.verified.sqlite3'):
        raise ValueError('Source, compact, output and journal must be distinct')
    if not no_link(journal) or not output.parent.is_dir() or not no_link(output.parent):
        raise ValueError('Unsafe output or journal location')
    source_size, source_md5, source_sha = stable_source(source,cancel)
    compact_fingerprint=stable_source(compact,cancel)
    fd, temporary=tempfile.mkstemp(prefix='.verified-',suffix='.sqlite3',dir=output.parent)
    os.close(fd)
    checked=reused=rejected=0
    try:
        with closing(sqlite3.connect(compact.as_uri()+'?mode=ro&immutable=1',uri=True)) as idx, closing(sqlite3.connect(source.as_uri()+'?mode=ro&immutable=1',uri=True)) as base, closing(sqlite3.connect(journal)) as cache, closing(sqlite3.connect(temporary)) as out:
            meta=dict(idx.execute('SELECT key,value FROM index_meta'))
            if meta.get('format')!='xstage-search-index-v1' or meta.get('source_md5')!=source_md5 or meta.get('source_sha256')!=source_sha or meta.get('source_bytes')!=str(source_size):
                raise ValueError('Compact index is stale or not derived from the supplied source')
            idx.execute('PRAGMA query_only=ON');base.execute('PRAGMA query_only=ON')
            cache.execute('CREATE TABLE IF NOT EXISTS checked (key TEXT PRIMARY KEY, stamp TEXT NOT NULL, media TEXT NOT NULL)')
            out.executescript('''PRAGMA journal_mode=DELETE;
                CREATE TABLE catalog_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE songs(id INTEGER PRIMARY KEY,ordinal INTEGER NOT NULL,web_song_id TEXT UNIQUE NOT NULL,search TEXT NOT NULL,playable INTEGER NOT NULL,payload TEXT NOT NULL,code TEXT NOT NULL,title TEXT NOT NULL,artist TEXT NOT NULL);
                CREATE TABLE verification_errors(id INTEGER PRIMARY KEY,reason TEXT NOT NULL);
                CREATE INDEX songs_code ON songs(code,id);
                CREATE INDEX songs_title ON songs(title COLLATE NOCASE,id);''')
            seen=set()
            total=int(meta['count'])
            for ident,code,title,artist,portable in idx.execute('SELECT id,code,title,artist,path FROM songs ORDER BY id'):
                stop(cancel)
                try:
                    old=base.execute('SELECT code,title,artist,path,playable FROM songs WHERE id=?',(ident,)).fetchone()
                    match=PATH.fullmatch(portable)
                    if not old or tuple(old[:3])!=(code,title,artist) or old[4]!=1 or not match or not str(old[3]).replace('\\','/').casefold().endswith('/xmid/'+match[1]+'/'+match[2].casefold()):
                        raise ValueError('Compact row differs from source')
                    p=original/match[1]/match[2]
                    if not no_link(p.parent) or not no_link(p) or not p.is_file():
                        raise ValueError('Original file missing or unsafe')
                    before=stamp(p)
                    key=json.dumps([str(original),portable,code,title,artist],ensure_ascii=False)
                    saved=cache.execute('SELECT media FROM checked WHERE key=? AND stamp=?',(key,before)).fetchone() if before else None
                    if saved and stamp(p)==before:
                        media=json.loads(saved[0]);reused+=1
                    else:
                        media,verified_stamp=verify_package(original,portable,code,title,artist,cancel)
                        cache.execute('INSERT OR REPLACE INTO checked VALUES(?,?,?)',(key,verified_stamp,json.dumps(media)))
                        cache.commit()
                    web_id='browser/xmid/'+media['md5Checksum']
                    if web_id in seen:
                        raise ValueError('Duplicate package identity; requires review')
                    seen.add(web_id)
                    song={'webSongId':web_id,'code':code,'sourceCode':code,'title':title,'artist':artist,'sourceFormat':'XMID','pendingDriveLink':True,'xmid':media}
                    search=unicodedata.normalize('NFC',' '.join([code,title,artist])).lower()
                    out.execute('INSERT INTO songs VALUES(?,?,?,?,?,?,?,?,?)',(ident,checked,web_id,search,1,json.dumps(song,ensure_ascii=False,separators=(',',':')),code,title,artist))
                    checked+=1
                except (ValueError,OSError,UnicodeError) as e:
                    rejected+=1
                    out.execute('INSERT INTO verification_errors VALUES(?,?)',(ident,str(e)[:300]))
                if progress:progress(checked+rejected,total)
            if checked+rejected!=total:
                raise ValueError('Compact count mismatch')
            stop(cancel)
            out.executemany('INSERT INTO catalog_meta VALUES(?,?)',{'format':'xstage-sqlite3-v1','schemaVersion':'1','kind':'snapshot','generation':source_sha,'pcSchema':'verified-compact-v1','mediaIdentity':FORMAT,'sourceMD5':source_md5,'sourceBytes':str(source_size),'sourceSHA256':source_sha,'compactMD5':compact_fingerprint[1],'verifiedCount':str(checked),'rejectedCount':str(rejected),'expectedCount':str(total)}.items())
            out.commit()
            if out.execute('PRAGMA quick_check').fetchone()!=('ok',):
                raise ValueError('Verified sidecar integrity check failed')
        if stable_source(source,cancel)!=(source_size,source_md5,source_sha) or stable_source(compact,cancel)!=compact_fingerprint:
            raise ValueError('Source or compact index changed during verification')
        if checked==0:
            raise ValueError('No original songs verified; no catalog published')
        stop(cancel)
        os.link(temporary,output)
        return {'verified':checked,'reused':reused,'rejected':rejected,'outputBytes':output.stat().st_size,'sourceMD5':source_md5}
    finally:
        for suffix in ('','-journal','-wal','-shm'):
            Path(temporary+suffix).unlink(missing_ok=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','compact','original','output','journal'):
        parser.add_argument(name,type=Path)
    a=parser.parse_args()
    print(json.dumps(build(a.source,a.compact,a.original,a.output,a.journal),ensure_ascii=False,indent=2))
