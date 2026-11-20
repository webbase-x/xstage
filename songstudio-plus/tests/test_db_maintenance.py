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

    def test_explicit_compaction_preserves_registry(self):
        core.import_folder(self.workspace,self.root)
        result=maint.compact_database(self.workspace)
        self.assertTrue(result["file_shrunk"])
        self.assertEqual(result["after"]["counts"]["songs"],1)
        with core.connect(self.workspace) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],"ok")

if __name__=="__main__":
    unittest.main()
