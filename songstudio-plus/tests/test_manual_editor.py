"""End-to-end tests for Menu 05 lyric repair and Menu 06 build eligibility."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import plus_core as core
import manual_editor as edit


class ManualKaraokeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.base=Path(self.temp.name)
        self.src=self.base/"source"
        self.src.mkdir()
        self.workspace=self.base/"workspace"
        (self.src/"00001.mp3").write_bytes(b"\xff\xfb"+b"TRACK"*100)
        summary=core.import_folder(self.workspace,self.src)
        self.assertEqual(summary["files_new"],1)
        self.song=core.songs(self.workspace)[0]
        edit.init(self.workspace)

    def tearDown(self):
        self.temp.cleanup()

    def test_empty_media_is_listed_without_fake_lyrics(self):
        queue=edit.queue(self.workspace)
        self.assertEqual(queue["total"],1)
        self.assertEqual(queue["rows"][0]["review_status"],"missing")
        self.assertEqual(edit.detail(self.workspace,self.song["id"])["lines"],[])
        self.assertEqual(edit.approved_build_ids(self.workspace),[])
        self.assertEqual(edit.ready_count(self.workspace),0)

    def test_partial_draft_is_saved_and_complete_manual_version_can_be_approved(self):
        song_id=self.song["id"]
        partial=edit.save(self.workspace,song_id,None,[
            {"text":"hello","start":1,"end":3,
             "segments":["hel","lo"],"starts":[1,2]},
            {"text":"world","start":None,"end":None,
             "segments":[],"starts":[]},
        ])
        self.assertFalse(partial["complete"])
        self.assertEqual(partial["saved_lines"],1)
        self.assertTrue(partial["version_id"])
        self.assertEqual(edit.detail(self.workspace,song_id)["lines"][1]["text"],"world")
        self.assertEqual(edit.queue(self.workspace)["rows"][0]["review_status"],"incomplete")
        with self.assertRaisesRegex(ValueError,"ยังไม่ครบ"):
            edit.approve(self.workspace,song_id,partial["version_id"])
        complete=edit.save(self.workspace,song_id,partial["version_id"],[
            {"text":"hello","start":1,"end":3,
             "segments":["hel","lo"],"starts":[1,2]},
            {"text":"world","start":4,"end":6,
             "segments":["wor","ld"],"starts":[4,5]},
        ])
        self.assertTrue(complete["complete"])
        self.assertEqual(edit.queue(self.workspace)["rows"][0]["review_status"],"review")
        self.assertEqual(edit.ready_count(self.workspace),0)
        self.assertEqual(edit.approved_build_ids(self.workspace),[])
        edit.approve(self.workspace,song_id,complete["version_id"])
        self.assertEqual(edit.ready_count(self.workspace),1)
        self.assertEqual(edit.approved_build_ids(self.workspace),[song_id])
        self.assertEqual(edit.approved_build_ids(self.workspace,exclude=[song_id]),[])
        self.assertEqual(edit.annotate_rows(self.workspace,core.songs(self.workspace))[0]["manual_status"],"ready")
        self.assertEqual(edit.queue(self.workspace)["total"],0)
        self.assertEqual(edit.queue(self.workspace,filter="all")["total"],1)
        with core.connect(self.workspace) as db:
            count=db.execute("SELECT COUNT(*) FROM xstage_lyric_versions").fetchone()[0]
            self.assertEqual(count,2)

    def test_skip_is_version_specific_and_does_not_delete_lyrics(self):
        sid=self.song["id"]
        edit.skip(self.workspace,sid,None)
        self.assertEqual(edit.queue(self.workspace)["total"],0)
        self.assertEqual(edit.queue(self.workspace,filter="skipped")["total"],1)
        result=edit.save(self.workspace,sid,None,[{"text":"text","start":None,
            "end":None,"segments":[],"starts":[]}])
        self.assertFalse(result["complete"])
        self.assertEqual(edit.queue(self.workspace)["total"],1)
        self.assertEqual(edit.detail(self.workspace,sid)["lines"][0]["text"],"text")

    def test_reject_fabricated_or_mismatched_timing(self):
        sid=self.song["id"]
        with self.assertRaisesRegex(ValueError,"จำนวนคำกับเวลาปาด"):
            edit.save(self.workspace,sid,None,[{"text":"สวัสดี",
                "start":1,"end":2,"segments":["สวัส","ดี"],"starts":[1]}])
        with self.assertRaisesRegex(ValueError,"ตรงกับเนื้อร้อง"):
            edit.save(self.workspace,sid,None,[{"text":"hello",
                "start":1,"end":2,"segments":["other"],"starts":[1]}])
        with self.assertRaisesRegex(ValueError,"แก้ไขในหน้าต่างอื่น"):
            edit.save(self.workspace,sid,"old-revision",[
                {"text":"hello","start":None,"end":None,"segments":[],"starts":[]}])
        self.assertEqual(edit.queue(self.workspace)["total"],1)


if __name__=="__main__":
    unittest.main()
