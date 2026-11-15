import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from karaoke.library import SongLibrary,write_json
from karaoke import restore

class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.source=self.root/'ชุดสำรอง';self.data=self.root/'Data'
        for folder,title in [(self.source,'เก่า'),(self.data,'ปัจจุบัน')]:
            folder.mkdir();lib=SongLibrary(folder/'songs.sqlite3')
            with lib.connect() as db:
                db.execute('INSERT INTO songs(id,path,code,title,artist,kind,search) VALUES(1,?,?,?,?,?,?)',('D:/songs/1.mid','1',title,'ผู้ร้อง','midi',title))
            write_json(folder/'settings.json',{'title':title})
            write_json(folder/'queue.json',[{'song_id':1,'singer':title,'key':2,'speed':100}])
    def tearDown(self):self.temp.cleanup()
    def title(self):
        with closing(restore.readonly(self.data/'songs.sqlite3')) as db:return db.execute('SELECT title FROM songs').fetchone()[0]
    def test_stage_is_independent_and_apply_keeps_safety_backup(self):
        write_json(self.source/'queue.json',{'format':'xstage.playlist','version':1,'tracks':[{'song_id':1,'path':'D:/songs/1.mid','singer':'A','key':3,'request_id':'old-session'}]})
        restore.stage_restore(self.source,self.data)
        self.assertEqual(self.title(),'ปัจจุบัน')
        write_json(self.source/'settings.json',{'title':'changed'})
        result=restore.apply_pending(self.data)
        self.assertEqual(self.title(),'เก่า')
        self.assertEqual(json.loads((self.data/'settings.json').read_text(encoding='utf-8'))['title'],'เก่า')
        q=json.loads((self.data/'queue.json').read_text(encoding='utf-8'));self.assertEqual(q[0]['key'],3);self.assertEqual(q[0]['request_id'],'')
        self.assertTrue((Path(result['safety'])/'songs.sqlite3').exists())
        self.assertIsNone(restore.apply_pending(self.data))
    def test_invalid_backup_does_not_change_current_data(self):
        write_json(self.source/'queue.json',[{'song_id':999}])
        with self.assertRaises(ValueError):restore.stage_restore(self.source,self.data)
        self.assertEqual(self.title(),'ปัจจุบัน');self.assertFalse((self.data/'restore-pending').exists())
    def test_mid_apply_failure_rolls_back_all_files(self):
        restore.stage_restore(self.source,self.data)
        original=restore.replace_file;calls=[]
        def fail(source,target):
            calls.append(target)
            if len(calls)==2:raise OSError('disk error')
            original(source,target)
        with patch.object(restore,'replace_file',side_effect=fail):
            with self.assertRaises(OSError):restore.apply_pending(self.data)
        self.assertEqual(self.title(),'ปัจจุบัน')
        self.assertEqual(json.loads((self.data/'settings.json').read_text(encoding='utf-8'))['title'],'ปัจจุบัน')
        self.assertEqual(json.loads((self.data/'queue.json').read_text(encoding='utf-8'))[0]['singer'],'ปัจจุบัน')
    def test_interrupted_apply_restores_original_before_startup(self):
        restore.stage_restore(self.source,self.data)
        original=restore.replace_file;calls=[]
        def interrupt(source,target):
            calls.append(target)
            if len(calls)==2:raise KeyboardInterrupt()
            original(source,target)
        with patch.object(restore,'replace_file',side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):restore.apply_pending(self.data)
        with self.assertRaisesRegex(ValueError,'ถูกขัดจังหวะ'):restore.apply_pending(self.data)
        self.assertEqual(self.title(),'ปัจจุบัน')
        self.assertFalse((self.data/'restore-pending').exists())
    def test_incomplete_and_corrupt_database_rejected(self):
        (self.source/'queue.json').unlink()
        with self.assertRaises(ValueError):restore.validate_backup(self.source)
        write_json(self.source/'queue.json',[])
        (self.source/'songs.sqlite3').write_bytes(b'not a database')
        with self.assertRaises(sqlite3.Error):restore.validate_backup(self.source)
