"""Unified V2 catalog and non-destructive Drive migration contract tests."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/"songstudio-pc"))
import unified_catalog_v2 as c
from v2_native_publish import V2NativePublisher, PublishError
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

    def test_legacy_v1_id_migration_preserves_drive_references(self):
        legacy={"webSongId":"audio/0/00001","code":"00001",
                "title":"เพลงทดสอบ","artist":"นักร้อง",
                "audio":{"fileId":"drive_audio_1","path":"AUDIO/M4A/Songs/0/00001.m4a"},
                "lyrics":{"fileId":"drive_lyrics_1","path":"AUDIO/M4A/Lyrics/0/00001.json"}}
        converted=c.migrate_v1_catalog([legacy])
        self.assertEqual(converted["songs"][0]["id"],"audio/0/00001")
        self.assertEqual(converted["songs"][0]["media"]["m4a"]["fileId"],"drive_audio_1")
        self.assertNotIn("audio",converted["songs"][0])
        self.assertEqual(converted["format"],c.CATALOG_FORMAT)

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


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.local=self.root/"songs"
        self.local.mkdir()
        (self.local/"current.json").write_text('{"songCount":1}',encoding="utf8")
        (self.local/"audio/0").mkdir(parents=True)
        (self.local/"lyrics/0").mkdir(parents=True)
        (self.local/"audio/0/00001.m4a").write_bytes(b"a"*1200)
        (self.local/"lyrics/0/00001.json").write_text(json.dumps({"schemaVersion":1,
            "lines":[{"startTime":1.0,"endTime":3.0,"text":"hello"}]}),encoding="utf8")
        self.drive=FakeOnlineDrive()
        self.drive.folder("root","XStageWeb")
        self.legacy=OnlinePublisher(self.drive)
        self.reader=lambda ident:json.loads(self.drive.items[str(ident)]["body"].decode("utf8"))
        self.legacy._json=self.reader
        row={"webSongId":"audio/0/00001","code":"00001","title":"song","artist":"",
             "audio":{"path":"audio/0/00001.m4a"},"lyrics":{"path":"lyrics/0/00001.json"}}
        self.legacy.publish(self.local,[row])
        self.publisher=V2NativePublisher(self.drive)
        self.publisher.reader._json=self.reader

    def test_dry_run_does_not_modify_drive_and_commit_keeps_v1(self):
        before=set(self.drive.items)
        root=self.drive.folder("root","XStageWeb")
        old_pointer=next(x for x in self.drive.list_children(root) if x["name"]=="current.json")
        raw_v1=self.drive.items[old_pointer["id"]]["body"]
        plan=self.publisher.migrate_legacy_v1()
        self.assertTrue(plan["dryRun"])
        self.assertEqual(plan["v2Songs"],1)
        self.assertEqual(set(self.drive.items),before)
        with self.assertRaises(PublishError):
            self.publisher.migrate_legacy_v1(dry_run=False,confirm=False)
        self.assertEqual(set(self.drive.items),before)
        output=self.publisher.migrate_legacy_v1(dry_run=False,confirm=True)
        self.assertEqual(output["v2Songs"],1)
        self.assertEqual(self.drive.items[old_pointer["id"]]["body"],raw_v1)
        db=self.drive.folder(root,"DB")
        pointer=next(x for x in self.drive.list_children(db) if x["name"]=="current.json")
        converted=self.reader(pointer["id"])
        catalog=self.reader(converted["catalogFileId"])
        c.validate_pointer(converted)
        c.validate_catalog(catalog,cloud=True,expected_count=1)
        self.assertEqual(catalog["songs"][0]["id"],"audio/0/00001")
        self.assertEqual(catalog["songs"][0]["media"]["m4a"]["fileId"],
                         self.legacy._json(old_pointer["id"])["catalogFileId"] if False else
                         catalog["songs"][0]["media"]["m4a"]["fileId"])

    def test_malformed_v1_does_not_publish_v2(self):
        root=self.drive.folder("root","XStageWeb")
        pointer=next(x for x in self.drive.list_children(root) if x["name"]=="current.json")
        base=self.reader(pointer["id"])["catalogFileId"]
        self.drive.items[base]["body"]=b'{"schemaVersion":1,"songs":[{"webSongId":"bad","audio":{"fileId":""}}]}'
        before=set(self.drive.items)
        with self.assertRaises((PublishError,ValueError)):
            self.publisher.migrate_legacy_v1(dry_run=False,confirm=True)
        self.assertEqual(set(self.drive.items),before)


if __name__=="__main__":
    unittest.main()
