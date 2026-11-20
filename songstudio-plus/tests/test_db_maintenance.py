"""SQLite import retention, resume safety, duplicate and compaction regression."""
from __future__ import annotations
import sys
import tempfile
import threading
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import plus_core as core
import db_maintenance as maint

class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)
        self.workspace=self.base/"workspace"
        self.root=self.base/"input"
        self.root.mkdir()
        self.media=self.root/"track.mp3"
        self.media.write_bytes(b"ID3"+b"A"*2000)
        core.init(self.workspace)

    def tearDown(self):
        self.tmp.cleanup()

    def test_duplicate_import_and_checkpoint_retention(self):
        for _ in range(6):
            result=core.import_folder(self.workspace,self.root)
            self.assertEqual(result["failures"],0)
        before=maint.snapshot(self.workspace)
        self.assertEqual(before["counts"]["songs"],1)
        self.assertEqual(before["counts"]["media"],1)
        self.assertEqual(before["counts"]["sources"],1)
        self.assertEqual(before["counts"]["checkpoints"],0)
        self.assertEqual(before["counts"]["import_items"],0)
        self.assertEqual(before["completed_batches"],6)
        cleaned=maint.cleanup_history(self.workspace,retain_completed=2)
        self.assertEqual(cleaned["old_batches_removed"],4)
        after=maint.snapshot(self.workspace)
        self.assertEqual(after["completed_batches"],2)
        self.assertEqual(after["counts"]["songs"],1)
        self.assertEqual(after["counts"]["media"],1)

    def test_second_import_does_not_rewrite_unchanged_source_or_success_logs(self):
        core.import_folder(self.workspace,self.root)
        with core.connect(self.workspace) as db:
            old=db.execute("""SELECT verified_sha256,last_seen
                FROM xstage_media_sources WHERE source_path=?""",
                (str(self.media.resolve()),)).fetchone()
            old_source=tuple(old)
        second=core.import_folder(self.workspace,self.root)
        self.assertEqual(second["files_new"],0)
        self.assertEqual(second["media_duplicates"],1)
        self.assertEqual(second["hash_cache_hits"],1)
        with core.connect(self.workspace) as db:
            source=tuple(db.execute("""SELECT verified_sha256,last_seen
                FROM xstage_media_sources WHERE source_path=?""",
                (str(self.media.resolve()),)).fetchone())
            self.assertEqual(source,old_source)
            self.assertEqual(db.execute("SELECT count(*) FROM xstage_import_items").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT count(*) FROM xstage_import_file_checkpoints").fetchone()[0],0)

    def test_cancelled_job_survives_maintenance_and_resumes(self):
        flag=threading.Event()
        flag.set()
        first=core.import_folder(self.workspace,self.root,cancel=flag)
        self.assertTrue(first["cancelled"])
        resume=core.interrupted_import(self.workspace)
        self.assertEqual(resume["batch_id"],first["batch"])
        maint.cleanup_history(self.workspace)
        self.assertEqual(core.interrupted_import(self.workspace)["batch_id"],first["batch"])
        final=core.import_folder(self.workspace,self.root)
        self.assertEqual(final["files_new"],1)
        self.assertEqual(maint.snapshot(self.workspace)["counts"]["songs"],1)

    def test_incomplete_ncn_issue_remains_after_cleanup(self):
        source=self.root/"NCN"/"Song"/"0"
        source.mkdir(parents=True)
        (source/"00001.mid").write_bytes(b"MThd"+"C".encode()*20)
        core.import_folder(self.workspace,self.root)
        issues=core.import_issues(self.workspace)
        self.assertTrue(any(item["outcome"]=="skipped-ncn-incomplete" for item in issues))
        maint.cleanup_history(self.workspace)
        issues=core.import_issues(self.workspace)
        self.assertTrue(any(item["outcome"]=="skipped-ncn-incomplete" for item in issues))
        self.assertEqual(maint.snapshot(self.workspace)["counts"]["songs"],1)

    def test_detailed_audit_measures_real_sqlite_table_and_index_pages(self):
        core.import_folder(self.workspace,self.root)
        report=maint.detailed_audit(self.workspace)
        self.assertEqual(report["quick_check"],"ok")
        self.assertIn("counts",report)
        self.assertIn("table_space",report)
        known={x["table"]:x for x in report["table_space"]}
        self.assertIn("xstage_songs",known)
        self.assertEqual(known["xstage_songs"]["category"],"keep")
        self.assertEqual(known["xstage_import_batches"]["category"],"temporary")
        if report["dbstat_available"]:
            self.assertGreater(known["xstage_songs"]["bytes"],0)
            self.assertGreaterEqual(known["xstage_songs"]["bytes"],
                                    known["xstage_songs"]["table_bytes"])

    def test_cleanup_completed_resume_cache_and_unused_index(self):
        core.import_folder(self.workspace,self.root)
        with core.connect(self.workspace) as db:
            db.execute("""INSERT INTO xstage_lyric_scan_cache
                (source_path,media_sha256,companion_stamp,outcome,last_scanned)
                VALUES ('orphan://removed','sha','','no-lyrics',?)""",
                (core.now(),))
            db.execute("""CREATE INDEX IF NOT EXISTS xstage_lyric_source
                ON xstage_lyric_versions(song_id,source_sha256)""")
            self.assertEqual(db.execute("""SELECT count(*) FROM xstage_import_resume_state
                WHERE status='completed'""").fetchone()[0],1)
        result=maint.cleanup_history(self.workspace)
        self.assertEqual(result["completed_resume_removed"],1)
        self.assertEqual(result["orphan_cache_removed"],1)
        self.assertEqual(result["unused_index_removed"],1)
        with core.connect(self.workspace) as db:
            self.assertEqual(db.execute("""SELECT count(*) FROM xstage_import_resume_state
                WHERE status='completed'""").fetchone()[0],0)
            self.assertEqual(db.execute("""SELECT count(*) FROM xstage_lyric_scan_cache
                WHERE source_path='orphan://removed'""").fetchone()[0],0)
            self.assertIsNone(db.execute("""SELECT name FROM sqlite_master
                WHERE name='xstage_lyric_source'""").fetchone())
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],"ok")

    def test_cleanup_retains_latest_two_full_audits_and_manual_reviews(self):
        import risk_audit as risks
        (self.root/"track.lrc").write_text(
            "[00:01.00]First lyric\n[00:05.00]Second line\n",
            encoding="utf-8")
        core.import_folder(self.workspace,self.root)
        risks.init(self.workspace)
        for _ in range(4):
            result=risks.scan(self.workspace)
            self.assertGreater(result["findings"],0)
        song_id=core.songs(self.workspace)[0]["id"]
        version_id=core.songs(self.workspace)[0]["version_id"]
        risks.review(self.workspace,song_id,version_id,"needs-review","keep human note")
        result=maint.cleanup_history(self.workspace)
        self.assertGreater(result["old_audit_findings_removed"],0)
        with core.connect(self.workspace) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM xstage_swipe_audit_runs").fetchone()[0],4)
            runs=[r[0] for r in db.execute("""SELECT id FROM xstage_swipe_audit_runs
                ORDER BY finished_at DESC,started_at DESC,id DESC LIMIT 2""")]
            self.assertEqual(db.execute("""SELECT count(DISTINCT run_id)
                FROM xstage_swipe_findings""").fetchone()[0],2)
            self.assertEqual({r[0] for r in db.execute(
                "SELECT DISTINCT run_id FROM xstage_swipe_findings")},set(runs))
            self.assertEqual(db.execute("SELECT count(*) FROM xstage_swipe_reviews").fetchone()[0],1)

    def test_explicit_compaction_preserves_registry(self):
        core.import_folder(self.workspace,self.root)
        result=maint.compact_database(self.workspace)
        self.assertTrue(result["file_shrunk"])
        self.assertEqual(result["after"]["counts"]["songs"],1)
        with core.connect(self.workspace) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],"ok")

if __name__=="__main__":
    unittest.main()
