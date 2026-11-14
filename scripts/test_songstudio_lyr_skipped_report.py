"""Skipped LYR reports and explicit recheck: always read-only."""
import csv
import importlib.util
import io
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "songstudio-pc"


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


bulk = module("skip_report_bulk", "lyric_text_groups.py")
editor = module("skip_report_ncn", "ncn_bulk_editor.py")


class SkippedReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "NCN"
        self.lyrics = self.root / "Lyrics" / "ไทย"
        self.lyrics.mkdir(parents=True)
        (self.root / "Song").mkdir()
        (self.root / "Cursor").mkdir()

    def write(self, filename, body=None, *, raw=None):
        target = self.lyrics / filename
        if raw is None:
            body = body if body is not None else [
                "หัวเพลง", "ท่อนสอง", "ท่อนสาม", "ท้ายเพลง"
            ]
            raw = ("เพลงไทย\r\nศิลปิน\r\nC\r\n.\r\n" +
                   "\r\n".join(body) + "\r\n\x1a").encode("cp874")
        target.write_bytes(raw)
        return target

    def seed(self):
        good = self.write("G01.LYR")
        short = self.write("S02.LYR", ["สั้น", "อีกท่อน"])
        corrupt = self.write("E03.LYR", raw=b"one\r\ntwo\r\nthree\r\nfour\r\n\x81\r\n" * 2)
        nul = self.write("N04.LYR", ["A", "B", "\x00", "D"])
        big = self.write("B05.LYR", raw=b"x" * (1024 * 1024 + 1))
        unsafe = self.write("=SUM(1+1).LYR", ["X"])
        return good, short, corrupt, nul, big, unsafe

    def test_full_report_reasons_pagination_csv_and_no_original_modification(self):
        paths = self.seed()
        originals = {p: p.read_bytes() for p in paths}
        snapshot = editor.scan(self.root, None, bulk)
        self.assertEqual(snapshot["inspected"], 6)
        self.assertEqual(snapshot["songs"], 1)
        self.assertEqual(snapshot["skippedInvalid"], 5)
        self.assertEqual(len(snapshot["skippedRows"]), 5)
        self.assertEqual(sum(r["count"] for r in snapshot["skippedReasons"]), 5)
        categories = {r["category"] for r in snapshot["skippedRows"]}
        self.assertIn("short_lyrics", categories)
        self.assertIn("too_large", categories)
        self.assertIn("encoding", categories)
        self.assertIn("invalid_chars", categories)
        page = editor.skipped_page(snapshot, offset=1, limit=2)
        self.assertEqual(page["total"], 5)
        self.assertEqual(len(page["rows"]), 2)
        self.assertEqual(page["skipped"], 5)
        csvbytes = editor.skipped_csv(snapshot)
        self.assertTrue(csvbytes.startswith(b"\xef\xbb\xbf"))
        csvrows = list(csv.reader(io.StringIO(csvbytes[3:].decode("utf-8"))))
        self.assertEqual(len(csvrows), 6)
        self.assertTrue(any("=SUM(1+1).LYR" in r[0] for r in csvrows[1:]))
        # Filename is safe when nested under a bucket; also test a *bare*
        # filename starting with "=" to verify formula-injection prevention.
        malicious = {"skippedRows": [{"file": "=2+2.LYR", "category": "other",
            "label": "ทดสอบ", "reason": "ไม่รองรับ"}]}
        sample = list(csv.reader(io.StringIO(
            editor.skipped_csv(malicious)[3:].decode("utf-8"))))
        self.assertEqual(sample[1][0], "'=2+2.LYR")
        self.assertTrue(all("ยังไม่ได้ตรวจซ้ำ" in r[1] for r in csvrows[1:]))
        for path, value in originals.items():
            self.assertEqual(path.read_bytes(), value)

    def test_all_invalid_lyrics_still_produce_recoverable_report(self):
        bad = self.write("ONLY.LYR", ["สั้น"])
        snap = editor.scan(self.root, None, bulk)
        self.assertEqual((snap["songs"], snap["skippedInvalid"]), (0, 1))
        self.assertEqual(editor.skipped_page(snap)["total"], 1)
        self.assertIn("ONLY.LYR", editor.skipped_csv(snap).decode("utf-8-sig"))
        self.write("ONLY.LYR")
        checked = editor.recheck_skipped(snap, bulk)
        self.assertEqual((checked["songs"], checked["skippedInvalid"]), (1, 0))
        self.assertEqual(checked["recheckSummary"]["recovered"], 1)
        self.assertEqual(editor.skipped_page(checked, view="recovered")["total"], 1)

    def test_recheck_only_failed_files_recovers_changed_and_confirms_unfixed(self):
        good, short, corrupt, nul, big, unsafe = self.seed()
        snapshot = editor.scan(self.root, None, bulk)
        self.assertEqual((snapshot["songs"], snapshot["skippedInvalid"]), (1, 5))
        repaired = self.write("S02.LYR")
        expected_repaired = repaired.read_bytes()
        original_good = good.read_bytes()
        read_paths = []
        original_read = Path.read_bytes
        def checked(path):
            self.assertNotEqual(path, good, "Recheck must never read a successful file")
            self.assertEqual(path.suffix.lower(), ".lyr")
            read_paths.append(path)
            return original_read(path)
        progress = []
        with patch.object(Path, "read_bytes", checked):
            changed = editor.recheck_skipped(
                snapshot, bulk,
                on_progress=lambda msg, done, total: progress.append((done, total)))
        self.assertEqual(len(read_paths), 5)
        self.assertEqual(progress[0], (0, 5))
        self.assertEqual(progress[-1], (5, 5))
        self.assertEqual(changed["songs"], 2)
        self.assertEqual(changed["skippedInvalid"], 4)
        self.assertEqual(changed["recheckSummary"], {
            "total": 5, "lastPass": 5, "confirmed": 4,
            "recovered": 1, "reasonChanged": 0
        })
        self.assertEqual(editor.skipped_page(changed, view="recovered")["total"], 1)
        self.assertEqual(editor.skipped_page(changed, view="rechecked")["total"], 5)
        self.assertEqual(editor.skipped_page(changed, view="skipped")["total"], 4)
        ids = bulk.list_groups(changed, "first", repeats_only=True)["rows"]
        self.assertTrue(any(x["count"] == 2 for x in ids))
        self.assertEqual(good.read_bytes(), original_good)
        self.assertEqual(repaired.read_bytes(), expected_repaired)
        csvrows = list(csv.reader(io.StringIO(editor.skipped_csv(changed)[3:].decode("utf-8"))))
        self.assertEqual(len(csvrows), 6)
        self.assertEqual(sum("อ่านได้หลังตรวจซ้ำ" in row[1] for row in csvrows[1:]), 1)
        self.assertEqual(sum("ยืนยันข้ามหลังตรวจซ้ำ" in row[1] for row in csvrows[1:]), 4)
        # Rechecking the remaining four must preserve the first recovery
        # and original failure reason, without rescanning accepted files.
        again = editor.recheck_skipped(changed, bulk)
        self.assertEqual(again["recheckSummary"], {
            "total": 5, "lastPass": 4, "confirmed": 4,
            "recovered": 1, "reasonChanged": 0
        })
        self.assertEqual(editor.skipped_page(again, view="rechecked")["total"], 5)
        self.assertEqual(editor.skipped_page(again, view="recovered")["total"], 1)
        self.assertEqual(again["songs"], 2)

    def test_reason_changes_are_reflected_and_no_reclassified_files_are_lost(self):
        _, short, _, _, _, _ = self.seed()
        snapshot = editor.scan(self.root, None, bulk)
        # A short LYR now becomes an unparseable CP874 payload.
        short.write_bytes(b"1\r\n2\r\n3\r\n4\r\n" + b"\x81" * 5)
        changed = editor.recheck_skipped(snapshot, bulk)
        self.assertEqual(changed["recheckSummary"]["reasonChanged"], 1)
        confirmed_again = editor.recheck_skipped(changed, bulk)
        self.assertEqual(confirmed_again["recheckSummary"]["reasonChanged"], 1)
        repeated = next(r for r in confirmed_again["recheckRows"]
                        if r["file"].endswith("S02.LYR"))
        self.assertEqual(repeated["originalCategory"], "short_lyrics")
        revised = next(r for r in changed["recheckRows"] if r["file"].endswith("S02.LYR"))
        self.assertEqual(revised["status"], "confirmed")
        self.assertEqual(revised["originalCategory"], "short_lyrics")
        self.assertEqual(revised["category"], "encoding")

    def test_recheck_cancellation_keeps_original_snapshot_unchanged(self):
        self.seed()
        snapshot = editor.scan(self.root, None, bulk)
        signal = threading.Event()
        def cancelled_progress(message, done, total):
            if done == 0:
                signal.set()
        with self.assertRaisesRegex(RuntimeError, "ยกเลิก"):
            editor.recheck_skipped(snapshot, bulk, cancelled=signal,
                                   on_progress=cancelled_progress)
        self.assertEqual(snapshot["skippedInvalid"], 5)
        self.assertNotIn("recheckRows", snapshot)

    def test_only_lyr_files_accessed_in_recheck_even_if_midi_cursor_present(self):
        _, short, _, _, _, _ = self.seed()
        mid = self.root / "Song" / "unused.MID"
        cur = self.root / "Cursor" / "unused.CUR"
        mid.write_bytes(b"secret")
        cur.write_bytes(b"timestamps")
        original_mid, original_cur = mid.read_bytes(), cur.read_bytes()
        snapshot = editor.scan(self.root, None, bulk)
        editor.recheck_skipped(snapshot, bulk)
        self.assertEqual(mid.read_bytes(), original_mid)
        self.assertEqual(cur.read_bytes(), original_cur)


if __name__ == "__main__":
    unittest.main()
