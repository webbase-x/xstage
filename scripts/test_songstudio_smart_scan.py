"""SQLite Smart Scan regression tests: real files, NCN, stop/resume, no media writes."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1] / "songstudio-pc"


def load(file, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


index = load("song_index.py", "songstudio_scan_index_test")
ncn = load("ncn_lyrics.py", "songstudio_scan_ncn_test")


class SongSmartScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "music"
        self.source.mkdir()
        self.output = self.root / "exports"
        self.output.mkdir()
        self.db = self.root / "private" / "song-index.sqlite3"
        self.notes = {}
        self.audio = self.source / "เพลงภาษาไทย.mp3"
        self.audio.write_bytes(b"ID3" * 2048)

    def tearDown(self):
        self.temp.cleanup()

    def run_scan(self, *, full=False, cancelled=None, on_progress=None):
        return index.scan(
            self.source, self.output, self.db, self.notes, ncn,
            full=full, cancelled=cancelled, on_progress=on_progress)

    def test_cache_restores_without_walk_and_reuses_unchanged_media(self):
        rows, first = self.run_scan()
        self.assertEqual(len(rows), 1)
        self.assertEqual(first["added"], 1)
        with patch.object(index.os, "scandir", side_effect=AssertionError("walked")):
            restored = index.restore(self.source, self.output, self.db, self.notes)
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0]["title"], "เพลงภาษาไทย")
        again, second = self.run_scan()
        self.assertEqual(again[0]["id"], rows[0]["id"])
        self.assertEqual(second["reused"], 1)
        self.assertEqual(second["changed"], 0)
        self.assertEqual(second["removed"], 0)
        self.assertEqual(self.audio.read_bytes(), b"ID3" * 2048)

    def test_incremental_add_change_delete_and_stable_ids(self):
        rows, _ = self.run_scan()
        first_id = rows[0]["id"]
        second_song = self.source / "อีกเพลง.m4a"
        second_song.write_bytes(b"M4A" * 1200)
        rows, stats = self.run_scan()
        self.assertEqual(stats["added"], 1)
        self.assertEqual({r["path"]: r["id"] for r in rows}[str(self.audio)], first_id)
        newer_id = {r["path"]: r["id"] for r in rows}[str(second_song)]
        self.assertNotEqual(newer_id, first_id)
        self.audio.write_bytes(b"ID3" * 3048)
        rows, stats = self.run_scan()
        self.assertEqual(stats["changed"], 1)
        self.assertEqual(next(r for r in rows if r["id"] == first_id)["size"], self.audio.stat().st_size)
        second_song.unlink()
        rows, stats = self.run_scan()
        self.assertEqual(stats["removed"], 1)
        self.assertEqual([r["id"] for r in rows], [first_id])
        self.assertTrue(self.audio.is_file())

    def test_cache_is_source_and_workspace_specific(self):
        self.run_scan()
        other = self.root / "other"
        other.mkdir()
        self.assertEqual(index.restore(other, self.output, self.db, self.notes), [])
        self.assertEqual(index.restore(self.source, other, self.db, self.notes), [])

    def test_ncn_reuses_unchanged_lyric_and_rereads_when_modified(self):
        base = self.source / "NCN"
        song = base / "Song" / "0" / "0001.MID"
        lyric = base / "Lyrics" / "0" / "0001.LYR"
        cursor = base / "Cursor" / "0" / "0001.CUR"
        for file in (song, lyric, cursor):
            file.parent.mkdir(parents=True, exist_ok=True)
        song.write_bytes(b"MThd" + b"\0" * 40)
        lyric.write_bytes("ชื่อแรก\nผู้ร้อง\nC\n\nเนื้อเพลง\n".encode("cp874"))
        cursor.write_bytes(b"\0\x00\x12\x00")
        rows, _ = self.run_scan()
        row = next(r for r in rows if r["path"] == str(song))
        self.assertEqual(row["title"], "ชื่อแรก")
        self.assertEqual(row["source_format"], "NCN")
        self.assertEqual(row["status"], "ready")
        with patch.object(ncn, "lyric_metadata", side_effect=AssertionError("reread")):
            rows, stats = self.run_scan()
        self.assertEqual(stats["changed"], 0)
        lyric.write_bytes("ชื่อใหม่กว่านี้\nผู้ร้องใหม่\nC\n\nเนื้อเพลง\n".encode("cp874"))
        rows, stats = self.run_scan()
        row = next(r for r in rows if r["path"] == str(song))
        self.assertEqual(row["title"], "ชื่อใหม่กว่านี้")
        self.assertEqual(row["artist"], "ผู้ร้องใหม่")
        cursor.unlink()
        rows, _ = self.run_scan()
        row = next(r for r in rows if r["path"] == str(song))
        self.assertEqual(row["status"], "missing-companion")

    def test_scanning_only_ncn_song_finds_lyrics_siblings(self):
        base = self.source / "NCN"
        song = base / "Song" / "0" / "0001.MID"
        lyric = base / "Lyrics" / "0" / "0001.LYR"
        cursor = base / "Cursor" / "0" / "0001.CUR"
        for file in (song, lyric, cursor):
            file.parent.mkdir(parents=True, exist_ok=True)
        song.write_bytes(b"MThd" + b"\0" * 40)
        lyric.write_bytes("ชื่อเพลง\nผู้ร้อง\nC\n\nเนื้อเพลง\n".encode("cp874"))
        cursor.write_bytes(b"\0\x00")
        self.source = base / "Song"
        rows, _ = self.run_scan()
        self.assertEqual(rows[0]["title"], "ชื่อเพลง")
        self.assertEqual(rows[0]["ncn"]["cursor"], str(cursor))
        cursor.unlink()
        rows, _ = self.run_scan()
        self.assertEqual(rows[0]["status"], "missing-companion")

    def test_cancel_preserves_last_complete_index_and_resume_reuses_checkpoint(self):
        before, _ = self.run_scan()
        self.assertEqual(len(before), 1)
        for i in range(18):
            (self.source / f"{i:05d}.mp3").write_bytes(b"ID3" * 100)
        class CancelAfter:
            def __init__(self):
                self.calls = 0
            def is_set(self):
                self.calls += 1
                return self.calls > 9
        with self.assertRaisesRegex(RuntimeError, "หยุดสแกน"):
            self.run_scan(cancelled=CancelAfter())
        # Interrupted scan cannot publish partial index or delete old catalog.
        self.assertEqual(len(index.restore(self.source, self.output, self.db, self.notes)), 1)
        rows, stats = self.run_scan()
        self.assertEqual(len(rows), 19)
        self.assertGreater(stats["reused"], 0)
        self.assertEqual(len(index.restore(self.source, self.output, self.db, self.notes)), 19)
        self.assertEqual(len(list(self.source.glob("*.mp3"))), 19)

    def test_excludes_generated_output_but_never_deletes_it(self):
        self.source = self.root
        generated = self.output / "StageWeb" / "audio" / "0" / "fake.m4a"
        generated.parent.mkdir(parents=True, exist_ok=True)
        generated.write_bytes(b"existing" * 600)
        rows, _ = self.run_scan()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["path"], str(self.audio))
        self.assertTrue(generated.is_file())

    def test_reports_actual_files_without_fake_percentage(self):
        stages = []
        _, stats = self.run_scan(on_progress=lambda phase, count: stages.append((phase, count)))
        self.assertEqual(stats["songs"], 1)
        self.assertGreaterEqual(stats["checked"], 1)
        self.assertTrue(stages)
        self.assertTrue(any("บันทึกดัชนี" in phrase for phrase, count in stages))


if __name__ == "__main__":
    unittest.main()
