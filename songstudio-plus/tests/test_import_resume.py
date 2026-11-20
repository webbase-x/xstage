"""Crash-safe import snapshots and resume with changed file/sidecar protection."""
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import plus_core as core
from test_plus import midi

class ImportResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.source=self.root/"ต้นฉบับ"
        self.source.mkdir()
        self.workspace=self.root/"library"
        core.init(self.workspace)
    def make(self,name="00001.mid",raw=None):
        path=self.source/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw or midi())
        return path
    def test_interrupted_import_skips_completed_files_and_restarts_at_checkpoint(self):
        for i in range(35):
            self.make(f"{i:05}.mid",midi()+bytes([i]))
        stop=threading.Event()
        digest=core.digest
        seen=[0]
        def stop_after_n(path):
            output=digest(path)
            seen[0]+=1
            if seen[0]>=19:stop.set()
            return output
        with patch.object(core,"digest",side_effect=stop_after_n):
            first=core.import_folder(self.workspace,self.source,cancel=stop)
        self.assertTrue(first["cancelled"])
        self.assertEqual(first["files_seen"],19)
        prior=core.interrupted_import(self.workspace)
        self.assertEqual(prior["batch_id"],first["batch"])
        with patch.object(core,"digest",wraps=core.digest) as hashed:
            resumed=core.import_folder(self.workspace,self.source)
        self.assertEqual(resumed["batch"],first["batch"])
        self.assertEqual(resumed["files_seen"],35)
        self.assertEqual(resumed["resumed_files"],19)
        self.assertEqual(hashed.call_count,16)
        self.assertFalse(resumed["cancelled"])
        self.assertIsNone(core.interrupted_import(self.workspace))
        with core.connect(self.workspace) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM xstage_import_file_checkpoints").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM xstage_import_items").fetchone()[0],0)
    def test_same_file_changed_reopens_media_even_after_checkpoint(self):
        source=self.make("song.mp3",b"sound one")
        stop=threading.Event()
        stop.set()  # zero items when cancelled, still resumable
        first=core.import_folder(self.workspace,self.source,cancel=stop)
        self.assertEqual(first["files_seen"],0)
        old=core.import_folder(self.workspace,self.source,cancel=threading.Event())
        self.assertEqual(old["files_seen"],1)
        self.assertEqual(old["resumed_files"],0)
        source.write_bytes(b"sound two")
        os.utime(source,None)
        # A completed batch starts a fresh import, and hash changes safely.
        again=core.import_folder(self.workspace,self.source)
        self.assertEqual(again["files_seen"],1)
        self.assertEqual(again["files_new"],1)
    def test_running_batch_marked_interrupted(self):
        self.make("audio.mp3",b"hello")
        stop=threading.Event();stop.set()
        result=core.import_folder(self.workspace,self.source,cancel=stop)
        with core.connect(self.workspace) as db:
            db.execute("UPDATE xstage_import_resume_state SET status='running' WHERE batch_id=?",(result["batch"],))
            db.execute("UPDATE xstage_import_batches SET status='running' WHERE id=?",(result["batch"],))
        found=core.interrupted_import(self.workspace)
        self.assertEqual(found["status"],"interrupted")
        self.assertEqual(found["batch_id"],result["batch"])
    def test_changed_companion_causes_recheck_after_cancel(self):
        midi_file=self.make("NCN/Song/0/00001.mid")
        lyr=self.make("NCN/Lyrics/0/00001.lyr",b"Name\\nArtist\\nC\\n\\nhello\\n")
        cur=self.make("NCN/Cursor/0/00001.cur",bytes([0,0,1,0,2,0,3,0,4,0,5,0]))
        stop=threading.Event()
        def callback(totals,_):stop.set()
        first=core.import_folder(self.workspace,self.source,callback,stop)
        # This import is not required to have correct lyrics, only a stable checkpoint.
        old_stamp=core.companion_stamp(core.companion_candidates(midi_file))
        cur.write_bytes(cur.read_bytes()+b"\\x06\\x00")
        self.assertNotEqual(core.companion_stamp(core.companion_candidates(midi_file)),old_stamp)
        with patch.object(core,"document_for",wraps=core.document_for) as parsed:
            again=core.import_folder(self.workspace,self.source)
        self.assertEqual(again["files_seen"],1)
        self.assertEqual(again["resumed_files"],0)
        self.assertGreaterEqual(parsed.call_count,1)

if __name__=="__main__": unittest.main()
