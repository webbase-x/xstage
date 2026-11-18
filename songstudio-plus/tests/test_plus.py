"""End-to-end regressions for the entirely separate X-Stage Song Studio Plus."""
from __future__ import annotations
import importlib
import os
import sqlite3
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import plus_core as plus

def varlen(n):
    out=[n&127]
    n >>=7
    while n:
        out.insert(0,0x80|(n&127)); n>>=7
    return bytes(out)

def midi():
    # 20 seconds of legal MIDI events to bound NCN lyric timing.
    track=(b"\x00\xff\x51\x03\x07\xa1\x20"+
           b"\x00\x90\x3c\x64"+
           varlen(480*20)+b"\x80\x3c\x00"+
           b"\x00\xff\x2f\x00")
    return (b"MThd"+struct.pack(">IHHH",6,0,1,480)+
            b"MTrk"+struct.pack(">I",len(track))+track)

class PlusTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.base=Path(self.temp.name)
        self.workspace=self.base/"workspace"
        self.src=self.base/"input"
        self.src.mkdir()
        plus.init(self.workspace)

    def tearDown(self):
        self.temp.cleanup()

    def put(self,name,data):
        p=self.src/name
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(data)
        return p

    def lrc(self,path,text="[00:01.00]By Nick >>>\n[00:05.00]Next line\n"):
        (path.parent/(path.stem+".lrc")).write_text(text,encoding="utf-8")

    def test_schema_all_tables_prefixed_and_separate_from_legacy(self):
        with plus.connect(self.workspace) as db:
            names=[row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        self.assertTrue(names)
        self.assertTrue(all(x.startswith("xstage_") or x.startswith("sqlite_") for x in names))
        self.assertFalse((self.workspace/"DB"/"song-registry.sqlite3").exists())

    def test_same_media_different_name_or_source_reuses_media(self):
        one=self.put("PC_A/00001.mp3",b"\xff\xfb"+"A".encode()*4000)
        self.lrc(one)
        two=self.put("PC_B/99999.mp3",one.read_bytes())
        self.lrc(two,"[00:01.00]Nick Different\n[00:05.00]Next line\n")
        summary=plus.import_folder(self.workspace,self.src)
        self.assertEqual(summary["files_new"],1)
        self.assertEqual(summary["media_duplicates"],1)
        report=plus.stats(self.workspace)
        self.assertEqual(report["songs"],1)
        self.assertEqual(report["media"],1)
        self.assertEqual(report["lyrics"],2)
        rows=plus.songs(self.workspace)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["code"],1)
        self.assertEqual(len(list((self.workspace/"SOURCE").rglob("*.mp3"))),1)

    def test_rerun_import_does_not_duplicate_media_or_lyrics(self):
        path=self.put("track.mp3",b"MP3-CONTENT"*500)
        self.lrc(path)
        plus.import_folder(self.workspace,self.src)
        before=plus.stats(self.workspace)
        result=plus.import_folder(self.workspace,self.src)
        after=plus.stats(self.workspace)
        self.assertEqual(result["files_new"],0)
        self.assertEqual(result["lyrics_new"],0)
        self.assertEqual({k:before[k] for k in ("songs","media","lyrics")},
                         {k:after[k] for k in ("songs","media","lyrics")})

    def test_same_filename_different_bytes_get_unique_code(self):
        self.put("A/00001.mid",midi())
        self.put("B/00001.mid",midi()+b"extension")
        out=plus.import_folder(self.workspace,self.src)
        self.assertEqual(out["files_new"],2)
        songs=plus.songs(self.workspace)
        self.assertEqual(len(songs),2)
        self.assertEqual(len({x["code"] for x in songs}),2)

    def test_group_replace_and_undo_preserve_independent_line_bounds(self):
        old=["[00:02.00].....nick.....\n[00:06.00]Keep A\n",
             "[00:09.00]Nick ......\n[00:15.00]Keep B\n",
             "[00:18.00]By  nick >>>\n[00:25.00]Keep C\n"]
        for n,lyrics in enumerate(old):
            path=self.put(f"track{n}.mp3",bytes([n+10])*1000)
            self.lrc(path,lyrics)
        plus.import_folder(self.workspace,self.src)
        found=plus.groups(self.workspace,"NiCk")
        self.assertEqual(len(found),3)
        self.assertEqual(sorted(x["lines"] for x in found),[1,1,1])
        keys=[x["group_key"] for x in found]
        plan=plus.plan_edit(self.workspace,"Nick",keys)
        self.assertEqual((plan["songs"],plan["lines"]),(3,3))
        before={}
        for song in plus.songs(self.workspace):
            with plus.connect(self.workspace) as db:
                v=db.execute("SELECT id FROM xstage_lyric_versions WHERE song_id=? AND is_current=1",
                             (song["id"],)).fetchone()
                before[song["id"]]=plus.get_version_lines(db,v["id"])
        result=plus.replace_groups(self.workspace,"Nick",keys,"x-stage karaoke",3)
        self.assertEqual((result["changed_songs"],result["changed_lines"]),(3,3))
        for song in plus.songs(self.workspace):
            with plus.connect(self.workspace) as db:
                v=db.execute("SELECT * FROM xstage_lyric_versions WHERE song_id=? AND is_current=1",
                             (song["id"],)).fetchone()
                after=plus.get_version_lines(db,v["id"])
            self.assertEqual(after[0][0]["text"],"x-stage karaoke")
            self.assertEqual(after[0][0]["start_time"],before[song["id"]][0][0]["start_time"])
            self.assertEqual(after[0][0]["end_time"],before[song["id"]][0][0]["end_time"])
            self.assertEqual(after[1][0]["text"],before[song["id"]][1][0]["text"])
            self.assertEqual(after[1][0]["start_time"],before[song["id"]][1][0]["start_time"])
            self.assertEqual(after[0][0]["timing_status"],"estimated")
        self.assertEqual(plus.undo_edit(self.workspace,result["batch"])["restored_songs"],3)
        self.assertEqual(len(plus.groups(self.workspace,"Nick")),3)

    def test_xmedia_binary_stores_source_and_lyrics_without_sidecar(self):
        path=self.put("001.mp3",b"FAKE-MEDIA-TEST"*999)
        self.lrc(path)
        plus.import_folder(self.workspace,self.src)
        song=plus.songs(self.workspace)[0]
        result=plus.build_song(self.workspace,song["id"])
        output=Path(result["path"])
        self.assertEqual(output.suffix,".xmp3")
        self.assertEqual(output.parent.parent.name,"XMP3")
        info=plus.inspect_xfile(output,True)
        self.assertEqual(info["media_sha256"],plus.digest(path))
        self.assertEqual(output.read_bytes()[-path.stat().st_size:],path.read_bytes())
        self.assertTrue(plus.build_song(self.workspace,song["id"])["skipped"])
        self.assertEqual(list(self.workspace.rglob("*.json")),[])
        self.assertEqual(list(self.workspace.rglob("*.xsk")),[])

    def test_midi_ncn_original_bytes_and_lyrics_from_companions(self):
        p=self.put("NCN/Song/0/00001.mid",midi())
        self.put("NCN/Lyrics/0/00001.lyr",
                 "เพลงทดสอบ\nศิลปินทดสอบ\nC\n\nNick\n".encode("cp874"))
        self.put("NCN/Cursor/0/00001.cur",struct.pack("<5H",0,1,2,3,4))
        info=plus.import_folder(self.workspace,self.src)
        self.assertEqual(info["failures"],0)
        rows=plus.songs(self.workspace)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["title"],"เพลงทดสอบ")
        self.assertEqual(rows[0]["artist"],"ศิลปินทดสอบ")
        self.assertEqual(len(plus.groups(self.workspace,"Nick")),1)
        built=plus.build_song(self.workspace,rows[0]["id"])
        self.assertEqual(Path(built["path"]).suffix,".xmid")
        self.assertEqual(plus.inspect_xfile(built["path"],True)["media_sha256"],plus.digest(p))

    def test_missing_lyrics_not_claimed_as_karaoke(self):
        self.put("no-lyrics.mp3",b"audio"*200)
        plus.import_folder(self.workspace,self.src)
        item=plus.songs(self.workspace)[0]
        self.assertIsNone(item["version_id"])
        with self.assertRaisesRegex(ValueError,"เนื้อร้อง"):
            plus.build_song(self.workspace,item["id"])

    def test_sha256_changes_when_source_file_changes(self):
        path=self.put("00001.mp3",b"A"*1000)
        plus.import_folder(self.workspace,self.src)
        path.write_bytes(b"B"*1000)
        again=plus.import_folder(self.workspace,self.src)
        self.assertEqual(again["files_new"],1)
        self.assertEqual(plus.stats(self.workspace)["media"],2)

if __name__=="__main__":
    unittest.main()
