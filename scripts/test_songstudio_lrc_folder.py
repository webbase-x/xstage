"""Regression checks: edit LRC from any selected folder without StageWeb."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("xstage_lrc_bulk_test",
                                               ROOT / "songstudio-pc/lyric_text_groups.py")
bulk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bulk)


class RawLrcFolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "ต้นทางเพลง"
        self.root.mkdir()
        self.backups = Path(self.temp.name) / "backups"

    def song(self, relative, lines=None, *, encoding="utf-8", bom=b"", newline="\r\n"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = lines or ["หัวเพลงเดิม", "ท่อนแรก", "ท่อนกลาง", "ท้ายเพลงเดิม"]
        body = "[ar:นักร้อง]" + newline
        body += "".join(f"[00:{index+1:02d}.00]{line}{newline}" for index, line in enumerate(lines))
        original = bom + body.encode(encoding)
        path.write_bytes(original)
        return path, original

    def test_no_catalog_required_and_recursive_scan_does_not_touch_audio(self):
        audio = self.root / "ไฟล์เสียง.mid"
        audio.write_bytes(b"MThd original song unchanged")
        one, before = self.song("เพลง1.lrc")
        two, _ = self.song("เพลงไทย/เพลง2.LRC")
        snapshot = bulk.scan_lrc_folder(self.root)
        self.assertEqual(snapshot["mode"], "lrc-folder")
        self.assertEqual(snapshot["songs"], 2)
        self.assertEqual(snapshot["inspected"], 2)
        group = bulk.list_groups(snapshot, "first")["rows"][0]
        self.assertEqual(group["count"], 2)
        self.assertEqual(group["text"], "หัวเพลงเดิม")
        self.assertEqual(one.read_bytes(), before)
        self.assertEqual(audio.read_bytes(), b"MThd original song unchanged")
        self.assertTrue(two.is_file())

    def test_group_replace_preserves_times_and_undo_restores_every_byte(self):
        one, before1 = self.song("ไทย/เพลง1.lrc", bom=b"\xef\xbb\xbf")
        two, before2 = self.song("ไทย/เพลง2.lrc")
        music = self.root / "ไทย/เพลง2.mp3"
        music.write_bytes(b"AUDIO - DO NOT MODIFY")
        snap = bulk.scan_lrc_folder(self.root)
        group_id = bulk.list_groups(snap, "first")["rows"][0]["id"]
        before_lines = snap["groups"][group_id]["count"]
        self.assertEqual(before_lines, 2)
        planned = bulk.plan(snap, [group_id], replacement="X-Stage Karaoke")
        self.assertEqual(planned["changedLines"], 2)
        output = bulk.apply_many_lrc_folder(
            self.root, snap, [group_id], "X-Stage Karaoke", self.backups,
            expected_count=planned["changedLines"])
        self.assertEqual(output["changedSongs"], 2)
        self.assertIn(b"[00:01.00]X-Stage Karaoke", one.read_bytes())
        self.assertIn(b"\r\n[00:02.00]", one.read_bytes())
        self.assertEqual(one.read_bytes()[:3], b"\xef\xbb\xbf")
        self.assertEqual(music.read_bytes(), b"AUDIO - DO NOT MODIFY")
        self.assertEqual(bulk.latest_backup(self.backups, self.root)["id"],
                         output["backupId"])
        bulk.undo(self.backups, self.root, output["backupId"])
        self.assertEqual(one.read_bytes(), before1)
        self.assertEqual(two.read_bytes(), before2)
        self.assertEqual(music.read_bytes(), b"AUDIO - DO NOT MODIFY")

    def test_multiple_positions_in_single_lrc_and_unedited_queue(self):
        one, _ = self.song("a.lrc")
        two, _ = self.song("b.lrc")
        snap = bulk.scan_lrc_folder(self.root)
        a = bulk.list_groups(snap, "first")["rows"][0]["id"]
        b = bulk.list_groups(snap, "last")["rows"][0]["id"]
        plan = bulk.plan(snap, [a, b], replacement="X-Stage Karaoke Online")
        self.assertEqual(plan["changedSongs"], 2)
        self.assertEqual(plan["changedLines"], 4)
        bulk.apply_many_lrc_folder(self.root, snap, [a, b], "X-Stage Karaoke Online",
                                   self.backups, expected_count=4)
        self.assertEqual(one.read_text(encoding="utf-8").count("X-Stage Karaoke Online"), 2)
        self.assertEqual(two.read_text(encoding="utf-8").count("X-Stage Karaoke Online"), 2)
        self.assertFalse(any(g["text"] == "หัวเพลงเดิม" for g in snap["groups"].values()))
        self.assertGreaterEqual(snap["groupCount"], 2)

    def test_stale_lrc_is_rejected_before_write_and_no_backup_generated(self):
        one, _ = self.song("a.lrc")
        two, before2 = self.song("b.lrc")
        snap = bulk.scan_lrc_folder(self.root)
        group_id = bulk.list_groups(snap, "first")["rows"][0]["id"]
        one.write_text(one.read_text(encoding="utf-8") + "[00:09.00]แก้จากโปรแกรมอื่น\n",
                       encoding="utf-8")
        changed_by_user = one.read_bytes()
        with self.assertRaisesRegex(ValueError, "เปลี่ยนจากตอนวิเคราะห์"):
            bulk.apply_many_lrc_folder(self.root, snap, [group_id], "X-Stage Karaoke",
                                       self.backups, expected_count=2)
        self.assertEqual(one.read_bytes(), changed_by_user)
        self.assertEqual(two.read_bytes(), before2)
        self.assertFalse(self.backups.exists())

    def test_search_limits_edits_to_matching_lyrics_and_preserves_other_songs(self):
        one, _ = self.song("a.lrc", ["หัวเพลงเดิม", "ท่อนแรก", "เนื้อหาเฉพาะนี้", "จบ"])
        two, before = self.song("b.lrc", ["หัวเพลงเดิม", "ท่อนแรก", "อื่น", "จบ"])
        snap = bulk.scan_lrc_folder(self.root)
        group_id = bulk.list_groups(snap, "first")["rows"][0]["id"]
        p = bulk.plan(snap, [group_id], search="เฉพาะนี้", replacement="X-Stage Karaoke")
        self.assertEqual(p["changedSongs"], 1)
        bulk.apply_many_lrc_folder(self.root, snap, [group_id], "X-Stage Karaoke",
                                   self.backups, search="เฉพาะนี้", expected_count=1)
        self.assertIn("X-Stage Karaoke", one.read_text(encoding="utf-8"))
        self.assertEqual(two.read_bytes(), before)
        remaining = bulk.list_groups(snap, "first", repeats_only=True)["rows"]
        self.assertTrue(any(g["text"] == "หัวเพลงเดิม" for g in remaining))

    def test_legacy_thai_encoding_is_preserved_and_unencodable_text_is_refused(self):
        path, before = self.song("win874.lrc", encoding="cp874")
        snap = bulk.scan_lrc_folder(self.root)
        group_id = bulk.list_groups(snap, "first", repeats_only=False)["rows"][0]["id"]
        with self.assertRaisesRegex(ValueError, "รหัสอักขระ"):
            bulk.apply_many_lrc_folder(self.root, snap, [group_id], "🚀 X-Stage",
                                       self.backups, expected_count=1)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(self.backups.exists())
        result = bulk.apply_many_lrc_folder(self.root, snap, [group_id], "X-Stage Karaoke",
                                            self.backups, expected_count=1)
        self.assertEqual(result["changedSongs"], 1)
        self.assertIn("X-Stage Karaoke", path.read_bytes().decode("cp874"))

    def test_utf16_and_malformed_multitimestamp_lrc(self):
        path, original = self.song("utf16.lrc", encoding="utf-16-le", bom=b"\xff\xfe")
        malformed, _ = self.song("bad.lrc")
        malformed.write_text("[00:01.00][00:02.00]ซ้ำ\n"
                             "[00:03.00]abc\n[00:04.00]def\n[00:05.00]ghi\n",
                             encoding="utf-8")
        snap = bulk.scan_lrc_folder(self.root)
        self.assertEqual(snap["inspected"], 2)
        self.assertEqual(snap["songs"], 1)
        self.assertEqual(snap["skippedInvalid"], 1)
        group_id = bulk.list_groups(snap, "first", repeats_only=False)["rows"][0]["id"]
        bulk.apply_many_lrc_folder(self.root, snap, [group_id], "X-Stage Karaoke",
                                   self.backups, expected_count=1)
        self.assertTrue(path.read_bytes().startswith(b"\xff\xfe"))
        self.assertIn("X-Stage Karaoke",
                      path.read_bytes()[2:].decode("utf-16-le"))
        self.assertTrue(malformed.read_text(encoding="utf-8").startswith("[00:01.00][00:02.00]"))

    def test_empty_folder_or_audio_only_explains_expected_lrc(self):
        (self.root / "track.mp3").write_bytes(b"audio")
        with self.assertRaisesRegex(ValueError, r"\.lrc"):
            bulk.scan_lrc_folder(self.root)
        bad = self.root / "short.lrc"
        bad.write_text("[00:01.00]A\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "อย่างน้อย 4 บรรทัด"):
            bulk.scan_lrc_folder(self.root)


if __name__ == "__main__":
    unittest.main()
