from contextlib import closing
import hashlib
import json
import sqlite3
import struct
import tempfile
import unittest
from pathlib import Path
from threading import Event
from karaoke.compact_verified_index import build, verify_package

def package(path, code, title, artist):
    def text(s):
        b=s.encode('utf8')
        return struct.pack('<I',len(b))+b
    meta=b''.join(text(s) for s in ['song',code,'version',title,artist,'verified'])+struct.pack('<I',0)
    midi=b'MThd'+bytes(16)
    data=struct.pack('<8sIQQ32s32s',b'XSTGPLS1',1,len(meta),len(midi),hashlib.sha256(midi).digest(),hashlib.sha256(meta).digest())+meta+midi
    path.write_bytes(data)
    return data

class VerifiedCompactTest(unittest.TestCase):
    def test_source_preserved_resume_and_rejection(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td).resolve()
            orig=root/'XMID';(orig/'0').mkdir(parents=True)
            good=package(orig/'0'/'1.xmid','1','รัก','ศิลปิน')
            package(orig/'0'/'2.xmid','2','ผิด','ศิลปิน')
            src=root/'songs.sqlite3';compact=root/'songs.search.sqlite3';journal=root/'verification-journal.sqlite3'
            rows=[(1,'1','รัก','ศิลปิน','SONGS/MIDI/XMID/0/1.xmid'),(2,'2','เพลง','ศิลปิน','SONGS/MIDI/XMID/0/2.xmid'),(3,'3','เพลง','ศิลปิน','SONGS/MIDI/XMID/0/3.xmid')]
            with closing(sqlite3.connect(src)) as c, c:
                c.execute('CREATE TABLE songs(id INTEGER PRIMARY KEY,code,title,artist,path,playable)')
                c.executemany('INSERT INTO songs VALUES(?,?,?,?,?,1)',rows)
            raw=src.read_bytes()
            with closing(sqlite3.connect(compact)) as c, c:
                c.executescript('CREATE TABLE index_meta(key,value);CREATE TABLE songs(id INTEGER PRIMARY KEY,code,title,artist,path);')
                c.executemany('INSERT INTO songs VALUES(?,?,?,?,?)',rows)
                c.executemany('INSERT INTO index_meta VALUES(?,?)',dict(format='xstage-search-index-v1',source_md5=hashlib.md5(raw).hexdigest(),source_sha256=hashlib.sha256(raw).hexdigest(),source_bytes=str(len(raw)),count='3').items())
            compact_raw=compact.read_bytes()
            out=root/'songs.verified.sqlite3'
            event=Event()
            def progress(done,total):
                if done==1:event.set()
            with self.assertRaises(InterruptedError):
                build(src,compact,orig,out,journal,cancel=event,progress=progress)
            self.assertFalse(out.exists())
            stats=build(src,compact,orig,out,journal)
            self.assertEqual((stats['verified'],stats['reused'],stats['rejected']),(1,1,2))
            with closing(sqlite3.connect(out)) as c, c:
                s=json.loads(c.execute('SELECT payload FROM songs').fetchone()[0])
                self.assertEqual(s['xmid']['md5Checksum'],hashlib.md5(good).hexdigest())
                self.assertEqual(s['xmid']['sha256'],hashlib.sha256(good).hexdigest())
                self.assertTrue(s['pendingDriveLink'])
                self.assertEqual(c.execute('SELECT count(*) FROM verification_errors').fetchone()[0],2)
                self.assertEqual(c.execute('PRAGMA quick_check').fetchone()[0],'ok')
            self.assertEqual(src.read_bytes(),raw)
            self.assertEqual(compact.read_bytes(),compact_raw)
            with self.assertRaises(ValueError):
                build(src,compact,orig,out,journal)
            with self.assertRaises(ValueError):
                verify_package(orig,'SONGS/MIDI/XMID/../1.xmid','1','รัก','ศิลปิน')
            (orig/'0'/'1.xmid').write_bytes(good[:-1]+b'x')
            with self.assertRaises(ValueError):
                verify_package(orig,'SONGS/MIDI/XMID/0/1.xmid','1','รัก','ศิลปิน')

if __name__=='__main__':unittest.main()
