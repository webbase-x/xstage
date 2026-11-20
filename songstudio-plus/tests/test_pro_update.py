"""Self-update safety: strict Release and hash, cancel/resume without damaged SQLite."""
from __future__ import annotations
import hashlib
import json
import sys
import tempfile
import time
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
import plus_core as core
import pro_updater as update


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.workspace=self.root/"workspace"
        core.init(self.workspace)

    def manifest(self,hash=None):
        return {
            "name":"X-Stage Song Studio Pro",
            "available":True,"version":"0.1.13",
            "download_url":"https://github.com/webbase-x/xstage/releases/download/"
              "song-studio-pro-v0.1.13-preview/"
              "X-Stage-Song-Studio-Pro-v0.1.13-win-x64-Setup.exe",
            "sha256":hash or "a"*64,
        }

    def test_release_verification_rejects_untrusted_or_hashless_urls(self):
        entry=self.manifest()
        self.assertEqual(update.validate(entry)["version"],"0.1.13")
        for change in (
            {"available":False},
            {"name":"Another Studio"},
            {"sha256":"abc"},
            {"download_url":"https://attacker.example/malware.exe"},
            {"version":"0.1.14"},
            {"download_url":entry["download_url"].replace("https://","http://")},
        ):
            bad={**entry,**change}
            with self.subTest(change=change),self.assertRaises(ValueError):
                update.validate(bad)

    def test_sha_verifies_full_staged_executable(self):
        content=b"MZ"+b"TEST_PRO"*150000
        sha=hashlib.sha256(content).hexdigest()
        location=self.workspace/"UPDATES"
        location.mkdir()
        target=self.manifest(sha)
        (location/"X-Stage-Song-Studio-Pro-v0.1.13-win-x64-Setup.exe").write_bytes(content)
        (location/"ready.json").write_text(json.dumps(target),encoding="utf-8")
        ready=update.ready_file(self.workspace)
        self.assertEqual(ready["sha256"],sha)
        (location/"X-Stage-Song-Studio-Pro-v0.1.13-win-x64-Setup.exe").write_bytes(b"MZ"+b"CORRUPT"*160000)
        self.assertIsNone(update.ready_file(self.workspace),
                          "tampering must block any automatic install")

    def test_user_cancelled_import_only_auto_resumes_for_program_restart(self):
        source=self.root/"Source";source.mkdir()
        (source/"00001.mp3").write_bytes(b"AUDIO")
        stop=threading.Event();stop.set()
        prior=core.import_folder(self.workspace,source,cancel=stop)
        self.assertTrue(prior["cancelled"])
        self.assertEqual(core.interrupted_import(self.workspace)["status"],"cancelled")
        self.assertTrue(core.prepare_import_for_restart(self.workspace,prior["batch"]))
        self.assertEqual(core.interrupted_import(self.workspace)["status"],"interrupted")
        self.assertFalse(core.prepare_import_for_restart(self.workspace,prior["batch"]))

    def test_long_running_studio_keeps_bounded_finished_job_history(self):
        """Completed jobs are diagnostics, not an unlimited in-memory queue."""
        with patch.object(core,"interrupted_import",return_value=None):
            state=app.State(self.workspace)
        with state.lock:
            for index in range(70):
                state.jobs[f"old-{index}"]={
                    "id":f"old-{index}","status":"completed",
                    "kind":"test","updated_at":time.time(),
                    "progress":{"done":index},"result":{"message":"x"*200},
                    "revision":0,
                }
        started=threading.Event()
        done=threading.Event()
        def operation(progress,cancel):
            started.set()
            done.wait(2)
            return {"ok":True}
        state.start_job("test",operation)
        self.assertTrue(started.wait(2))
        with state.lock:
            self.assertEqual(len(state.jobs),41)
            self.assertNotIn("old-0",state.jobs)
            self.assertIn("old-69",state.jobs)
            self.assertTrue(any(row["status"]=="running"
                                for row in state.jobs.values()))
        done.set()

    def test_resumed_import_rate_excludes_previous_session_counts(self):
        with patch.object(core,"interrupted_import",return_value=None):
            state=app.State(self.workspace)
        job={"started_at":time.monotonic()-1,
             "updated_at":time.time(),"revision":0,
             "progress":{}}
        state.update(job,{"files_seen":80000},"resumed")
        self.assertEqual(job["progress"]["files_per_second"],0)
        time.sleep(.012)
        state.update(job,{"files_seen":80002},"two files")
        rate=job["progress"]["files_per_second"]
        self.assertGreater(rate,0)
        self.assertLess(rate,1000)
        with state.lock:
            state.jobs["fake-rate"]=job
        visible=state.jobs_snapshot()[0]
        self.assertNotIn("_rate_first_count",visible)
        self.assertNotIn("_rate_first_at",visible)

    def test_update_requests_import_stop_then_restart_checkpoint(self):
        with patch.object(core,"interrupted_import",return_value=None):
            state=app.State(self.workspace)
        entered=threading.Event()
        def import_job(progress,cancel):
            entered.set()
            cancel.wait(2)
            return {"batch":"batch-test-1"}
        state.start_job("import",import_job)
        self.assertTrue(entered.wait(3))
        state.start_job("update",lambda progress,cancel:{"downloaded":True})
        self.assertFalse(any(job["cancel"].is_set() for job in
                             state.jobs.values() if job["kind"]=="import"),
                         "downloading must not interrupt an active import")
        state.request_restart()
        self.assertTrue(any(job["cancel"].is_set() for job in
                            state.jobs.values() if job["kind"]=="import"),
                        "install stops safely after current file")
        deadline=time.monotonic()+5
        while time.monotonic()<deadline and not state.ready_to_exit():
            time.sleep(.015)
        with patch.object(core,"prepare_import_for_restart",return_value=True) as mark:
            # Preserve the exact completed import job, not the downloaded EXE.
            state._restart_prepared=False
            self.assertTrue(state.ready_to_exit())
            mark.assert_called_once_with(self.workspace,"batch-test-1")


if __name__=="__main__": unittest.main()
