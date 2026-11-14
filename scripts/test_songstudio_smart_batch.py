"""Smart Batch regression: anchored timing, skips, durable ZIP and rollback."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]


def source(relative, name):
    spec = importlib.util.spec_from_file_location(name, REPO / relative)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bulk = source("songstudio-pc/lyric_text_groups.py", "xstage_smart_bulk")
export = source("songstudio-pc/song_export.py", "xstage_smart_export")


class AnchorTests(unittest.TestCase):
    def test_only_changed_span_receives_new_timestamps(self):
        old = "ABCDEF"
        line = {"startTime": 1, "endTime": 6,
                "syllables": [{"text": ch, "start": 1 + index * 0.7,
                               "duration": .7}
                              for index, ch in enumerate(old)]}
        initial = {glyph["text"]: glyph["start"] for glyph in line["syllables"]}
        self.assertTrue(bulk._retime_visual_units(line, old, "ABXYDEF"))
        positions = {glyph["text"]: glyph["start"] for glyph in line["syllables"]}
        for glyph in "ABDEF":
            self.assertAlmostEqual(positions[glyph], initial[glyph], places=4,
                                   msg=f"unchanged {glyph} must keep original time")
        self.assertLess(positions["B"], positions["X"])
        self.assertLess(positions["X"], positions["Y"])
        self.assertLess(positions["Y"], positions["D"])
        self.assertEqual(line["startTime"], 1)
        self.assertEqual(line["endTime"], 6)
        self.assertEqual(line["timingMethod"], "anchored-changed-spans")
        self.assertTrue(line["timingEstimated"])

    def test_equal_visible_lengths_reuse_all_original_cues(self):
        line = {"startTime": 0, "endTime": 3,
                "syllables": [{"text": ch, "start": i + .1, "duration": .4}
                              for i, ch in enumerate("ABC")]}
        self.assertFalse(bulk._retime_visual_units(line, "ABC", "XYZ"))
        self.assertEqual([x["start"] for x in line["syllables"]], [.1, 1.1, 2.1])
        self.assertEqual(line["timingMethod"], "original-cue-positions")
        self.assertTrue(line["timingEstimated"],
                        "Reusing cue positions is not verified sung alignment")

    def test_combining_thai_marks_are_one_display_glyph(self):
        original = "กิข่า"
        visual = bulk._display_units(original)
        self.assertEqual(visual, ["กิ", "ข่", "า"])
        line = {"startTime": 2, "endTime": 7,
                "syllables": [{"text": x, "start": 2+i, "duration": .5}
                              for i, x in enumerate(visual)]}
        self.assertTrue(bulk._retime_visual_units(line, original, "กิข่าใหม่"))
        self.assertEqual(line["syllables"][0]["text"], "กิ")
        self.assertEqual(line["syllables"][0]["start"], 2)
        self.assertEqual(line["syllables"][1]["start"], 3)

    def test_invalid_or_insufficient_original_time_is_rejected(self):
        line = {"startTime": 1, "endTime": 4, "syllables": [
            {"text": "A", "start": 2}, {"text": "B", "start": 1.5}]}
        with self.assertRaisesRegex(ValueError, "ย้อนหลัง"):
            bulk._retime_visual_units(line, "AB", "AXXB")
        broken = {"startTime": 1, "endTime": 1, "syllables": []}
        with self.assertRaisesRegex(ValueError, "ช่วงเวลา"):
            bulk._retime_visual_units(broken, "ABC", "XYZ")
        outside = {"startTime": 1, "endTime": 4, "syllables": [
            {"text": "A", "start": 1}, {"text": "B", "start": 8}]}
        with self.assertRaisesRegex(ValueError, "ไม่ปลอดภัย"):
            bulk._retime_visual_units(outside, "AB", "AXB")


class BatchSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "songs"
        self.backups = Path(self.temp.name) / "backups"
        self.records = []
        self.originals = {}
        for i in range(1, 5):
            code = f"{i:04d}"
            audio = self.root / "audio" / "0" / (code + ".m4a")
            audio.parent.mkdir(parents=True, exist_ok=True)
            audio.write_bytes((code * 500).encode("utf-8"))
            raw = "".join(
                f"[00:{(n+1)*3:02d}.00]{word}\n"
                for n, word in enumerate(["HELLO", "intro", f"verse-{code}",
                                          "bridge", "outro", "LAST"]))
            json_path = export.save_lyrics(self.root, audio, raw, code)
            record = {"webSongId": f"audio/0/{code}", "code": code,
                      "title": "Song " + code, "artist": "Artist",
                      "bucket": "0", "sourceFormat": "MP3", "mode": "original",
                      "vocals": None,
                      "audio": {"path": f"audio/0/{code}.m4a", "size": audio.stat().st_size},
                      "lyrics": {"path": f"lyrics/0/{code}.json"}}
            self.records.append(record)
            self.originals[code] = {
                "audio": audio.read_bytes(), "json": json_path.read_bytes(),
                "lrc": json_path.with_suffix(".lrc").read_bytes()
            }
        export.publish_batch(self.root, self.records)

    def tearDown(self):
        self.temp.cleanup()

    def snapshot_and_group(self):
        snapshot = bulk.scan(self.root, export)
        group = bulk.list_groups(snapshot, "first")["rows"][0]
        return snapshot, group

    def test_skips_mutated_json_and_undoes_valid_subset(self):
        snapshot, group = self.snapshot_and_group()
        corrupt = self.root / "lyrics" / "0" / "0004.json"
        corrupt.write_text("{ invalid JSON", encoding="utf-8")
        broken = corrupt.read_bytes()
        output = bulk.apply_many_smart(
            self.root, export, snapshot, [group["id"]],
            "HELLO NEW", self.backups, expected_count=4)
        self.assertEqual(output["changedSongs"], 3)
        self.assertEqual(output["skippedInvalid"], 1)
        self.assertTrue(Path(output["skippedReport"]).is_file())
        self.assertEqual(corrupt.read_bytes(), broken)
        self.assertEqual(bulk.latest_backup(self.backups, self.root)["id"],
                         output["backupId"])
        for code in ("0001", "0002", "0003"):
            doc = json.loads((self.root / "lyrics" / "0" / f"{code}.json").read_text())
            self.assertEqual(doc["lines"][0]["text"], "HELLO NEW")
            self.assertEqual((self.root / "audio" / "0" / f"{code}.m4a").read_bytes(),
                             self.originals[code]["audio"])
        pending = bulk.list_groups(snapshot, "first", repeats_only=False)["rows"]
        self.assertEqual(next(x for x in pending if x["text"] == "HELLO")["count"], 1)
        bulk.undo(self.backups, self.root, output["backupId"])
        for code in ("0001", "0002", "0003"):
            self.assertEqual(
                (self.root / "lyrics" / "0" / f"{code}.json").read_bytes(),
                self.originals[code]["json"])
            self.assertEqual(
                (self.root / "lyrics" / "0" / f"{code}.lrc").read_bytes(),
                self.originals[code]["lrc"])
        self.assertEqual(corrupt.read_bytes(), broken)

    def test_cancel_before_commit_does_not_change_sources(self):
        snapshot, group = self.snapshot_and_group()
        event = threading.Event()
        event.set()
        with self.assertRaisesRegex(RuntimeError, "ยกเลิก"):
            bulk.apply_many_smart(self.root, export, snapshot, [group["id"]],
                                  "NEW", self.backups, expected_count=4,
                                  cancelled=event)
        for code, original in self.originals.items():
            self.assertEqual((self.root / "lyrics" / "0" / f"{code}.json").read_bytes(),
                             original["json"])
        self.assertFalse(list(self.backups.glob("*.json")))

    def test_write_failure_rolls_back_every_valid_file(self):
        snapshot, group = self.snapshot_and_group()
        real_write = bulk._atomic_bytes

        def interrupted(path, content):
            if Path(path).name == "0002.json":
                raise OSError("simulate storage write fault")
            return real_write(path, content)

        with patch.object(bulk, "_atomic_bytes", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "storage write fault"):
                bulk.apply_many_smart(self.root, export, snapshot, [group["id"]],
                                      "REPLACED", self.backups, expected_count=4)
        for code, original in self.originals.items():
            self.assertEqual((self.root / "lyrics" / "0" / f"{code}.json").read_bytes(),
                             original["json"])
            self.assertEqual((self.root / "lyrics" / "0" / f"{code}.lrc").read_bytes(),
                             original["lrc"])

    def test_rechecks_catalog_and_confirmation_before_writes(self):
        snapshot, group = self.snapshot_and_group()
        with self.assertRaisesRegex(ValueError, "จำนวน"):
            bulk.apply_many_smart(self.root, export, snapshot, [group["id"]],
                                  "NEW", self.backups, expected_count=1000)
        export.publish_batch(self.root, self.records)
        with self.assertRaisesRegex(ValueError, "เปลี่ยน"):
            bulk.apply_many_smart(self.root, export, snapshot, [group["id"]],
                                  "NEW", self.backups, expected_count=4)
        self.assertFalse(self.backups.exists())

    def test_incomplete_ncn_is_excluded_before_grouping(self):
        file = self.root / "lyrics" / "0" / "0004.json"
        doc = json.loads(file.read_text(encoding="utf-8"))
        doc["sourceFormat"] = "NCN"
        doc["metadata"] = {"timingComplete": False}
        file.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        snap = bulk.scan(self.root, export)
        self.assertEqual(snap["songs"], 3)
        self.assertEqual(snap["skippedInvalid"], 1)
        self.assertEqual(bulk.list_groups(snap, "first")["rows"][0]["count"], 3)

    def test_all_invalid_returns_safe_skip_report(self):
        snapshot, group = self.snapshot_and_group()
        for code in self.originals:
            (self.root / "lyrics" / "0" / f"{code}.json").write_text(
                "not json", encoding="utf-8")
        result = bulk.apply_many_smart(self.root, export, snapshot, [group["id"]],
                                       "NEW", self.backups, expected_count=4)
        self.assertEqual(result["changedSongs"], 0)
        self.assertEqual(result["skippedInvalid"], 4)
        self.assertFalse(list(self.backups.glob("*.zip")))


if __name__ == "__main__":
    unittest.main()
