"""Regression suite for bulk intro/outro replacement of local generated lyrics."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, REPO / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bulk = load("songstudio-pc/lyric_text_groups.py", "xstage_phrase_groups_test")
export = load("songstudio-pc/song_export.py", "xstage_song_export_phrase_groups_test")


class LyricHeadTailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "workspace" / "songs"
        self.backups = self.base / "private-backups"
        self.src = []
        self.records = []
        self.starts = {}
        songs = [
            ("001", ["[X-Stage Karaoke]", "ผู้ผลิตรายการ", "เนื้อร้องหนึ่ง",
                     "เนื้อร้องสอง", "พบกันใหม่", "ขอบคุณที่รับฟัง"]),
            ("002", ["[X-Stage Karaoke]", "ผู้ผลิตรายการ", "เนื้อร้องสาม",
                     "เนื้อร้องสี่", "พบกันใหม่", "ขอบคุณที่รับฟัง"]),
            ("003", ["[X-Stage Karaoke]", "อีกข้อความ", "เนื้อร้องห้า",
                     "เนื้อร้องหก", "คนละข้อความ", "ขอบคุณที่รับฟัง"]),
            ("004", ["คำเกริ่นอื่น", "อีกข้อความ", "เนื้อร้องเจ็ด",
                     "เนื้อร้องแปด", "คนละข้อความ", "ขอบคุณที่รับฟัง"]),
        ]
        for code, lines in songs:
            audio = self.root / "audio" / "0" / (code + ".m4a")
            audio.parent.mkdir(parents=True, exist_ok=True)
            audio.write_bytes(b"fLaC!" * 3000)
            lrc_text = "".join(
                f"[00:{(i+1)*2:02d}.00]{line}\n" for i, line in enumerate(lines))
            lyric = export.save_lyrics(self.root, audio, lrc_text, code)
            self.src.append((audio, audio.read_bytes()))
            self.starts[code] = [entry["startTime"] for entry in
                                  json.loads(lyric.read_text(encoding="utf-8"))["lines"]]
            row = {
                "webSongId": "audio/0/"+code, "code":code,
                "title":"เพลง "+code, "artist":"ศิลปิน",
                "sourceFormat":"MP3", "mode":"original", "bucket":"0",
                "audio":{"path":"audio/0/"+code+".m4a","size":audio.stat().st_size},
                "lyrics":{"path":"lyrics/0/"+code+".json"},
                "vocals":None,
            }
            self.records.append(row)
        export.publish_batch(self.root, self.records)

    def tearDown(self):
        self.tmp.cleanup()

    def snapshot(self):
        return bulk.scan(self.root, export)

    def test_four_positions_group_separately_and_rank_by_frequency(self):
        s=self.snapshot()
        self.assertEqual(s["songs"],4)
        first=bulk.list_groups(s,"first")
        second=bulk.list_groups(s,"second")
        penultimate=bulk.list_groups(s,"penultimate")
        last=bulk.list_groups(s,"last")
        self.assertEqual(first["rows"][0]["text"],"[X-Stage Karaoke]")
        self.assertEqual(first["rows"][0]["count"],3)
        self.assertEqual(second["rows"][0]["count"],2)
        self.assertEqual(penultimate["rows"][0]["count"],2)
        self.assertEqual(last["rows"][0]["count"],4)
        self.assertEqual(len(first["rows"]),1,"Only repeated phrases by default")
        self.assertEqual(len(bulk.list_groups(s,"first",repeats_only=False)["rows"]),2)
        self.assertEqual(len(bulk.list_groups(s,"last",search="ไม่พบ")["rows"]),0)

    def test_preview_includes_count_and_song_samples(self):
        s=self.snapshot()
        ident=bulk.list_groups(s,"first")["rows"][0]["id"]
        result=bulk.preview(s,ident)
        self.assertEqual(result["label"],"บรรทัดแรก")
        self.assertEqual(len(result["examples"]),3)
        self.assertEqual(result["examples"][0]["code"],"001")

    def test_replace_changes_only_first_line_in_three_songs_and_can_undo(self):
        s=self.snapshot()
        group=bulk.list_groups(s,"first")["rows"][0]
        path=self.root/"lyrics"/"0"/"001.json"
        lrc=path.with_suffix(".lrc")
        old_json=path.read_bytes()
        old_lrc=lrc.read_bytes()
        result=bulk.apply(self.root,export,s,group["id"],"[เพลง X-Stage ใหม่]",
                          self.backups,expected_count=3)
        self.assertEqual(result["changedSongs"],3)
        self.assertEqual(result["changedFiles"],6)
        for idx,row in enumerate(self.records):
            lyric=self.root/row["lyrics"]["path"]
            doc=json.loads(lyric.read_text(encoding="utf-8"))
            expected="[เพลง X-Stage ใหม่]" if idx<3 else "คำเกริ่นอื่น"
            self.assertEqual(doc["lines"][0]["text"],expected)
            self.assertEqual([x["startTime"] for x in doc["lines"]],
                             self.starts[row["code"]])
            self.assertEqual(doc["lines"][1]["text"],
                             "ผู้ผลิตรายการ" if idx<2 else "อีกข้อความ")
            self.assertIn(expected,lyric.with_suffix(".lrc").read_text(encoding="utf-8"))
            self.assertEqual(doc["rawLrc"],lyric.with_suffix(".lrc").read_text(encoding="utf-8"))
            self.assertTrue(export.record_is_complete(self.root,row))
        for path,data in self.src:self.assertEqual(path.read_bytes(),data)
        self.assertEqual(bulk.latest_backup(self.backups,self.root)["id"],
                         result["backupId"])
        restored=bulk.undo(self.backups,self.root,result["backupId"])
        self.assertEqual(restored["restoredSongs"],3)
        self.assertEqual((self.root/"lyrics"/"0"/"001.json").read_bytes(),old_json)
        self.assertEqual(lrc.read_bytes(),old_lrc)
        self.assertIsNone(bulk.latest_backup(self.backups,self.root))

    def test_each_position_replaces_only_its_own_line(self):
        for position,new_text in (
            ("second","ใหม่บรรทัดสอง"),
            ("penultimate","ใหม่ก่อนสุดท้าย"),
            ("last","ใหม่บรรทัดท้าย"),
        ):
            snap=self.snapshot()
            group=bulk.list_groups(snap,position)["rows"][0]
            original={row["code"]:
                      json.loads((self.root/row["lyrics"]["path"]).read_text(encoding="utf-8"))
                      for row in self.records}
            output=bulk.apply(self.root,export,snap,group["id"],new_text,
                              self.backups,expected_count=group["count"])
            index=bulk.POSITIONS[position][0]
            for row in self.records:
                doc=json.loads((self.root/row["lyrics"]["path"]).read_text(encoding="utf-8"))
                old=original[row["code"]]
                if old["lines"][index]["text"]==group["text"]:
                    self.assertEqual(doc["lines"][index]["text"],new_text)
                else:
                    self.assertEqual(doc["lines"][index]["text"],old["lines"][index]["text"])
                for i in range(len(old["lines"])):
                    if i!=index%len(old["lines"]):
                        self.assertEqual(doc["lines"][i],old["lines"][i])
            bulk.undo(self.backups,self.root,output["backupId"])

    def test_cancel_before_commit_and_stale_catalog_do_not_change_files(self):
        snap=self.snapshot()
        group=bulk.list_groups(snap,"first")["rows"][0]
        initial=(self.root/"lyrics"/"0"/"001.json").read_bytes()
        with self.assertRaisesRegex(ValueError,"จำนวนเพลง"):
            bulk.apply(self.root,export,snap,group["id"],"ใหม่",self.backups,
                       expected_count=100)
        stopped=threading.Event()
        stopped.set()
        with self.assertRaisesRegex(RuntimeError,"ยกเลิก"):
            bulk.apply(self.root,export,snap,group["id"],"ใหม่",self.backups,
                       expected_count=3,cancelled=stopped)
        self.assertEqual((self.root/"lyrics"/"0"/"001.json").read_bytes(),initial)
        export.publish_batch(self.root,self.records)
        with self.assertRaisesRegex(ValueError,"เปลี่ยนแปลง"):
            bulk.apply(self.root,export,snap,group["id"],"ใหม่",self.backups,
                       expected_count=3)
        self.assertEqual((self.root/"lyrics"/"0"/"001.json").read_bytes(),initial)

    def test_undo_refuses_to_overwrite_subsequent_user_edits(self):
        snap=self.snapshot()
        group=bulk.list_groups(snap,"first")["rows"][0]
        result=bulk.apply(self.root,export,snap,group["id"],"ข้อความใหม่",
                          self.backups,expected_count=3)
        path=self.root/"lyrics"/"0"/"001.json"
        path.write_text(path.read_text(encoding="utf-8")+"\n",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"แก้ไขภายหลัง"):
            bulk.undo(self.backups,self.root,result["backupId"])
        self.assertIn("ข้อความใหม่",path.read_text(encoding="utf-8"))

    def test_inconsistent_lrc_and_short_lyrics_are_excluded(self):
        lrc=self.root/"lyrics"/"0"/"001.lrc"
        lrc.write_text("not synced to JSON",encoding="utf-8")
        snap=self.snapshot()
        self.assertEqual(snap["songs"],3)
        self.assertEqual(snap["skippedInvalid"],1)
        self.assertEqual(bulk.list_groups(snap,"first")["rows"][0]["count"],2)

    def test_empty_or_multiline_text_is_rejected(self):
        snap=self.snapshot()
        g=bulk.list_groups(snap,"first")["rows"][0]
        for value in ("", "two\nlines", "x"*401, g["text"]):
            with self.subTest(value=value[:10]):
                with self.assertRaises(ValueError):
                    bulk.apply(self.root,export,snap,g["id"],value,self.backups,
                               expected_count=g["count"])
        self.assertFalse(list(self.backups.glob("*.zip"))) if self.backups.exists() else None


if __name__=="__main__":
    unittest.main()
