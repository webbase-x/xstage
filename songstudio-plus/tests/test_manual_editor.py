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
        self.assertEqual(edit.approved_selected_ids(self.workspace,[song_id]),set())
        edit.approve(self.workspace,song_id,complete["version_id"])
        self.assertEqual(edit.ready_count(self.workspace),1)
        self.assertEqual(edit.approved_build_ids(self.workspace),[song_id])
        self.assertEqual(edit.approved_selected_ids(self.workspace,[song_id]),{song_id})
        # Multi-chunk explicit validation never needs to materialize the
        # complete karaoke catalog, and preserves each requested selection.
        large_selection=["missing-"+str(i) for i in range(405)]+[song_id,song_id]
        self.assertEqual(edit.approved_selected_ids(self.workspace,large_selection),
                         {song_id})
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

    def test_manual_version_is_never_overwritten_by_automatic_import(self):
        song_id=self.song["id"]
        saved=edit.save(self.workspace,song_id,None,[
            {"text":"Text","start":2,"end":4,
             "segments":["Te","xt"],"starts":[2,3]},
        ])
        old=saved["version_id"]
        with core.connect(self.workspace) as db:
            db.execute("""INSERT INTO xstage_lyric_versions
               (id,song_id,content_sha256,source_sha256,origin,timing_status,
                title,artist,created_at,is_current)
               VALUES (?,?,?,NULL,'NCN','original','test','',?,0)""",
               ("original-version",song_id,"another-original-sha",core.now()))
            self.assertFalse(core._prefer_version(db,song_id,"original-version"))
            active=db.execute("""SELECT id FROM xstage_lyric_versions
              WHERE song_id=? AND is_current=1""",(song_id,)).fetchone()[0]
            self.assertEqual(active,old)

    def test_diagnostics_suggest_fixes_only_for_observed_problems(self):
        rows=[
            {"text":"รักเธอ","start":None,"end":None,"segments":[],"starts":[]},
            {"text":"hello","start":1.0,"end":3.0,"segments":["hel","lo"],
             "starts":[1.0]},
            {"text":"abcd","start":3.0,"end":4.0,"segments":["ab","xd"],
             "starts":[3.1,3.5]},
            {"text":"ok","start":4.0,"end":7.0,"segments":["o","k"],
             "starts":[4.1,5.0],"timing":"estimated"},
        ]
        found=edit.inspect_cue_issues(rows)
        self.assertIn(("missing","LINE_UNTIMED",0),
            [(x["category"],x["rule"],x["line_position"]) for x in found])
        self.assertIn(("missing","CUES_PARTIAL",1),
            [(x["category"],x["rule"],x["line_position"]) for x in found])
        self.assertIn(("structural","CUES_TEXT_MISMATCH",2),
            [(x["category"],x["rule"],x["line_position"]) for x in found])
        self.assertIn(("unverified","ESTIMATED_TIMING",3),
            [(x["category"],x["rule"],x["line_position"]) for x in found])
        self.assertFalse(any(x["category"]=="structural" and x["line_position"]==3
                             for x in found))
        self.assertTrue(all(x["found"] and x["suggestion"] for x in found))

    def test_detail_exposes_missing_lyric_recommendations(self):
        details=edit.detail(self.workspace,self.song["id"])
        self.assertFalse(details["has_lyrics"])
        self.assertEqual(details["findings"][0]["rule"],"NO_LYRICS")
        saved=edit.save(self.workspace,self.song["id"],None,[
            {"text":"ทดสอบ","start":1.0,"end":3.0,
             "segments":["ทด","สอบ"],"starts":[1.0,2.0]},
        ])
        details=edit.detail(self.workspace,self.song["id"])
        self.assertTrue(details["has_lyrics"])
        self.assertTrue(any(x["category"]=="unverified"
                            for x in details["findings"]))
        self.assertEqual(details["song"]["version_id"],saved["version_id"])

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
