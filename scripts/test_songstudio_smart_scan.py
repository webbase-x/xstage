"""SQLite Smart Scan: real media+timed lyrics pairs, stop/resume, no source writes."""
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

    def test_timed_lyric_pair_reuses_and_detects_change(self):
        base=self.source / "MIDI"
        song=base / "Songs" / "0" / "0001.MID"
        lyric=base / "Lyrics" / "0" / "0001.lrc"
        song.parent.mkdir(parents=True)
        lyric.parent.mkdir(parents=True)
        song.write_bytes(b"MThd"+b"\0"*40)
        lyric.write_text("[00:01.00]ท่อนแรก",encoding="utf-8")
        rows,_=self.run_scan()
        row=next(item for item in rows if item["path"]==str(song))
        self.assertEqual(row["status"],"ready")
        self.assertEqual(row["lyrics_file"],str(lyric))
        self.assertEqual(row["source_format"],"SMF")
        rows,stats=self.run_scan()
        self.assertEqual(stats["changed"],0)
        lyric.write_text("[00:01.00]ท่อนแรกที่แก้ไขให้ยาว",encoding="utf-8")
        rows,stats=self.run_scan()
        self.assertGreaterEqual(stats["changed"],1)
        lyric.unlink()
        rows,_=self.run_scan()
        row=next(item for item in rows if item["path"]==str(song))
        self.assertEqual(row["status"],"missing-lyrics")
        self.assertNotIn("ncn",row)

    def test_selected_song_folder_does_not_guess_unscanned_lyrics(self):
        base=self.source / "NCN"
        song=base / "Song" / "0" / "0001.MID"
        lyric=base / "Lyrics" / "0" / "0001.json"
        song.parent.mkdir(parents=True)
        lyric.parent.mkdir(parents=True)
        song.write_bytes(b"MThd"+b"\0"*40)
        lyric.write_text('{"schemaVersion":1,"songCode":"0001","lines":[{"startTime":1,"text":"ทดสอบ"}]}',
                         encoding="utf-8")
        self.source=base / "Song"
        rows,_=self.run_scan()
        self.assertEqual(rows[0]["status"],"missing-lyrics")
        self.assertNotIn("lyrics_file",rows[0])
        self.source=base
        rows,_=self.run_scan()
        row=next(item for item in rows if item["path"]==str(song))
        self.assertEqual(row["status"],"ready")
        self.assertEqual(row["lyrics_file"],str(lyric))

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
