"""Unified V2 catalog validation and first-run private Drive contract tests."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/"songstudio-pc"))
import unified_catalog_v2 as c
from v2_native_publish import V2NativePublisher, PublishError, read_published_v2, write_published_v2
from test_songstudio_online_publish import FakeOnlineDrive
from online_publish import OnlinePublisher


def record(song_id="audio/0/00001",code="00001",format="m4a"):
    return {
      "id":song_id,"webSongId":song_id,"code":code,
      "title":"เพลงทดสอบ","artist":"นักร้อง",
      "media":{format:{"fileId":"drive_audio_1","path":"AUDIO/"+format.upper()+"/Songs/0/"+code+"."+format}},
      "lyrics":{"fileId":"drive_lyrics_1","path":"AUDIO/"+format.upper()+"/Lyrics/0/"+code+".json"}
    }


class UnifiedSongCatalogTests(unittest.TestCase):
    def test_cloud_song_and_published_catalog(self):
        one=record()
        doc={"schemaVersion":2,"format":c.CATALOG_FORMAT,"songs":[one]}
        self.assertEqual(c.validate_catalog(doc,cloud=True,expected_count=1),doc)
        self.assertEqual(c.validate_pointer({"schemaVersion":2,"generation":"v2_test",
           "catalogFileId":"abc123","songCount":1})["songCount"],1)

    def test_rejects_private_absolute_path_in_drive_catalog(self):
        bad=record();bad["media"]["m4a"]["localPath"]="C:/Private/Song.m4a"
        with self.assertRaises(c.CatalogValidationError):
            c.validate_catalog({"schemaVersion":2,"songs":[bad]},cloud=True)

    def test_local_pc_export_uses_same_semantic_fields(self):
        local=c.export_local_song({"id":12,"path":"C:/Music/00001.mp3",
           "format":"MP3","code":"00001","title":"Local","artist":"A"})
        self.assertEqual(local["media"]["mp3"]["localPath"],"C:/Music/00001.mp3")
        self.assertEqual(local["id"],"12")
        c.validate_song(local,cloud=False)
        with self.assertRaises(c.CatalogValidationError):c.validate_song(local,cloud=True)

    def test_rejects_corrupt_or_duplicate_catalog(self):
        with self.assertRaises(c.CatalogValidationError):
            c.validate_catalog({"schemaVersion":2,"songs":[record(),record()]},cloud=True)
        with self.assertRaises(c.CatalogValidationError):
            c.validate_pointer({"schemaVersion":2,"generation":"a","catalogFileId":"b","songCount":True})
        with self.assertRaises(c.CatalogValidationError):
            c.validate_song({**record(),"media":{"midi":{"fileId":"m","type":"ncn"}}},cloud=True)
        with self.assertRaises(c.CatalogValidationError):
            c.validate_song({**record(),"media":{"mp3":{"fileId":"a","path":"AUDIO/../etc"}}},cloud=True)


class LargeCatalogTests(unittest.TestCase):
    def setUp(self):
        self.drive=FakeOnlineDrive()
        root=self.drive.folder("root","XStageWeb")
        self.db=self.drive.folder(root,"DB")
        self.reader=lambda ident: json.loads(
            self.drive.items[str(ident)]["body"].decode("utf-8"))

    def songs(self,n):
        return {
            "S"+str(i):{
                "id":"S"+str(i),"code":str(i).zfill(5),
                "title":"ทดสอบ "+str(i),"artist":"",
                "media":{"mp3":{"fileId":"file_"+str(i)}},
                "lyrics":None
            } for i in range(n)
        }

    def test_2501_songs_use_bounded_shards_and_incremental_delta(self):
        records=self.songs(2501)
        pointer=write_published_v2(self.drive,self.db,records)
        self.assertNotIn("catalogFileId",pointer)
        self.assertEqual(len(pointer["catalogFiles"]),2)
        self.assertTrue(all(p["songCount"]<=2500 for p in pointer["catalogFiles"]))
        self.assertEqual(len(read_published_v2(self.reader,pointer)),2501)
        added=self.songs(2502)["S2501"]
        records[added["id"]]=added
        after=write_published_v2(self.drive,self.db,records,
                                 previous=pointer,revisions=[added])
        self.assertEqual(after["catalogFiles"],pointer["catalogFiles"])
        self.assertEqual(len(after["deltaFileIds"]),1)
        self.assertEqual(len(read_published_v2(self.reader,after)),2502)
        pointer_file=[x for x in self.drive.list_children(self.db)
                      if x["name"]=="current.json"]
        self.assertEqual(len(pointer_file),1)

    def test_failing_precommit_retains_old_active_pointer(self):
        old=write_published_v2(self.drive,self.db,self.songs(1))
        previous=[x for x in self.drive.list_children(self.db)
                  if x["name"]=="current.json"][0]
        def block():
            raise PublishError("Simulated concurrent update")
        with self.assertRaisesRegex(PublishError,"concurrent"):
            write_published_v2(self.drive,self.db,self.songs(2),
                               previous=old,revisions=None,precommit=block)
        self.assertEqual(self.reader(previous["id"]),old)
        self.assertEqual(len([x for x in self.drive.list_children(self.db)
                              if x["name"]=="current.json"]),1)

    def test_duplicate_code_never_uploads_or_changes_current_pointer(self):
        records=self.songs(2)
        records["S1"]["code"]=records["S0"]["code"]
        before=set(self.drive.items)
        with self.assertRaises(c.CatalogValidationError):
            write_published_v2(self.drive,self.db,records)
        self.assertEqual(set(self.drive.items),before)

    def test_pointer_rejects_duplicate_shard_and_large_delta_list(self):
        with self.assertRaises(c.CatalogValidationError):
            c.validate_pointer({"schemaVersion":2,"generation":"a","songCount":2,
                "catalogFiles":[{"fileId":"id","songCount":1},{"fileId":"id","songCount":1}]})
        with self.assertRaises(c.CatalogValidationError):
            c.validate_pointer({"schemaVersion":2,"generation":"a","songCount":1,
                "catalogFileId":"id","deltaFileIds":["d"]*2})


class FreshCloudV2Tests(unittest.TestCase):
    def setUp(self):
        self.drive=FakeOnlineDrive()
        self.pub=OnlinePublisher(self.drive)
        self.pub._json=lambda ident:json.loads(
            self.drive.items[str(ident)]["body"].decode("utf8"))

    def test_verified_empty_namespace_does_not_create_drive_root(self):
        before=len(self.drive.items)
        registry=self.pub.read_code_registry()
        self.assertEqual(registry["schemaVersion"],2)
        self.assertEqual(registry["songs"],[])
        self.assertEqual(len(self.drive.items),before)

    def test_first_run_creates_only_v2_pointer_once(self):
        first=self.pub.initialize_cloud_v2()
        self.assertTrue(first["created"])
        second=self.pub.initialize_cloud_v2()
        self.assertFalse(second["created"])
        self.assertEqual(first["generation"],second["generation"])
        root=next(x["id"] for x in self.drive.list_children("root")
                  if x["name"]=="XStageWeb")
        db=next(x["id"] for x in self.drive.list_children(root)
                if x["name"]=="DB")
        current=[x for x in self.drive.list_children(db) if x["name"]=="current.json"]
        self.assertEqual(len(current),1)
        pointer=self.pub._json(current[0]["id"])
        self.assertEqual(pointer["schemaVersion"],2)
        self.assertEqual(pointer["songCount"],0)
        self.assertEqual(len(read_published_v2(self.pub._json,pointer)),0)

if __name__=="__main__":
    unittest.main()
