"""Regression fixtures for the evidence-only swipe risk ledger.

Every flagged row originates in a purposely malformed SQLite timing record,
not a random song choice, title heuristic, or unproven audio assertion.
"""
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import plus_core as core
import risk_audit as audit
from test_plus import midi


class RiskAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.workspace=self.base/"workspace"
        self.source=self.base/"source"
        self.source.mkdir()
        audit.init(self.workspace)

    def test_initialized_risk_schema_does_not_reissue_ddl_on_ui_reads(self):
        with patch.object(core,"connect",side_effect=AssertionError("redundant DDL")):
            audit.init(self.workspace)

    def put(self,rel,data):
        path=self.source/rel
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data)
        return path

    def ncn(self,code="00400",cursor=True):
        self.put(f"NCN/Song/0/{code}.mid",midi())
        self.put(f"NCN/Lyrics/0/{code}.lyr",
                 "เพลงทดสอบ\nผู้ร้อง\nC\n\nNick\n".encode("cp874"))
        if cursor:
            self.put(f"NCN/Cursor/0/{code}.cur",struct.pack("<5H",0,1,2,3,4))
        core.import_folder(self.workspace,self.source)
        return core.songs(self.workspace)[0]

    def test_no_fabricated_structural_risk_in_valid_ncn(self):
        self.ncn()
        report=audit.scan(self.workspace)
        self.assertEqual(report["structural_songs"],0)
        self.assertEqual(audit.list_findings(self.workspace,"structural")["total"],0)
        # The NCN reader estimates the final line boundary, which is
        # recorded separately as an unverified assumption, NOT an error.
        self.assertEqual(audit.list_findings(self.workspace,"unverified")["total"],1)

    def test_direct_text_mismatch_creates_reproducible_specific_evidence(self):
        song=self.ncn()
        with core.connect(self.workspace) as db:
            line=db.execute("""SELECT l.id FROM xstage_lyric_lines l
                 JOIN xstage_lyric_versions v ON v.id=l.version_id
                 WHERE v.song_id=? AND v.is_current=1""",(song["id"],)).fetchone()
            db.execute("UPDATE xstage_lyric_cues SET text=? WHERE line_id=? AND position=0",
                       ("X",line["id"]))
        first=audit.scan(self.workspace)
        self.assertEqual(first["structural_songs"],1)
        result=audit.list_findings(self.workspace,"structural")
        self.assertEqual(result["total"],1)
        self.assertEqual(result["rows"][0]["song_id"],song["id"])
        rules=[x["rule"] for x in result["rows"][0]["findings"]]
        self.assertIn("CUE_TEXT_DIFFERS",rules)
        second=audit.scan(self.workspace)
        self.assertNotEqual(first["run_id"],second["run_id"])
        self.assertEqual(audit.list_findings(self.workspace,"structural")["total"],1)
        self.assertEqual(len(audit.history(self.workspace)["runs"]),2)

    def test_proven_outside_line_timing_flagged_not_randomized(self):
        song=self.ncn()
        with core.connect(self.workspace) as db:
            line=db.execute("""SELECT l.id,l.end_time FROM xstage_lyric_lines l
                 JOIN xstage_lyric_versions v ON v.id=l.version_id
                 WHERE v.song_id=? AND v.is_current=1""",(song["id"],)).fetchone()
            db.execute("UPDATE xstage_lyric_cues SET start_time=? WHERE line_id=? AND position=0",
                       (line["end_time"]+2.0,line["id"]))
        audit.scan(self.workspace)
        entries=audit.list_findings(self.workspace,"structural")["rows"]
        self.assertEqual(len(entries),1)
        self.assertIn("CUE_OUTSIDE_LINE",[f["rule"] for f in entries[0]["findings"]])

    def test_incomplete_cur_not_falsely_labeled_playable_risk(self):
        self.put("NCN/Song/0/00400.mid",midi())
        self.put("NCN/Lyrics/0/00400.lyr",
                 "เพลงทดสอบ\nผู้ร้อง\nC\n\nNick\n".encode("cp874"))
        result=core.import_folder(self.workspace,self.source)
        self.assertEqual(result["skipped_ncn"],1)
        self.assertEqual(core.stats(self.workspace)["songs"],0)
        report=audit.scan(self.workspace)
        # Missing CUR means NCN source is skipped, never labeled a risk
        # or made available as an imaginary playable song.
        self.assertEqual(report["total"],0)
        self.assertEqual(audit.list_findings(self.workspace,"structural")["total"],0)
        self.assertEqual(audit.list_findings(self.workspace,"unverified")["total"],0)

    def test_partial_lyric_version_is_blocked_not_structural(self):
        self.put("NCN/Song/0/00809.mid",midi())
        self.put("NCN/Lyrics/0/00809.lyr",
                 "เพลงทดสอบ\nผู้ร้อง\nC\n\nNick\nAnother\n".encode("cp874"))
        self.put("NCN/Cursor/0/00809.cur",struct.pack("<5H",0,1,2,3,4))
        core.import_folder(self.workspace,self.source)
        report=audit.scan(self.workspace)
        self.assertEqual(report["blocked_songs"],1)
        self.assertEqual(report["structural_songs"],0)
        self.assertEqual(audit.list_findings(self.workspace,"blocked")["total"],1)

    def test_lrc_estimate_is_review_only_not_confirmed_error(self):
        media=self.put("audio.mp3",b"music"*400)
        (media.parent/"audio.lrc").write_text(
            "[00:01.00]Hello\n[00:05.00]World\n",encoding="utf-8")
        core.import_folder(self.workspace,self.source)
        report=audit.scan(self.workspace)
        self.assertEqual(report["structural_songs"],0)
        self.assertEqual(report["estimated_songs"],1)
        self.assertEqual(audit.list_findings(self.workspace,"unverified")["total"],1)

    def test_review_history_is_manual_and_survives_rescan(self):
        self.ncn()
        audit.scan(self.workspace)
        item=audit.list_findings(self.workspace,"unverified")["rows"][0]
        self.assertEqual(audit.history(self.workspace)["reviews"],[])
        with self.assertRaisesRegex(ValueError,"สถานะ"):
            audit.review(self.workspace,item["song_id"],item["version_id"],"confirmed-by-system")
        audit.review(self.workspace,item["song_id"],item["version_id"],
                     "needs-review","ต้องทดสอบกับเครื่องคาราโอเกะ")
        audit.review(self.workspace,item["song_id"],item["version_id"],
                     "passed","เปิดฟังแล้วตรงช่วงนี้")
        audit.scan(self.workspace)
        rows=audit.list_findings(self.workspace,"unverified")["rows"]
        self.assertEqual(rows[0]["review_status"],"passed")
        history=audit.history(self.workspace)
        self.assertEqual(len(history["reviews"]),2)
        self.assertEqual(history["reviews"][0]["note"],"เปิดฟังแล้วตรงช่วงนี้")

    def test_scan_is_version_specific_and_saves_no_source_copy(self):
        song=self.ncn()
        audit.scan(self.workspace)
        self.assertFalse((self.workspace/"SOURCE").exists())
        old=core.songs(self.workspace)[0]["version_id"]
        with core.connect(self.workspace) as db:
            base=db.execute("SELECT * FROM xstage_lyric_versions WHERE id=?",(old,)).fetchone()
            new_id="another-version"
            db.execute("UPDATE xstage_lyric_versions SET is_current=0 WHERE id=?",(old,))
            db.execute("""INSERT INTO xstage_lyric_versions
              (id,song_id,content_sha256,origin,timing_status,title,artist,
               created_at,is_current) VALUES (?,?,?,?,?,?,?,?,1)""",
               (new_id,song["id"],"deadbeef","edit","estimated",
                base["title"],base["artist"],core.now()))
        audit.scan(self.workspace)
        self.assertEqual(audit.list_findings(self.workspace,"structural")["total"],0)
        self.assertEqual(audit.list_findings(self.workspace,"blocked")["total"],1)


if __name__=="__main__":
    unittest.main()
