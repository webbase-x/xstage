import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from build_search_index import build, portable_path

class CompactIndexTests(unittest.TestCase):
    def test_real_sqlite(self):
        with tempfile.TemporaryDirectory() as directory:
            src=Path(directory)/'songs.sqlite3'
            out=Path(directory)/'songs.search.sqlite3'
            db=sqlite3.connect(src)
            db.execute('CREATE TABLE songs(id INTEGER PRIMARY KEY,code TEXT,title TEXT,artist TEXT,path TEXT,playable INTEGER)')
            rows=[]
            for i in range(1,25):
                rows.append((i,str(i),'รักเพลง '+str(i),'ศิลปิน',fr'D:\XStageSong\XMID\0\{i:08}.xmid',1))
                rows.append((i+100,str(i),'รักเพลง '+str(i),'ศิลปิน',fr'G:\My Drive\XStageKaraoke\SONGS\MIDI\XMID\0\{i:08}.xmid',1))
            rows.extend([(301,'1','รักเพลง 1','ศิลปิน','XMID/1/00000001.xmid',1),(302,'2','อื่น','ศิลปิน','XMID/../bad.xmid',1),(303,'3','อื่น','ศิลปิน','XMID/0/hidden.xmid',0)])
            db.executemany('INSERT INTO songs VALUES(?,?,?,?,?,?)',rows);db.commit();db.close()
            before=hashlib.sha256(src.read_bytes()).hexdigest()
            stats=build(src,out)
            self.assertEqual((stats['scanned'],stats['indexed'],stats['duplicates'],stats['skipped']),(50,25,24,1))
            self.assertEqual(hashlib.sha256(src.read_bytes()).hexdigest(),before)
            c=sqlite3.connect(out.as_uri()+'?mode=ro&immutable=1',uri=True)
            try:
                self.assertEqual(c.execute('PRAGMA quick_check').fetchone(),('ok',))
                self.assertEqual(c.execute('SELECT id FROM songs WHERE code=? ORDER BY id',('1',)).fetchall(),[(1,),(301,)])
                self.assertEqual(c.execute('SELECT count(*) FROM song_fts WHERE song_fts MATCH ?',('"รัก"',)).fetchone(),(25,))
                meta=dict(c.execute('SELECT key,value FROM index_meta'))
                self.assertEqual(meta['source_sha256'],before)
                self.assertEqual(meta['count'],'25')
                self.assertEqual(meta['media_identity'],'unverified-preview-only')
            finally:c.close()
            with self.assertRaises(ValueError):build(src,out)
            with self.assertRaises(ValueError):build(src,src)
            (Path(str(src)+'-wal')).write_bytes(b'pending')
            with self.assertRaises(ValueError):build(src,Path(directory)/'second.sqlite3')
            self.assertFalse((Path(directory)/'second.sqlite3').exists())
    def test_path(self):
        self.assertEqual(portable_path(r'D:\XMID\0\001.XMID'),'SONGS/MIDI/XMID/0/001.xmid')
        self.assertIsNone(portable_path('XMID/../001.xmid'))
        self.assertIsNone(portable_path('XMID/0/001.mid'))

if __name__=='__main__':unittest.main()
