"""Safety tests for the shared Drive for desktop publisher."""
import importlib.util
import sys
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "shared_drive_sync.py"
sys.path.insert(0,str(MODULE.parent))
import plus_core as core
import metadata_recovery
spec = importlib.util.spec_from_file_location("shared_drive_sync", MODULE)
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)


class SharedDrivePublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.drive = base / "Google Drive" / "XStageKaraoke"
        for folder in ("SONGS", "DB", "SOUNDFONT", "FX", "BACKUP"):
            (self.drive / folder).mkdir(parents=True, exist_ok=True)
        self.source = base / "Prepared" / "SONGS"
        self.source.mkdir(parents=True, exist_ok=True)

    def test_preview_identical_duplicate_conflict_new(self):
        target = self.drive / "SONGS" / "MIDI" / "XMID" / "1"
        target.mkdir(parents=True)
        (target / "10001.xmid").write_bytes(b"already-synced")
        (target / "10002.xmid").write_bytes(b"unique-existing")
        matching = self.source / "MIDI" / "XMID" / "1"
        matching.mkdir(parents=True)
        (matching / "10001.xmid").write_bytes(b"already-synced")
        (matching / "10002.xmid").write_bytes(b"changed")
        (matching / "10003.xmid").write_bytes(b"already-synced")
        (matching / "10004.xmid").write_bytes(b"new-track")
        preview = shared.inspect(str(self.source), str(self.drive), "SONGS")
        totals = preview["stats"]
        self.assertEqual(totals["scanned"], 4)
        self.assertEqual(totals["identical"], 1)
        self.assertEqual(totals["duplicate"], 1)
        self.assertEqual(totals["conflict"], 1)
        self.assertEqual(totals["new"], 1)
        self.assertEqual((target / "10002.xmid").read_bytes(), b"unique-existing")

    def test_only_new_files_and_duplicate_skipped(self):
        dest = self.drive / "SOUNDFONT" / "SF2"
        dest.mkdir()
        (dest / "original.sf2").write_bytes(b"soundbank-one")
        (self.source / "second.sf2").write_bytes(b"soundbank-one")
        (self.source / "third.sf2").write_bytes(b"soundbank-two")
        preview = shared.inspect(str(self.source), str(self.drive), "SOUNDFONT")
        self.assertEqual(preview["stats"]["duplicate"], 1)
        self.assertEqual(preview["stats"]["new"], 1)
        result = shared.publish(str(self.source), str(self.drive), "SOUNDFONT", plan=preview)
        self.assertEqual(result["published"], 1)
        self.assertEqual((dest / "original.sf2").read_bytes(), b"soundbank-one")
        self.assertEqual((dest / "third.sf2").read_bytes(), b"soundbank-two")
        self.assertFalse((dest / "second.sf2").exists())
        self.assertFalse((self.drive / "DB" / "songs.sqlite3").exists())

    def test_cancel_preserves_completed_files(self):
        (self.source / "a.wav").write_bytes(b"a123")
        (self.source / "b.wav").write_bytes(b"b456")
        stopped = threading.Event()
        def progress(state, message):
            if state.get("published", 0) >= 1:
                stopped.set()
        result = shared.publish(str(self.source), str(self.drive), "FX", progress, stopped)
        self.assertTrue(result["cancelled"])
        self.assertEqual(result["published"], 1)
        self.assertEqual(len(list((self.drive / "FX").glob("*.wav"))), 1)
        self.assertEqual(len(list((self.drive / "FX").glob("*.part"))), 0)

    def test_refuse_root_or_nested_source_and_no_implicit_db(self):
        with self.assertRaises(ValueError):
            shared.inspect(str(self.drive / "SONGS"), str(self.drive), "SONGS")
        with self.assertRaises(ValueError):
            shared.resolve_root(str(Path(self.temp.name) / "NoXStage"))
        with self.assertRaises(ValueError):
            shared.inspect(str(self.source), str(self.drive), "DB")

    def test_source_changes_invalidate_approved_plan(self):
        (self.source / "new.wav").write_bytes(b"old")
        preview = shared.inspect(str(self.source), str(self.drive), "FX")
        (self.source / "new.wav").write_bytes(b"updated")
        with self.assertRaises(ValueError):
            shared.publish(str(self.source), str(self.drive), "FX", plan=preview)
        self.assertFalse((self.drive / "FX" / "new.wav").exists())

    def test_reviewed_metadata_only_xmid_update_and_no_db_write(self):
        workspace=Path(self.temp.name)/"workspace"
        fixture=Path(__file__).parent/"fixtures"/"dontreecrab_ncn"
        original=Path(self.temp.name)/"original"
        shutil.copytree(fixture,original)
        # A numeric NCN source code is a recognizable placeholder on both
        # sides. Arbitrary non-numeric names are deliberately not assumed bad.
        for ext,folder in (("mid","Song"),("lyr","Lyrics"),("cur","Cursor")):
            old=original/folder/"1"/("test."+ext)
            old.rename(old.with_name("00001."+ext))
        core.import_folder(workspace,original)
        song=core.songs(workspace)[0]
        with core.connect(workspace) as db:
            db.execute("UPDATE xstage_songs SET title=original_code,artist='' WHERE id=?",(song["id"],))
            db.execute("UPDATE xstage_lyric_versions SET title=?,artist='' WHERE song_id=?",(song["original_code"],song["id"]))
        first=Path(core.build_song(workspace,song["id"])["path"])
        relative=Path("MIDI")/"XMID"/"0"/first.name
        target=self.drive/"SONGS"/relative
        target.parent.mkdir(parents=True)
        target.write_bytes(first.read_bytes())
        (self.drive/"DB"/"songs.sqlite3").write_bytes(b"catalog")
        self.assertEqual(metadata_recovery.run(workspace)["rebuilt"],1)
        src=self.source/relative
        src.parent.mkdir(parents=True)
        shutil.copyfile(first,src)
        plan=shared.inspect(str(self.source),str(self.drive),"SONGS")
        self.assertEqual(plan["stats"]["metadata_update"],1)
        with self.assertRaises(ValueError):
            shared.publish(str(self.source),str(self.drive),"SONGS")
        result=shared.publish(str(self.source),str(self.drive),"SONGS",plan=plan)
        self.assertEqual(result["updated"],1)
        self.assertEqual(core.read_xfile(target)["title"],"Test Song")
        self.assertEqual((self.drive/"DB"/"songs.sqlite3").read_bytes(),b"catalog")
        self.assertEqual(shared.inspect(str(self.source),str(self.drive),"SONGS")["stats"]["identical"],1)


if __name__ == "__main__":
    unittest.main()
