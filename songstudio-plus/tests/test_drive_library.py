"""Integration contracts for XStageKaraoke Desktop Drive song acquisition."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import drive_library as drive
import plus_core as core


class DriveLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.root=self.base/"Drive mount"/"XStageKaraoke"
        for name in ("SONGS","DB","SOUNDFONT"):
            (self.root/name).mkdir(parents=True)
        self.workspace=self.base/"Studio SQLite"
        self.dest=self.base/"Local song downloads"
        core.init(self.workspace)

    def add(self,relative,body):
        path=self.root/"SONGS"/relative
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(body)
        return path

    def test_only_current_root_is_accepted_and_original_sqlite_is_untouched(self):
        self.assertEqual(drive.resolve_root(str(self.root)),self.root)
        self.assertEqual(drive.resolve_root(str(self.root/"SONGS")),self.root)
        with self.assertRaisesRegex(ValueError,"XStageKaraoke"):
            drive.resolve_root(str(self.base))
        (self.root/"DB"/"current.sqlite3").write_bytes(b"USER-OWNED-DB")
        media=self.add("AUDIO/MP3/SONG/7/74649.mp3",b"ID3"+b"audio"*20)
        result=drive.download_and_import(self.workspace,self.root,destination=self.dest)
        self.assertEqual(result["downloaded"],1)
        self.assertEqual(core.stats(self.workspace)["songs"],1)
        self.assertEqual((self.root/"DB"/"current.sqlite3").read_bytes(),b"USER-OWNED-DB")
        self.assertEqual(media.read_bytes(),b"ID3"+b"audio"*20)
        self.assertFalse((self.dest/"DB").exists())
        self.assertEqual((self.dest/"SONGS"/"AUDIO/MP3/SONG/7/74649.mp3").read_bytes(),media.read_bytes())

    def test_exact_duplicate_is_skipped_and_changed_bytes_are_downloaded(self):
        media=self.add("AUDIO/MP3/SONG/A/ABC.mp3",b"ID3"+b"example"*20)
        first=drive.download_and_import(self.workspace,self.root,destination=self.dest)
        self.assertEqual(first["downloaded"],1)
        second=drive.download_and_import(self.workspace,self.root,destination=self.dest)
        self.assertEqual(second["downloaded"],0)
        self.assertEqual(second["unchanged"],1)
        self.assertEqual(core.stats(self.workspace)["songs"],1)
        media.write_bytes(b"ID3"+b"updated"*20)
        third=drive.download_and_import(self.workspace,self.root,destination=self.dest)
        self.assertEqual(third["downloaded"],1)
        self.assertEqual((self.dest/"SONGS"/"AUDIO/MP3/SONG/A/ABC.mp3").read_bytes(),media.read_bytes())

    def test_hashed_lyrics_json_is_matched_and_imported(self):
        code="74649"
        source=self.add("AUDIO/MP3/SONG/7/"+code+"-1234567890abcdef.mp3",b"ID3"+b"music"*20)
        doc={"schemaVersion":1,"songCode":code,"title":"ทดสอบเพลง",
             "artist":"ทดสอบศิลปิน",
             "lines":[{"text":"สวัสดี","startTime":1.0,"endTime":3.0,
                       "syllables":[{"text":"สวัสดี","start":1.0,"duration":2.0}]}]}
        self.add("AUDIO/MP3/LYRICS/7/"+code+"-fedcba0987654321.json",
                 json.dumps(doc,ensure_ascii=False).encode("utf-8"))
        companion=core.companion_candidates(source)
        self.assertTrue(companion[".json"])
        self.assertEqual(core.document_for(source,companion)["metadata"]["title"],"ทดสอบเพลง")
        result=drive.download_and_import(self.workspace,self.root,destination=self.dest)
        self.assertEqual(result["downloaded"],2)
        with core.connect(self.workspace) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM xstage_songs").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT count(*) FROM xstage_lyric_versions").fetchone()[0],1)

    def test_ncn_files_are_paired_from_separate_hashed_folders(self):
        source=self.add("MIDI/NCN/SONG/T/test-1234567890abcdef.mid",b"MThd"+b"x"*40)
        lyr=self.add("MIDI/NCN/LYR/T/test-1111111111111111.lyr",b"text")
        cur=self.add("MIDI/NCN/CUR/T/test-2222222222222222.cur",b"cur")
        doc={"schemaVersion":1,"songCode":"test","lines":[
             {"text":"ทดสอบ","startTime":0,"endTime":2}]}
        self.add("MIDI/NCN/LYRICS/T/test-3333333333333333.json",
                 json.dumps(doc,ensure_ascii=False).encode())
        companions=core.companion_candidates(source)
        self.assertEqual(companions[".lyr"],lyr)
        self.assertEqual(companions[".cur"],cur)
        self.assertIsNotNone(companions[".json"])
        self.assertEqual(core.ncn_missing_companions(companions),[])

    def test_ambiguous_json_never_silently_chooses_a_random_song(self):
        source=self.add("AUDIO/MP3/SONG/A/ABC-1234567890abcdef.mp3",b"ID3")
        self.add("AUDIO/MP3/LYRICS/A/ABC-2222222222222222.json",b"{}")
        self.add("AUDIO/MP3/LYRICS/A/ABC-3333333333333333.json",b"{}")
        self.assertIsNone(core.companion_candidates(source)[".json"])

    def test_partial_download_is_removed_after_cancellation(self):
        signal=threading.Event()
        signal.set()
        self.add("AUDIO/MP3/SONG/A/track.mp3",b"ID3"+b"song"*20)
        result=drive.download_and_import(self.workspace,self.root,cancel=signal,
                                         destination=self.dest)
        self.assertTrue(result["cancelled"])
        self.assertEqual(list(self.dest.rglob("*.part")),[])
        self.assertEqual(core.stats(self.workspace)["songs"],0)

    def test_incomplete_cloud_json_does_not_claim_verified_timing(self):
        raw={"schemaVersion":1,"lines":[{"text":"line","startTime":1}]}
        filename=self.base/"missing-end.json"
        filename.write_text(json.dumps(raw))
        with self.assertRaisesRegex(ValueError,"เวลาเริ่ม-จบ"):
            core._cloud_json_document(filename)


if __name__=="__main__":
    unittest.main()
