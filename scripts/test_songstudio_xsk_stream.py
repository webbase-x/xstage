"""Regression: producer scans next MIDI batch while builder consumes first batch."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "songstudio-pc"


def load(name):
    spec = importlib.util.spec_from_file_location("test_" + name, ROOT / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stream = load("xsk_stream")


class XskStreamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "Music"
        self.output = self.source / "XStageSong"
        self.source.mkdir()
        self.output.mkdir()

    def midi(self, folder, name, marker=b"X"):
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (name + ".mid")
        path.write_bytes(b"MThd" + marker * 80)
        (folder / (name + ".lrc")).write_text(
            "[ti:ชื่อเพลง " + name + "]\n[ar:ศิลปินทดสอบ]\n[00:02.00]เนื้อร้องพร้อมเวลา",
            encoding="utf-8")
        return path

    def test_midi_fixture_lrc_has_real_line_breaks(self):
        midi = self.midi(self.source, "fixture", b"F")
        lyrics = midi.with_suffix(".lrc").read_text(encoding="utf-8")
        self.assertEqual(len(lyrics.splitlines()), 3)
        self.assertIn("[ar:ศิลปินทดสอบ]", lyrics.splitlines())
        self.assertTrue(lyrics.splitlines()[2].startswith("[00:02.00]"))

    def test_starts_processing_first_folder_before_deeper_scan_finishes(self):
        self.midi(self.source / "A", "00001")
        self.midi(self.source / "B", "00002")
        statuses = []
        with stream.source_batches(self.source, self.output, cancelled=threading.Event(),
                                   on_scan=lambda state, done, wait:
                                       statuses.append((state["found"], done, wait)),
                                   batch_size=32, max_batches=2) as tracks:
            row = next(tracks)
            self.assertEqual(row["code"], "00001")
            self.assertEqual({r["code"] for r in tracks}, {"00002"})
        self.assertTrue(any(count >= 1 and not finished for count, finished, _ in statuses))

    def test_limited_queue_with_thousands_and_output_excluded(self):
        for index in range(180):
            self.midi(self.source / "A", f"{index:05d}", bytes([index % 255 + 1]))
        (self.output / "MIDI" / "XSK").mkdir(parents=True)
        (self.output / "MIDI" / "XSK" / "old.mid").write_bytes(b"MThd" * 50)
        max_backlog = 0

        def progress(_, done, waiting):
            nonlocal max_backlog
            max_backlog = max(max_backlog, waiting)

        with stream.source_batches(self.source, self.output, cancelled=threading.Event(),
                                   on_scan=progress, batch_size=8, max_batches=2) as tracks:
            names = [row["code"] for row in tracks]
        self.assertEqual(len(names), 180)
        self.assertNotIn("old", names)
        self.assertLessEqual(max_backlog, 2)

    def test_cancellation_ends_iterator_and_preserves_source(self):
        self.midi(self.source, "00001")
        self.midi(self.source, "00002")
        cancellation = threading.Event()
        with stream.source_batches(self.source, self.output, cancelled=cancellation,
                                   batch_size=1) as tracks:
            next(tracks)
            cancellation.set()
            with self.assertRaisesRegex(RuntimeError, "ยกเลิก"):
                list(tracks)
        self.assertTrue((self.source / "00002.mid").exists())

    def test_unreadable_subfolder_is_not_silently_skipped(self):
        self.midi(self.source / "A", "00001")
        self.midi(self.source / "B", "00002")
        original = stream.os.scandir

        def fails_for_b(folder):
            if Path(folder).name == "B":
                raise PermissionError("denied")
            return original(folder)

        with patch.object(stream.os, "scandir", side_effect=fails_for_b):
            with stream.source_batches(self.source, self.output, cancelled=threading.Event(),
                                       batch_size=1) as tracks:
                self.assertEqual(next(tracks)["code"], "00001")
                with self.assertRaisesRegex(RuntimeError, "สแกน MIDI ไม่ครบ"):
                    list(tracks)

    def test_rejects_invalid_input_and_output(self):
        with self.assertRaises(ValueError):
            with stream.source_batches(self.source, self.source, cancelled=threading.Event()):
                pass
        with self.assertRaises(ValueError):
            with stream.source_batches(self.source, self.output, cancelled=threading.Event(),
                                       batch_size=0):
                pass

    def test_mirrored_audio_lyrics_pair_does_not_cross_albums(self):
        engine = load("engine")
        export = load("song_export")
        first = self.midi(self.source / "Album A" / "AUDIO", "00011", b"A")
        second = self.midi(self.source / "Album B" / "AUDIO", "00011", b"B")
        first.with_suffix(".lrc").unlink()
        second.with_suffix(".lrc").unlink()
        lyrics = self.source / "Album A" / "LYRICS"
        lyrics.mkdir()
        (lyrics / "00011.json").write_text(json.dumps({
            "schemaVersion": 1, "lines": [{"startTime": 1.5,
                                          "endTime": 4.0, "text": "ปลอดภัย"}]
        }, ensure_ascii=False), encoding="utf-8")
        _, timed, _ = engine.lyrics_package({"path": str(first),
                                              "code": "00011"}, export=export)
        self.assertEqual(timed["lines"][0]["startTime"], 1.5)
        _, absent, _ = engine.lyrics_package({"path": str(second),
                                               "code": "00011"}, export=export)
        self.assertIsNone(absent)

    def test_xsk_identity_reads_ncn_and_kar_metadata_not_filename(self):
        engine = load("engine")
        source = self.source / "00001.mid"
        row = {"path": str(source), "code": "00001",
               "title": source.stem, "artist": ""}
        for format_name in ("NCN", "KAR"):
            with self.subTest(format_name=format_name):
                doc = {"schemaVersion": 1, "sourceFormat": format_name,
                       "metadata": {"title": "เพลงตัวอย่างจริง",
                                    "artist": "ศิลปินตัวจริง"},
                       "lines": [{"startTime": 1.0, "text": "ร้อง"}]}
                self.assertEqual(engine._xsk_identity(source, row, doc),
                                 ("เพลงตัวอย่างจริง", "ศิลปินตัวจริง"))

    def test_xsk_identity_never_uses_brand_as_artist(self):
        engine = load("engine")
        source = self.source / "00002.mid"
        row = {"path": str(source), "title": "00002", "artist": ""}
        doc = {"title": "เพลงที่สอง", "artist": "X-Stage Karaoke",
               "metadata": {"artist": "X-Stage Song Studio"}}
        self.assertEqual(engine._xsk_identity(source, row, doc),
                         ("เพลงที่สอง", "ไม่ระบุศิลปิน"))
        engine.NOTES[str(source)] = {"artist": "ศิลปินแก้ไขด้วยตนเอง"}
        try:
            self.assertEqual(engine._xsk_identity(source, row, doc)[1],
                             "ศิลปินแก้ไขด้วยตนเอง")
        finally:
            engine.NOTES.pop(str(source), None)

    def test_real_xsk_sealing_roundtrip_and_dedup(self):
        import sys
        # XSK2 must not create or require a Windows DPAPI key.
        engine = load("engine")
        package = load("xsk_package")
        self.midi(self.source, "00001", b"A")
        self.midi(self.source, "00002", b"B")
        (self.source / "00001.lrc").unlink()
        (self.source / "00001.json").write_text(json.dumps({
            "schemaVersion": 1, "title": "เพลงจาก JSON",
            "artist": "นักร้องจาก JSON",
            "lines": [{"startTime": 2.0, "endTime": 4.0, "text": "ทดลอง"}]
        }, ensure_ascii=False), encoding="utf-8")
        self.midi(self.source, "00003", b"B")  # duplicate of 00002, never the metadata fixture 00001
        broken = self.midi(self.source, "00004", b"C")
        broken.with_suffix(".lrc").unlink()  # file without timed lyrics must be skipped
        self.midi(self.source, "เพลงไทย ทดสอบ", b"D")
        old_source = engine.PREFS["source"]
        old_folder = engine.PREFS["xsk_folder"]
        old_style = engine.PREFS["code_style"]
        old_length = engine.PREFS["code_length"]
        old_module = engine._module
        old_data = engine.DATA
        try:
            engine.PREFS.update(source=str(self.source), xsk_folder=str(self.output),
                                code_style="numeric", code_length="5")
            engine.DATA = self.root / "state"
            engine.DATA.mkdir()
            engine.CANCEL.clear()
            def module(name, label):
                if name == "xsk_keys.py":
                    from types import SimpleNamespace
                    return SimpleNamespace(get_key=lambda _: bytes(range(32)))
                return old_module(name, label)
            with patch.object(engine, "_module", side_effect=module):
                with stream.source_batches(self.source, self.output, cancelled=engine.CANCEL,
                                           batch_size=1) as rows:
                    outcome = engine.build_xsk(rows, "original", {
                        "xsk_folder": str(self.output),
                        "code_style": "numeric", "code_length": "5",
                    }, progressive=True)
                self.assertEqual(outcome["created"], 3)
                self.assertEqual(outcome["skipped"], 1)
                self.assertEqual(outcome["notReady"], 1)
                self.assertEqual(outcome["errors"], 0)
                first = list(self.output.rglob("*.xsk"))
                self.assertEqual(len(first), 3)
                self.assertTrue(all(p.read_bytes().startswith(b'XSK2') for p in first))
                self.assertEqual(len({package.open_package(p)["audio"]["sha256"]
                                      for p in first}), 3)
                parsed = [package.open_package(p, bytes(range(32))) for p in first]
                self.assertTrue(any(item["title"] == "เพลงจาก JSON" and
                                    item["artist"] == "นักร้องจาก JSON"
                                    for item in parsed))
                with stream.source_batches(self.source, self.output, cancelled=engine.CANCEL,
                                           batch_size=1) as rows:
                    repeat = engine.build_xsk(rows, "original", {
                        "xsk_folder": str(self.output),
                        "code_style": "numeric", "code_length": "5",
                    }, progressive=True)
                self.assertEqual(repeat["created"], 0)
                self.assertEqual(repeat["skipped"], 4)
                self.assertEqual(repeat["notReady"], 1)
        finally:
            engine.PREFS.update(source=old_source, xsk_folder=old_folder,
                                code_style=old_style, code_length=old_length)
            engine.DATA = old_data
            engine.CANCEL.clear()


if __name__ == "__main__":
    unittest.main()
