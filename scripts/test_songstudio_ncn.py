"""Regression: two-file song+lyrics import and historical NCN read-only parser.

New import uses one MIDI/KAR plus timed LRC/JSON. Legacy LYR/CUR is never
looked up to validate or publish new songs, but direct parser fixtures stay.
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

    def test_legacy_ncn_trio_not_used_as_new_song_lyrics(self):
        mid, lyr, cur = self.make_ncn()
        self.assertEqual(engine.scan_source(), 1)
        row = engine.FILES[0]
        self.assertNotIn("ncn", row)
        self.assertEqual(row["status"], "missing-lyrics")
        _, document, _ = engine.lyrics_package(row)
        self.assertIsNone(document)
        self.assertTrue(lyr.is_file() and cur.is_file(), "legacy sources stay untouched")

    def test_two_file_midi_and_lrc_retain_source_bytes(self):
        mid, lyr, cur = self.make_ncn("00011", "0")
        lrc = mid.with_suffix(".lrc")
        lrc.write_text("[00:01.00]เพลงสองไฟล์\n[00:02.00]บรรทัดที่สอง",encoding="utf-8")
        engine.scan_source()
        row = next(x for x in engine.FILES if x["code"] == "00011")
        self.assertEqual(row["lyrics_file"], str(lrc))
        self.assertEqual(row["source_format"], "SMF")
        lrc_text, doc, checksum = engine.lyrics_package(row)
        self.assertEqual(doc["lines"][0]["text"], "เพลงสองไฟล์")
        self.assertTrue(checksum)
        source_before = mid.read_bytes()
        with patch.object(engine, "convert", side_effect=lambda _row, output, preview=False:
                          Path(output).write_bytes(b"M4A-TEST-DATA"*500)):
            result = engine.build_library([row], "original", {"audio_only": False})
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["lyricsCount"], 1)
        self.assertEqual(mid.read_bytes(), source_before)

    def test_two_file_json_is_valid_timed_source(self):
        mid, _, _ = self.make_ncn("00012", "0")
        js = mid.with_suffix(".json")
        js.write_text(json.dumps({
            "schemaVersion":1,"songCode":"00012",
            "lines":[{"startTime":1.5,"endTime":3.0,"text":"เนื้อร้องพร้อมเวลา"}]
        },ensure_ascii=False),encoding="utf-8")
        engine.scan_source()
        row = next(x for x in engine.FILES if x["code"] == "00012")
        self.assertEqual(row["lyrics_file"],str(js))
        _, doc, _ = engine.lyrics_package(row)
        self.assertEqual(doc["lines"][0]["startTime"],1.5)
        self.assertEqual(doc["lines"][0]["text"],"เนื้อร้องพร้อมเวลา")

    def test_matching_lyrics_requires_unique_companion(self):
        mid, _, _ = self.make_ncn("00013", "0")
        mid.with_suffix(".lrc").write_text("[00:01.00]ทดสอบ",encoding="utf-8")
        mid.with_suffix(".json").write_text(json.dumps({
            "schemaVersion":1,"songCode":"00013","lines":[{"startTime":1,"text":"ซ้ำ"}]
        },ensure_ascii=False),encoding="utf-8")
        engine.scan_source()
        row=next(x for x in engine.FILES if x["code"]=="00013")
        self.assertEqual(row["status"],"ambiguous-lyrics")
        with self.assertRaisesRegex(ValueError,"LRC และ JSON"):
            engine.lyrics_package(row)

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



    def test_preview_inspects_only_timed_lrc_json_not_legacy_cursor(self):
        mid, lyr, cur = self.make_ncn("A123", "A")
        lrc = mid.with_suffix(".lrc")
        lrc.write_text("[00:01.00]สวัสดี\n[00:02.00]ท่อนสอง",encoding="utf-8")
        engine.scan_source()
        song_id=next(x for x in engine.FILES if x["code"]=="A123")["id"]
        report=engine.preview_source_report(song_id)
        self.assertTrue(report["timedLyricsReady"])
        self.assertTrue(report["complete"])
        self.assertIn("inspect:lrc",{x["value"] for x in report["options"]})
        self.assertNotIn("inspect:lyr",{x["value"] for x in report["options"]})
        self.assertNotIn("inspect:cur",{x["value"] for x in report["options"]})
        self.assertIn("สวัสดี",engine.preview_inspect(song_id,"inspect:lrc")["text"])
        with self.assertRaisesRegex(ValueError,"ยกเลิก"):
            engine.preview_inspect(song_id,"inspect:cur")
        self.assertTrue(lyr.is_file() and cur.is_file())

    def test_missing_lyrics_prevents_false_complete_preview(self):
        self.make_ncn("B222", "B", with_cursor=False)
        engine.scan_source()
        row=next(x for x in engine.FILES if x["code"]=="B222")
        report=engine.preview_source_report(row["id"])
        self.assertFalse(report["complete"])
        self.assertFalse(report["timedLyricsReady"])
        self.assertTrue(any(x["required"] and not x["found"]
                            for x in report["components"]))

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

    def test_two_file_mid_and_json_build_matches_single_code(self):
        mid, lyr, cur = self.make_ncn("00046", "0", lyric="เพลงทดสอบ")
        companion=mid.with_suffix(".json")
        companion.write_text(json.dumps({
            "schemaVersion":1,"songCode":"00046",
            "lines":[{"startTime":0.5,"endTime":2,"text":"เพลงทดสอบ"}]
        },ensure_ascii=False),encoding="utf-8")
        engine.scan_source()
        row=next(x for x in engine.FILES if x["code"]=="00046")
        with patch.object(engine,"convert",side_effect=lambda _row,output,preview=False:
                          Path(output).write_bytes(b"M4A-TEST-DATA"*500)):
            completed=engine.build_library([row],"original",{"audio_only":False})
        self.assertEqual((completed["created"],completed["lyricsCount"],completed["errors"]),
                         (1,1,0),completed)
        root=self.workspace/"StageWeb"
        audio=root/"audio"/"0"/"00046.mid"
        timed=root/"lyrics"/"0"/"00046.json"
        self.assertEqual(audio.read_bytes(),mid.read_bytes())
        self.assertEqual(json.loads(timed.read_text(encoding="utf-8"))["lines"][0]["text"],
                         "เพลงทดสอบ")
        self.assertTrue((root/"current.json").is_file())


if __name__ == "__main__":
    unittest.main()
