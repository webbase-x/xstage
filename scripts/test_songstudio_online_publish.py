"""XStageWeb V2-only Song Studio/Google Drive tests (all requests mocked).

Exercises production media publisher and private V2 download planner. No
OAuth secrets or actual Drive accounts are accessed by these tests.
"""
from __future__ import annotations
import hashlib
import io
import json
import sys
import tempfile
import urllib.parse
import unittest
from pathlib import Path
from unittest.mock import patch

import test_songstudio_drive_roundtrip as roundtrip
from test_songstudio_drive_roundtrip import FakePrivateDrive

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"songstudio-pc"))
import online_publish as online
from v2_native_publish import read_published_v2


class FakeOnlineDrive(FakePrivateDrive):
    def api(self, route, query=None, *, method="GET", data=None):
        if route.startswith("/files/") and method=="GET":
            return dict(self.items[route.split("/")[-1]]["metadata"])
        raise AssertionError("Unexpected Google API call: "+route)


class V2OnlinePublishTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.root=self.base/"songs"
        self.root.mkdir()
        (self.root/"current.json").write_text('{"songCount":1}',encoding="utf8")
        self.drive=FakeOnlineDrive()
        self.publisher=online.OnlinePublisher(self.drive)
        self.publisher._json=self.read_json

    def read_json(self,ident):
        return json.loads(self.drive.items[str(ident)]["body"].decode("utf-8"))

    def make_song(self,code="00001",audio=b"A"*4500,text="Hello"):
        folder=code[0].upper()
        m4a="audio/"+folder+"/"+code+".m4a"
        lyric="lyrics/"+folder+"/"+code+".json"
        for path in (m4a,lyric):
            (self.root/path).parent.mkdir(parents=True,exist_ok=True)
        (self.root/m4a).write_bytes(audio)
        (self.root/lyric).write_text(json.dumps({
            "schemaVersion":1,"lines":[{"startTime":1,"endTime":5,"text":text}]
        },ensure_ascii=False),encoding="utf8")
        return {"webSongId":"audio/"+folder+"/"+code,
                "code":code,"title":"เพลง "+code,"artist":"ศิลปิน",
                "audio":{"path":m4a},"lyrics":{"path":lyric}}

    def root_id(self):
        roots=[x for x in self.drive.list_children("root") if x["name"]=="XStageWeb"]
        self.assertEqual(len(roots),1)
        return roots[0]["id"]

    def pointer(self):
        root=self.root_id()
        db=next(x["id"] for x in self.drive.list_children(root) if x["name"]=="DB")
        pointers=[x for x in self.drive.list_children(db) if x["name"]=="current.json"]
        self.assertEqual(len(pointers),1)
        return self.read_json(pointers[0]["id"]),pointers[0]["id"],db

    def published(self):
        pointer,_,_=self.pointer()
        return read_published_v2(self.read_json,pointer)

    def drive_response(self,url,**kwargs):
        fileid=urllib.parse.urlsplit(url).path.rsplit("/",1)[-1]
        return io.BytesIO(self.drive.items[fileid]["body"])

    def test_path_contract(self):
        route=online.cloud_media_path
        self.assertEqual(str(route("audio/0/a.m4a",code="00001")),"AUDIO/M4A/Songs/0/a.m4a")
        self.assertEqual(str(route("lyrics/0/a.json",role="lyrics",code="00001")),
                         "AUDIO/M4A/Lyrics/0/a.json")
        self.assertEqual(str(route("lyrics/0/a.json","MP3",role="lyrics",code="00001")),
                         "AUDIO/MP3/Lyrics/0/a.json")
        self.assertEqual(str(route("music/0/a.mid","NCN",code="B0001")),
                         "MIDI/NCN/Songs/B/a.mid")
        for invalid in ("../escape.m4a","/absolute.m4a","audio//bad.mp3","audio\\bad.mp3"):
            with self.subTest(path=invalid),self.assertRaises(online.PublishError):
                route(invalid)

    def test_fresh_google_drive_auto_creates_only_v2(self):
        row=self.make_song()
        before=len(self.drive.items)
        preview=self.publisher.read_code_registry()
        self.assertTrue(preview["visible"])
        self.assertEqual(preview["songs"],[])
        self.assertEqual(len(self.drive.items),before)
        outcome=self.publisher.publish(self.root,[row])
        self.assertTrue(outcome["published"])
        self.assertEqual(outcome["newSongs"],1)
        pointer,pointer_id,db=self.pointer()
        self.assertEqual(pointer["schemaVersion"],2)
        self.assertEqual(pointer["songCount"],1)
        self.assertEqual(len(self.published()),1)
        self.assertEqual(self.drive.upload_order[-1],"current.json")
        root=self.root_id()
        self.assertFalse(any(x["name"]=="current.json" for x in self.drive.list_children(root)))
        data=next(iter(self.published().values()))
        self.assertEqual(data["id"],row["webSongId"])
        self.assertEqual(data["media"]["m4a"]["fileId"] in self.drive.items,True)
        self.assertTrue(data["media"]["m4a"]["path"].startswith("AUDIO/M4A/Songs/0/"))
        self.assertTrue(data["lyrics"]["path"].startswith("AUDIO/M4A/Lyrics/0/"))
        self.assertNotIn(str(self.base),json.dumps(data,ensure_ascii=False))
        self.assertNotIn("StageWeb",json.dumps(pointer))

    def test_initialize_empty_v2_can_be_repeated_without_reset(self):
        before=len(self.drive.items)
        p=self.publisher.initialize_cloud_v2()
        self.assertTrue(p["created"])
        self.assertEqual(p["totalSongs"],0)
        pointer,_,_=self.pointer()
        self.assertEqual(pointer["songCount"],0)
        names={x["name"] for x in self.drive.list_children(self.root_id())}
        self.assertTrue({"DB","AUDIO","VIDEO","MIDI"}.issubset(names))
        stable=self.publisher.initialize_cloud_v2()
        self.assertFalse(stable["created"])
        self.assertEqual(stable["generation"],p["generation"])
        self.assertEqual(len(self.published()),0)
        self.assertGreater(len(self.drive.items),before)

    def test_duplicate_upload_is_unchanged(self):
        row=self.make_song()
        self.publisher.publish(self.root,[row])
        prior, pointer_id, _=self.pointer()
        files=len(self.drive.items)
        outcome=self.publisher.publish(self.root,[row])
        self.assertEqual(outcome["duplicates"],1)
        self.assertFalse(outcome["published"])
        self.assertEqual(len(self.drive.items),files)
        self.assertEqual(self.pointer()[1],pointer_id)
        self.assertEqual(self.pointer()[0]["generation"],prior["generation"])

    def test_same_code_changed_audio_is_conflict_without_mutation(self):
        row=self.make_song()
        self.publisher.publish(self.root,[row])
        before=self.published()
        pointer,_,_=self.pointer()
        (self.root/row["audio"]["path"]).write_bytes(b"B"*4500)
        outcome=self.publisher.publish(self.root,[row])
        self.assertEqual(outcome["conflicts"],1)
        self.assertFalse(outcome["published"])
        self.assertEqual(self.published(),before)
        self.assertEqual(self.pointer()[0]["generation"],pointer["generation"])

    def test_same_audio_changed_lyric_keeps_file_id(self):
        row=self.make_song()
        self.publisher.publish(self.root,[row])
        old=self.published()[row["webSongId"]]
        (self.root/row["lyrics"]["path"]).write_text(json.dumps({
            "schemaVersion":1,"lines":[{"startTime":1,"endTime":5,"text":"NEW"}]
        }),encoding="utf8")
        result=self.publisher.publish(self.root,[row])
        fresh=self.published()[row["webSongId"]]
        self.assertEqual(result["updatedSongs"],1)
        self.assertEqual(old["media"]["m4a"]["fileId"],fresh["media"]["m4a"]["fileId"])
        self.assertNotEqual(old["lyrics"]["fileId"],fresh["lyrics"]["fileId"])
        self.assertEqual(len(self.pointer()[0].get("deltaFileIds",[])),1)

    def test_two_distinct_codes_identical_bytes_do_not_duplicate(self):
        a=self.make_song("00001")
        b=self.make_song("00002")
        # Both songs have the same media/lyrics but use different codes.
        self.publisher.publish(self.root,[a])
        outcome=self.publisher.publish(self.root,[b])
        self.assertEqual(outcome["duplicates"],1)
        self.assertEqual(len(self.published()),1)

    def test_interrupted_initial_upload_never_publishes_pointer(self):
        row=self.make_song()
        original=self.drive.upload_file
        def broken(parent,path,name,**opts):
            if "Lyrics" in str(path):
                raise RuntimeError("Simulated Drive loss")
            return original(parent,path,name,**opts)
        with patch.object(self.drive,"upload_file",side_effect=broken):
            with self.assertRaises(RuntimeError):
                self.publisher.publish(self.root,[row])
        root=self.root_id()
        db=next(x["id"] for x in self.drive.list_children(root) if x["name"]=="DB")
        self.assertFalse(any(x["name"]=="current.json" for x in self.drive.list_children(db)))
        self.publisher.publish(self.root,[row])
        self.assertEqual(len(self.published()),1)
        self.assertEqual(len([x for x in self.drive.items.values() if
          x["metadata"]["name"].endswith(".m4a")]),1)

    def test_v2_download_and_db_plan_keep_private_tree(self):
        row=self.make_song()
        self.publisher.publish(self.root,[row])
        with patch.object(roundtrip.drive,"_request",side_effect=self.drive_response):
            songs=self.drive.download_library(self.base/"restored","songs")
            database=self.drive.download_library(self.base/"db-only","db")
        self.assertEqual(songs["source"],"XStageWeb")
        self.assertEqual(database["source"],"XStageWeb")
        path=Path(songs["path"])
        self.assertTrue((path/"DB/current.json").is_file())
        self.assertEqual(len(list(path.rglob("*.m4a"))),1)
        self.assertEqual(len(list(path.rglob("*.json")))>=3,True)
        dbpath=Path(database["path"])
        self.assertTrue((dbpath/"DB/current.json").is_file())
        self.assertFalse(list(dbpath.rglob("*.m4a")))

    def test_v2_download_rejects_tampering_before_writing(self):
        row=self.make_song()
        self.publisher.publish(self.root,[row])
        pointer,_,db=self.pointer()
        base_id=pointer.get("catalogFileId")
        self.drive.items[base_id]["body"]=b'{"schemaVersion":2,"songs":[]}'
        with patch.object(roundtrip.drive,"_request",side_effect=self.drive_response):
            with self.assertRaises(Exception):
                self.drive.download_library(self.base/"tampered","songs")
        self.assertFalse((self.base/"tampered"/"XStageWeb").exists())

    def test_download_does_not_create_a_missing_cloud_root(self):
        before=len(self.drive.items)
        with self.assertRaises(Exception):
            self.drive.download_library(self.base/"missing","songs")
        self.assertEqual(len(self.drive.items),before)


if __name__=="__main__":
    unittest.main()
