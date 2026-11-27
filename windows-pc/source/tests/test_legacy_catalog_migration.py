import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from karaoke.legacy_catalog_migration import migrate
from karaoke.shared_catalog_builder import _pc_id
from test_shared_catalog_builder import _xmid

class LegacyMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.home=self.root/"PC";self.home.mkdir()
        self.songs=self.root/"SONGS";self.folder=self.songs/"MIDI"/"XMID"/"0"
        self.folder.mkdir(parents=True)
        self.source=self.root/"legacy.sqlite3"
        self.midi=(b"MThd\x00\x00\x00\x06\x00\x00\x00\x01\x00\x60"
                   b"MTrk\x00\x00\x00\x04\x00\xff\x2f\x00")
        for n in (1,2):
            (self.folder/f"{n:05}.xmid").write_bytes(_xmid(f"{n:05}","ชื่อในแพ็กเกจ","ศิลปิน",self.midi))
        with closing(sqlite3.connect(self.source)) as db:
            db.execute("CREATE TABLE songs(id INTEGER PRIMARY KEY,path TEXT,code TEXT,title TEXT,artist TEXT,favorite INTEGER,playable INTEGER,first_lyric TEXT)")
            db.executemany("INSERT INTO songs VALUES(?,?,?,?,?,?,?,?)",[
                (17,r"D:\xstagesong\xmid\0\00001.xmid","00001","ชื่อแก้แล้ว","",1,1,"เนื้อเดิม"),
                (29,r"D:\xstagesong\xmid\0\00002.xmid","00002","ชื่อสอง","ศิลปิน",0,1,"")])
            db.commit()

    def test_preserve_all_codes_and_old_ids_without_mutating_source(self):
        before=self.source.read_bytes()
        result=migrate(self.source,self.songs,self.home)
        self.assertEqual(result["accepted"],2)
        self.assertEqual(self.source.read_bytes(),before)
        with closing(sqlite3.connect(result["database"])) as db:
            rows=db.execute("SELECT id,code,title,artist,payload,midi_md5 FROM songs ORDER BY ordinal").fetchall()
            self.assertEqual([(r[1],r[2],r[3]) for r in rows],[("00001","ชื่อแก้แล้ว",""),("00002","ชื่อสอง","ศิลปิน")])
            for r,legacy in zip(rows,(17,29)):
                payload=json.loads(r[4]); self.assertEqual(payload["legacyPcId"],legacy)
                self.assertEqual(r[0],_pc_id(payload["webSongId"]))
                self.assertEqual(payload["xmid"]["md5Checksum"],hashlib.md5((self.folder/(r[1]+".xmid")).read_bytes()).hexdigest())
                self.assertTrue(payload["pendingDriveLink"])
                self.assertIsNone(r[5])
            self.assertEqual(db.execute("SELECT legacy_id FROM legacy_pc_ids ORDER BY legacy_id").fetchall(),[(17,),(29,)])

    def test_missing_or_ambiguous_file_does_not_replace_existing_snapshot(self):
        first=migrate(self.source,self.songs,self.home)
        previous=Path(first["database"]).read_bytes()
        (self.folder/"00002.xmid").unlink()
        with self.assertRaises(ValueError):migrate(self.source,self.songs,self.home)
        self.assertEqual(Path(first["database"]).read_bytes(),previous)
        (self.songs/"00001.xmid").write_bytes((self.folder/"00001.xmid").read_bytes())
        with self.assertRaises(ValueError):migrate(self.source,self.songs,self.home)
        self.assertEqual(Path(first["database"]).read_bytes(),previous)


    def test_pc_legacy_export_keeps_master_and_cloud_backup(self):
        from karaoke.local_master import prepare_legacy_export, export_portable
        import shutil
        drive=self.root/"XStageKaraoke"
        shutil.copytree(self.songs,drive/"SONGS")
        (drive/"SOUNDFONT").mkdir()
        (drive/"FX").mkdir()
        (drive/"DB").mkdir()
        (self.home/"DB").mkdir()
        live=self.home/"DB"/"songs.sqlite3"
        shutil.copyfile(self.source,live)
        cloud=drive/"DB"/"songs.sqlite3"
        shutil.copyfile(self.source,cloud)
        original=live.read_bytes()
        prepared=prepare_legacy_export(self.home,live,drive)
        self.assertEqual(prepared["accepted"],2)
        with self.assertRaises(FileExistsError):
            export_portable(self.home,drive,pending=True)
        self.assertEqual(cloud.read_bytes(),original)
        export_portable(self.home,drive,pending=True,overwrite=True)
        self.assertEqual(live.read_bytes(),original)
        with closing(sqlite3.connect(cloud)) as db:
            self.assertEqual(db.execute("SELECT value FROM catalog_meta WHERE key='pcSchema'").fetchone()[0],"shared-v1")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM songs").fetchone()[0],2)
        self.assertEqual(len(list(cloud.parent.glob("*.bak"))),1)
