"""NCN timing regressions derived from Nick Karaoke CUR semantics.

Keep source lyric bytes and cursor positions authoritative; no estimated onset
may masquerade as a measured CUR cue.
"""
from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ncn_reader
import plus_core


def _varlen(value):
    result = [value & 127]
    value >>= 7
    while value:
        result.insert(0, 0x80 | (value & 127))
        value >>= 7
    return bytes(result)


def _midi_20_seconds():
    track = (b"\x00\xff\x51\x03\x07\xa1\x20"
             + b"\x00\x90\x3c\x64"
             + _varlen(480 * 20) + b"\x80\x3c\x00"
             + b"\x00\xff\x2f\x00")
    return (b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480)
            + b"MTrk" + struct.pack(">I", len(track)) + track)


class NcnLineEndRegression(unittest.TestCase):
    def test_last_measured_cursor_after_four_seconds_is_not_clipped(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            midi = root / "00001.mid"
            lyr = root / "00001.lyr"
            cur = root / "00001.cur"
            midi.write_bytes(_midi_20_seconds())
            lyr.write_bytes("ชื่อเพลง\nศิลปิน\nC\n.\nABCD\n".encode("cp874"))
            # NCN uses 24 CUR units per MIDI quarter note, and consumes one
            # entry for each lyric line marker. Last D onset at 6s (288 units).
            cur.write_bytes(struct.pack("<5H", 0, 0, 24, 48, 288))
            original_media = midi.read_bytes()
            doc = ncn_reader.ncn_document({
                "midi": str(midi), "lyrics": str(lyr),
                "cursor": str(cur), "missing": [], "code": "00001",
            })
            line = doc["lines"][0]
            self.assertEqual(line["text"], "ABCD")
            self.assertAlmostEqual(line["characters"][-1]["startTime"], 6.)
            self.assertGreater(line["endTime"], 6.)
            self.assertTrue(line["endTimeEstimated"])
            self.assertGreaterEqual(line["endTime"], max(
                s["start"] + s["duration"] for s in line["syllables"]))
            rows = plus_core.valid_lines(doc)
            self.assertEqual(rows[0][0], "ABCD")
            self.assertEqual(rows[0][-1], "estimated")
            self.assertEqual(midi.read_bytes(), original_media)

    def test_overlapping_lines_preserve_all_measured_onsets(self):
        doc = ncn_reader._timed_lines_to_json([
            {"text": "AB", "startTime": 1., "characters": [
                {"text": "A", "startTime": 1.},
                {"text": "B", "startTime": 4.5},
            ]},
            {"text": "CD", "startTime": 2., "characters": [
                {"text": "C", "startTime": 2.},
                {"text": "D", "startTime": 2.3},
            ]},
        ], "42", "NCN")
        self.assertGreater(doc["lines"][0]["endTime"], 4.5)
        self.assertTrue(doc["lines"][0]["endTimeEstimated"])
        self.assertEqual(len(plus_core.valid_lines(doc)), 2)

    def test_nick_extreme_legacy_midi_signatures_keep_original_bytes(self):
        """Lock/Good from the library are real SMF layouts with extra tails."""
        with tempfile.TemporaryDirectory() as d:
            for signature in (b"Lock", b"Good", b"TECH", b"NCN1"):
                with self.subTest(signature=signature):
                    source = Path(d) / (signature.decode("ascii") + ".mid")
                    original = signature + _midi_20_seconds()[4:] + b"legacy trailer"
                    source.write_bytes(original)
                    division, tempos, events, duration = ncn_reader.midi_events(
                        source, include_duration=True)
                    self.assertEqual(division, 480)
                    self.assertGreater(duration, 0)
                    self.assertEqual(source.read_bytes(), original)
            bad = Path(d) / "unknown.mid"
            bad.write_bytes(b"NOPE" + _midi_20_seconds()[4:])
            with self.assertRaisesRegex(ValueError, "4E 4F 50 45"):
                ncn_reader.midi_events(bad)

    def test_last_line_default_four_seconds_when_no_late_cue(self):
        doc = ncn_reader._timed_lines_to_json([
            {"text": "AB", "startTime": 1., "characters": [
                {"text": "A", "startTime": 1.},
                {"text": "B", "startTime": 2.},
            ]},
        ], "42", "NCN")
        self.assertAlmostEqual(doc["lines"][0]["endTime"], 5.)
        self.assertTrue(doc["lines"][0]["endTimeEstimated"])


if __name__ == "__main__":
    unittest.main()
