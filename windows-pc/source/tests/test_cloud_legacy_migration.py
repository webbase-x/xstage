import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from karaoke.cloud_legacy_migration import stage_cloud, FOLDER, resolve_legacy

class CloudMigrationTests(unittest.TestCase):
    def test_cloud_only_metadata_and_legacy_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/"legacy.sqlite3"
            with closing(sqlite3.connect(source)) as db:
                db.execute("CREATE TABLE songs(id INTEGER PRIMARY KEY,path TEXT,code TEXT,title TEXT,artist TEXT)")
                db.execute("INSERT INTO songs VALUES(17,?,?,?,?)",(r"D:\xstagesong\xmid\0\00000001.xmid","00000001","เพลง",""))
                db.commit()
            def folder(ident,name,parent=None):
                return dict(id=ident,name=name,mimeType=FOLDER,parents=[parent] if parent else [])
            def file(ident,name,parent,data):
                return dict(id=ident,name=name,parents=[parent],mimeType="application/octet-stream",size=str(len(data)),md5Checksum=hashlib.md5(data).hexdigest(),version="1")
            tree={"root000":[folder("songs000","SONGS","root000"),folder("db000","DB","root000")],
                  "db000":[file("sqlite000","songs.sqlite3","db000",source.read_bytes())],
                  "songs000":[folder("midi000","MIDI","songs000")],
                  "midi000":[folder("xmid000","XMID","midi000")],
                  "xmid000":[folder("zero000","0","xmid000")],
                  "zero000":[file("media000","00000001.xmid","zero000",b"package")]}
            class Fake:
                def metadata(self,ident):return folder("root000","XStageKaraoke")
                def children(self,ident):return iter(tree[ident])
                def download_db(self,meta,destination):
                    assert meta["id"]=="sqlite000"
                    destination.write_bytes(source.read_bytes())
            before=source.read_bytes()
            result=stage_cloud(Fake(),"root000",root/"candidate.sqlite3")
            self.assertFalse(result["cloud_written"])
            self.assertEqual(result["accepted"],1)
            self.assertEqual(source.read_bytes(),before)
            with closing(sqlite3.connect(result["database"])) as db:
                payload=json.loads(db.execute("SELECT payload FROM songs").fetchone()[0])
                self.assertEqual(payload["legacyPcId"],17)
                self.assertEqual(payload["code"],"00000001")
                self.assertEqual(payload["xmid"]["fileId"],"media000")
                self.assertEqual(payload["xmid"]["path"],"SONGS/MIDI/XMID/0/00000001.xmid")
                self.assertIsNone(payload["midiSize"])
                self.assertNotIn("pendingDriveLink",payload)
            with self.assertRaises(FileExistsError):
                stage_cloud(Fake(),"root000",root/"candidate.sqlite3")

    def test_ambiguous_path_fails(self):
        with self.assertRaises(ValueError):
            resolve_legacy(r"D:\XMID\0\a.xmid",{"xmid/0/a.xmid":("XMID/0/a.xmid",{}),"midi/xmid/0/a.xmid":("MIDI/XMID/0/a.xmid",{})})
