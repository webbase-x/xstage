"""Regression tests for real Nick Karaoke NCN mirrored folder sources.

A single logical song is Song/ID.MID + Lyrics/ID.LYR + Cursor/ID.CUR.
All components must be matched by code AND bucket, never filename alone.
"""
from __future__ import annotations

from array import array
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import json
import struct
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
ENGINE_SPEC = spec_from_file_location("xstage_ncn_test_engine", REPO / "songstudio-pc" / "engine.py")
engine = module_from_spec(ENGINE_SPEC)
ENGINE_SPEC.loader.exec_module(engine)
ncn = engine.NCN


def var(n):
    out = [n & 127]
    n >>= 7
    while n:
        out.insert(0, 0x80 | (n & 127))
        n >>= 7
    return bytes(out)


def midi(tracks=None):
    if tracks is None:
        tracks = [(0, b"\xff\x51\x03\x07\xa1\x20")]
    raw = b""
    for dt, evt in tracks:
        raw += var(dt) + evt
    raw += b"\x00\xff\x2f\x00"
    return (b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480) +
            b"MTrk" + struct.pack(">I", len(raw)) + raw)


class NcnSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.ncn = self.dir / "MIDI" / "NCN"
        self.workspace = self.dir / "Export"
        self.workspace.mkdir()
        engine.PREFS["workspace"] = str(self.workspace)
        engine.PREFS["source"] = str(self.dir / "MIDI")
        engine.NOTES.clear()
        engine.FILES.clear()
        engine.FILE_BY_ID.clear()
        engine.CANCEL.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def make_ncn(self, code="00001", bucket="0", lyric="สวัสดี", artist="นักร้องทดสอบ",
                 with_cursor=True, with_lyrics=True):
        base = self.ncn / "Song" / bucket
        base.mkdir(parents=True, exist_ok=True)
        mid = base / (code + ".MID")
        mid.write_bytes(midi())
        lpath = self.ncn / "Lyrics" / bucket / (code + ".LYR")
        cpath = self.ncn / "Cursor" / bucket / (code + ".CUR")
        if with_lyrics:
            lpath.parent.mkdir(parents=True, exist_ok=True)
            lpath.write_bytes(("ชื่อเพลงทดสอบ\n" + artist + "\nC\n\n" + lyric + "\n")
                              .encode("cp874"))
        if with_cursor:
            cpath.parent.mkdir(parents=True, exist_ok=True)
            values = [0] + [i * 12 for i in range(len(lyric))]
            cpath.write_bytes(struct.pack("<"+"H"*len(values), *values) + b"\xff")
        return mid, lpath, cpath

    def test_ncns_with_mirrored_cursor_lyrics_song_resolve_one_song(self):
        mid, lyr, cur = self.make_ncn()
        self.assertEqual(engine.scan_source(), 1)
        row = engine.FILES[0]
        self.assertEqual(row["code"], "00001")
        self.assertEqual(row["title"], "ชื่อเพลงทดสอบ")
        self.assertEqual(row["artist"], "นักร้องทดสอบ")
        self.assertEqual(row["source_format"], "NCN")
        self.assertEqual(row["status"], "ready")
        self.assertEqual(Path(row["ncn"]["lyrics"]), lyr)
        self.assertEqual(Path(row["ncn"]["cursor"]), cur)
        lrc, document, fingerprint = engine.lyrics_package(row)
        self.assertIn("สวัสดี", lrc)
        self.assertEqual(document["sourceFormat"], "NCN")
        self.assertEqual(document["metadata"]["artist"], "นักร้องทดสอบ")
        self.assertEqual(document["lines"][0]["text"], "สวัสดี")
        self.assertEqual(len(document["lines"][0]["characters"]), 4)
        self.assertAlmostEqual(document["lines"][0]["characters"][1]["startTime"], .25)
        self.assertTrue(fingerprint)

    def test_scan_when_user_selects_song_folder_only_finds_sibling_lyrics(self):
        mid, lyr, cur = self.make_ncn("A001", "A")
        engine.PREFS["source"] = str(self.ncn / "Song")
        self.assertEqual(engine.scan_source(), 1)
        row = engine.FILES[0]
        self.assertEqual(row["title"], "ชื่อเพลงทดสอบ")
        self.assertEqual(row["source_format"], "NCN")
        self.assertEqual(row["ncn"]["lyrics"], str(lyr))
        self.assertEqual(row["ncn"]["cursor"], str(cur))

    def test_missing_ncn_cursor_is_reported_not_saved_as_fake_lyrics(self):
        self.make_ncn(with_cursor=False)
        self.assertEqual(engine.scan_source(), 1)
        row = engine.FILES[0]
        self.assertEqual(row["status"], "missing-companion")
        with self.assertRaisesRegex(ValueError, "NCN ไม่ครบ"):
            engine.lyrics_package(row)
        with self.assertRaisesRegex(RuntimeError, "ไม่ครบ"):
            engine.build_library([row], "original", {"audio_only": False})
        self.assertEqual(list(self.workspace.rglob("*.m4a")), [])
        self.assertEqual(list(self.workspace.rglob("*.json")), [])

    def test_create_ncn_byte_identical_midi_and_timed_lyrics_then_repair_without_reencoding(self):
        mid, lyr, cur = self.make_ncn()
        engine.scan_source()
        row = engine.FILES[0]
        def dummy_convert(_, target, preview=False):
            Path(target).write_bytes(b"A" * 5000)
        with patch.object(engine, "convert", side_effect=dummy_convert) as convert:
            first = engine.build_library([row], "original", {"audio_only": False})
            self.assertEqual(first["created"], 1)
            self.assertEqual(first["lyricsCount"], 1)
            audio = self.workspace / "StageWeb" / "audio" / "0" / "00001.mid"
            lyrics_file = self.workspace / "StageWeb" / "lyrics" / "0" / "00001.json"
            self.assertEqual(audio.read_bytes(), mid.read_bytes())
            self.assertTrue(lyrics_file.is_file())
            saved = json.loads(lyrics_file.read_text(encoding="utf-8"))
            self.assertEqual(saved["sourceFormat"], "NCN")
            self.assertEqual(saved["lines"][0]["text"], "สวัสดี")
            second = engine.build_library([row], "original", {"audio_only": False})
            self.assertEqual((second["created"], second["skipped"], second["lyricsCount"]),
                             (0, 1, 0))
            self.assertEqual(convert.call_count, 0)
            # Preserve original MIDI, and repair newly updated LYR on rerun.
            lyr.write_bytes("ชื่อเพลงทดสอบ\nนักร้องทดสอบ\nC\n\nเนื้อร้องใหม่\n".encode("cp874"))
            cur.write_bytes(struct.pack("<"+"H"* (len("เนื้อร้องใหม่")+1),
                                        *range(len("เนื้อร้องใหม่")+1)))
            third = engine.build_library([row], "original", {"audio_only": False})
            self.assertEqual((third["created"], third["skipped"], third["lyricsCount"]),
                             (0, 1, 1))
            self.assertEqual(convert.call_count, 0)
            corrected = json.loads(lyrics_file.read_text(encoding="utf-8"))
            self.assertEqual(corrected["lines"][0]["text"], "เนื้อร้องใหม่")
            self.assertEqual(len(list(self.workspace.rglob("*.mid"))), 1)
            self.assertTrue(list(lyrics_file.parent.glob("00001.json.before-repair-*.bak")))

    def test_same_midi_different_ncn_lyrics_are_different_songs(self):
        self.make_ncn("00001", "0", lyric="คนละเพลง")
        self.make_ncn("10001", "1", lyric="อีกหนึ่งเพลง")
        engine.scan_source()
        rows = engine.FILES
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(engine._source_digest(rows[0], engine._song_export_module()),
                            engine._source_digest(rows[1], engine._song_export_module()))
        with patch.object(engine, "convert", side_effect=lambda row, target, preview=False:
                          Path(target).write_bytes(b"A" * 5000)):
            result = engine.build_library(rows, "original", {"audio_only": False})
        self.assertEqual(result["created"], 2)
        self.assertEqual(len(list(self.workspace.rglob("*.mid"))), 2)

    def test_kar_embedded_lyrics_ignore_title_metadata(self):
        title = "เพลงตัวอย่าง".encode("cp874")
        artist = "นักร้อง".encode("cp874")
        lines = [
            (0, b"\xff\x01" + var(len(title)+2) + b"@T" + title),
            (0, b"\xff\x01" + var(len(artist)+2) + b"@T" + artist),
            (480, b"\xff\x05" + var(len("สวัสดี".encode("cp874"))+1)
             + b"/" + "สวัสดี".encode("cp874")),
        ]
        file = self.dir / "karaoke.kar"
        file.write_bytes(midi(lines))
        doc = ncn.kar_document(file, "karaoke")
        self.assertEqual(doc["metadata"]["artist"], "นักร้อง")
        self.assertEqual(doc["lines"][0]["text"], "สวัสดี")
        self.assertAlmostEqual(doc["lines"][0]["startTime"], .5)

    def test_invalid_empty_lyrics_document_is_not_published(self):
        export = engine._song_export_module()
        root = self.workspace / "StageWeb"
        output = root / "audio" / "0" / "00001.m4a"
        output.parent.mkdir(parents=True)
        output.write_bytes(b"M" * 4096)
        with self.assertRaisesRegex(ValueError, "ไม่มีเนื้อร้อง"):
            export.save_lyrics(root, output, "plain text no LRC", "00001")
        self.assertEqual(list((root / "lyrics").rglob("*.json")) if
                         (root / "lyrics").exists() else [], [])



    def test_component_inspection_and_real_karaoke_characters(self):
        mid, lyr, cur = self.make_ncn("A123", "A")
        engine.scan_source()
        song_id = engine.FILES[0]["id"]
        report = engine.preview_source_report(song_id)
        self.assertTrue(report["timedLyricsReady"])
        self.assertTrue(report["complete"])
        self.assertEqual(len([x for x in report["components"]
                              if x["found"] and x["required"]]), 2)
        selections = {x["value"] for x in report["options"]}
        self.assertIn("midi:" + str(song_id), selections)
        self.assertIn("inspect:lyr", selections)
        self.assertIn("inspect:cur", selections)
        lyric_check = engine.preview_inspect(song_id, "inspect:lyr")
        cursor_check = engine.preview_inspect(song_id, "inspect:cur")
        self.assertIn("สวัสดี", lyric_check["text"])
        self.assertIn("ตำแหน่ง", cursor_check["message"])
        preview = engine.preview_lyrics(song_id)
        self.assertEqual(preview["status"], "found")
        self.assertEqual(preview["source"], "NCN")
        self.assertEqual(preview["lines"][0]["text"], "สวัสดี")
        self.assertEqual(len(preview["lines"][0]["characters"]), 4)
        self.assertAlmostEqual(preview["lines"][0]["characters"][1]["startTime"], .25)

    def test_incomplete_ncn_picker_reports_missing_cursor(self):
        self.make_ncn("B222", "B", with_cursor=False)
        engine.scan_source()
        song_id = engine.FILES[0]["id"]
        report = engine.preview_source_report(song_id)
        self.assertFalse(report["complete"])
        self.assertFalse(report["timedLyricsReady"])
        self.assertTrue(any(x["type"] == "Cursor · CUR" and not x["found"]
                            for x in report["components"]))
        self.assertNotIn("inspect:cur", {x["value"] for x in report["options"]})


    def test_karaoke_pc_ncn_cp874_crlf_and_untimed_footer(self):
        """Karaoke PC removes an untimed vendor credit, not real song words."""
        mid, lyr, cur = self.make_ncn("00042", "0", lyric="กข")
        lyrics = "ชื่อเพลง\r\nศิลปิน\r\nC\r\n.\r\nกข\r\nNick_Karaoke Professional\r\n"
        lyr.write_bytes(lyrics.encode("cp874"))
        cur.write_bytes(struct.pack("<3H", 0, 0, 24))
        doc = ncn.ncn_document(ncn.resolve_companions(mid))
        self.assertEqual([x["text"] for x in doc["lines"]], ["กข"])
        self.assertAlmostEqual(doc["lines"][0]["characters"][1]["startTime"], .5)
        self.assertEqual(doc["metadata"]["removedUntimedFooterLines"], 1)
        self.assertTrue(doc["metadata"]["timingComplete"])

    def test_karaoke_pc_ncn_partial_cursor_preserves_verified_prefix(self):
        """Never invent the remainder of a truncated CUR file."""
        mid, lyr, cur = self.make_ncn("00043", "0", lyric="ABCD")
        cur.write_bytes(struct.pack("<3H", 0, 0, 24))
        doc = ncn.ncn_document(ncn.resolve_companions(mid))
        self.assertEqual(doc["lines"][0]["text"], "AB")
        self.assertEqual(len(doc["lines"][0]["characters"]), 2)
        self.assertFalse(doc["metadata"]["timingComplete"])
        self.assertTrue(doc["metadata"]["timingWarnings"])

    def test_karaoke_pc_ncn_thai_mark_and_sentinel(self):
        """One CP874 byte consumes a cursor, but Thai marks paint together."""
        mid, lyr, cur = self.make_ncn("00044", "0", lyric="กิข")
        cur.write_bytes(struct.pack("<5H", 0, 0, 12, 24, 65535))
        doc = ncn.ncn_document(ncn.resolve_companions(mid))
        self.assertEqual(doc["lines"][0]["text"], "กิข")
        self.assertEqual([x["text"] for x in doc["lines"][0]["characters"]], ["กิ", "ข"])
        self.assertAlmostEqual(doc["lines"][0]["characters"][1]["startTime"], .5)
        self.assertEqual(doc["metadata"]["unusedCursorValues"], 1)

    def test_karaoke_pc_ncn_uses_original_midi_tempo_change(self):
        mid, lyr, cur = self.make_ncn("00045", "0", lyric="กข")
        mid.write_bytes(midi([
            (0, b"\xff\x51\x03\x07\xa1\x20"),
            (480, b"\xff\x51\x03\x0f\x42\x40"),
        ]))  # 120 BPM until tick 480, then 60 BPM.
        cur.write_bytes(struct.pack("<3H", 0, 0, 48))
        doc = ncn.ncn_document(ncn.resolve_companions(mid))
        self.assertAlmostEqual(doc["lines"][0]["characters"][1]["startTime"], 1.5)

    def test_karaoke_pc_plain_embedded_midi_crlf_and_soft_karaoke(self):
        """PC Karaoke handles both MIDI lyric CR/LF and KAR slash separators."""
        def meta(tag, value):
            return b"\xff" + bytes([tag]) + var(len(value)) + value
        path = self.dir / "70001.kar"
        path.write_bytes(midi([
            (0, meta(1, b"@LTHAI")),
            (0, meta(1, b"@TExample")),
            (480, meta(5, "หนึ่ง".encode("cp874"))),
            (480, meta(5, b"\r")),
            (0, meta(5, "สอง".encode("cp874"))),
            (480, meta(5, b"\\Three")),
        ]))
        doc = ncn.kar_document(path, "70001")
        self.assertEqual([x["text"] for x in doc["lines"]], ["หนึ่ง", "สอง", "Three"])
        self.assertEqual(doc["metadata"]["title"], "Example")
        self.assertAlmostEqual(doc["lines"][0]["startTime"], .5)
        self.assertAlmostEqual(doc["lines"][1]["startTime"], 1.)
        self.assertAlmostEqual(doc["lines"][2]["startTime"], 1.5)
        self.assertEqual(doc["lines"][0]["characters"][0]["text"], "หนึ่ง")

    def test_karaoke_pc_byte_identical_mid_plus_real_lyrics_json(self):
        """Existing publishing engine saves both outputs under ONE song code."""
        mid, lyr, cur = self.make_ncn("00046", "0", lyric="เพลงทดสอบ")
        engine.scan_source()
        row = next(x for x in engine.FILES if x["code"] == "00046")
        with patch.object(engine, "convert", side_effect=lambda _row, output, preview=False:
                          Path(output).write_bytes(b"M4A-TEST-DATA" * 500)):
            completed = engine.build_library([row], "original", {"audio_only": False})
        self.assertEqual((completed["created"], completed["lyricsCount"],
                          completed["errors"]), (1, 1, 0), completed)
        root = self.workspace / "StageWeb"
        audio = root / "audio" / "0" / "00046.mid"
        lrc = root / "lyrics" / "0" / "00046.lrc"
        timed = root / "lyrics" / "0" / "00046.json"
        self.assertEqual(audio.read_bytes(),mid.read_bytes())
        self.assertIn("เพลงทดสอบ", lrc.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(timed.read_text(encoding="utf-8"))["sourceFormat"], "NCN")
        self.assertTrue((root / "current.json").is_file())


if __name__ == "__main__":
    unittest.main()
