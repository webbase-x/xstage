import sqlite3
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import xmid_library_manager as manager


class XmidManagerTests(unittest.TestCase):
    def test_audit_and_recover_without_database_write(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);root=base/"SONGS";root.mkdir()
            out=base/"out";out.mkdir();db=base/"songs.sqlite3"
            a=root/"00001.xmid";a.write_bytes(b"one")
            b=root/"00002.xmid";b.write_bytes(b"two")
            with sqlite3.connect(db) as con:
                con.execute("CREATE TABLE songs(id INTEGER PRIMARY KEY,path TEXT,code TEXT,title TEXT,artist TEXT,duplicate_of INTEGER,playable INTEGER)")
                con.executemany("INSERT INTO songs VALUES(?,?,?,?,?,?,?)",[
                    (1,str(a),"00001","ชื่อเพลง","ศิลปิน",0,1),
                    (2,str(b),"00002","","",1,1),
                    (3,str(root/"missing.xmid"),"00003","","",0,0),
                    (4,str(base/"outside.xmid"),"00004","","",0,1)])
            before=db.read_bytes()
            plan=manager.scan(str(db),str(root))
            self.assertEqual(plan["counts"]["no_title"],3)
            self.assertEqual(plan["counts"]["duplicate"],1)
            self.assertEqual(plan["counts"]["missing"],1)
            self.assertEqual(plan["counts"]["unsafe"],1)
            self.assertEqual(manager.page(plan,"all")["actionable"],1)
            result=manager.relocate(plan,"all",[],True,[],str(out),"delete")
            self.assertEqual(result["moved"],1)
            self.assertFalse(b.exists())
            self.assertEqual(a.read_bytes(),b"one")
            self.assertEqual(next(out.rglob("00002.xmid")).read_bytes(),b"two")
            self.assertEqual(db.read_bytes(),before)

    def test_shared_catalog_and_stale_file_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);root=base/"SONGS";root.mkdir()
            out=base/"out";out.mkdir();db=base/"songs.sqlite3"
            file=root/"a.xmid";file.write_bytes(b"old")
            with sqlite3.connect(db) as con:
                con.execute("CREATE TABLE songs(id INTEGER PRIMARY KEY,path TEXT,code TEXT,title TEXT,artist TEXT,web_song_id TEXT,original_relative_path TEXT)")
                con.execute("INSERT INTO songs VALUES(1,'SONGS/a.xmid','a','','','remote','SONGS/a.xmid')")
            plan=manager.scan(str(db),str(root))
            self.assertTrue(plan["shared"])
            self.assertFalse(plan["rows"][0]["actionable"])
            with self.assertRaises(ValueError):
                manager.relocate(plan,"all",[1],False,[],str(out),"move")
            with sqlite3.connect(db) as con:
                con.execute("DROP TABLE songs")
                con.execute("CREATE TABLE songs(id INTEGER PRIMARY KEY,path TEXT,code TEXT,title TEXT,artist TEXT)")
                con.execute("INSERT INTO songs VALUES(1,?,'a','','')",(str(file),))
            plan=manager.scan(str(db),str(root))
            file.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                manager.relocate(plan,"all",[1],False,[],str(out),"move")
            self.assertEqual(file.read_bytes(),b"changed")
