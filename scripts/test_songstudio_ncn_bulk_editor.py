"""Regression tests for direct NCN head/tail replacement."""
import importlib.util
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1] / "songstudio-pc"

def load(name, path):
    spec=importlib.util.spec_from_file_location(name, BASE/path)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

bulk=load("ncn_bulk_base","lyric_text_groups.py")
ncn=load("ncn_bulk_reader","ncn_lyrics.py")
edit=load("ncn_bulk_editor_tests","ncn_bulk_editor.py")

def midi():
    end=b"\x00\xff\x2f\x00"
    return b"MThd"+struct.pack(">IHHH",6,0,1,480)+b"MTrk"+struct.pack(">I",len(end))+end

class NCNEditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/"MIDI"/"NCN"
        for name in ("Song","Lyrics","Cursor"):
            (self.root/name/"0").mkdir(parents=True)
        self.backup=Path(self.tmp.name)/"backup"

    def song(self,code="00001",footer=b""):
        lines=["หัวเพลงเดิม","เนื้อร้องสอง","เนื้อร้องสาม","ท้ายเพลงเดิม"]
        mid=self.root/"Song"/"0"/(code+".MID")
        lyr=self.root/"Lyrics"/"0"/(code+".LYR")
        cur=self.root/"Cursor"/"0"/(code+".CUR")
        mid.write_bytes(midi())
        payload=b"".join(x.encode("cp874")+b"\r\n" for x in lines)
        lyr.write_bytes("ชื่อเพลง\r\nศิลปิน\r\nC\r\n.\r\n".encode("cp874")+payload+footer+b"\x1a")
        values=[]
        cursor=0
        for x in lines:
            data=x.encode("cp874")
            values.append(cursor)
            for b in data:
                cursor+=1
                values.append(cursor)
        cur.write_bytes(struct.pack("<"+"H"*len(values),*values)+b"\xff")
        return mid,lyr,cur

    def test_selected_ncn_or_its_song_or_parent_resolves(self):
        self.assertEqual(edit.locate(self.root),self.root.resolve())
        self.assertEqual(edit.locate(self.root/"Song"),self.root.resolve())
        self.assertEqual(edit.locate(self.root.parent),self.root.resolve())
        self.assertEqual(edit.locate(self.root.parent.parent),self.root.resolve())
        unrelated=Path(self.tmp.name)/"OtherSources"
        unrelated.mkdir()
        self.assertIsNone(edit.locate(unrelated))

    def test_replacement_rebuilds_cur_without_changing_other_times_and_undo(self):
        first=self.song("00001")
        second=self.song("00002")
        originals={path:path.read_bytes() for path in first+second}
        old=edit._parse(first[1].read_bytes(),first[2].read_bytes(),bulk)
        snap=edit.scan(self.root,ncn,bulk)
        self.assertEqual(snap["songs"],2)
        group=bulk.list_groups(snap,"first")["rows"][0]["id"]
        p=bulk.plan(snap,[group],replacement="X-Stage Karaoke Online")
        self.assertEqual(p["changedLines"],2)
        result=edit.apply(self.root,ncn,bulk,snap,[group],"X-Stage Karaoke Online",self.backup,
                          expected_count=p["changedLines"])
        self.assertEqual(result["changedFiles"],4)
        for mid,lyr,cur in (first,second):
            self.assertEqual(mid.read_bytes(),originals[mid])
            self.assertNotEqual(lyr.read_bytes(),originals[lyr])
            self.assertNotEqual(cur.read_bytes(),originals[cur])
            self.assertTrue(cur.read_bytes().endswith(b"\xff"))
            self.assertTrue(lyr.read_bytes().endswith(b"\x1a"))
        current=edit._parse(first[1].read_bytes(),first[2].read_bytes(),bulk)
        self.assertEqual(current["lines"][0],"X-Stage Karaoke Online")
        self.assertEqual([x["times"] for x in old["entries"][1:]],
                         [x["times"] for x in current["entries"][1:]])
        self.assertEqual([x["text"] for x in ncn.ncn_document(ncn.resolve_companions(first[0]))["lines"]][0],
                         "X-Stage Karaoke Online")
        bulk.undo(self.backup,self.root,result["backupId"])
        for path,payload in originals.items():
            self.assertEqual(path.read_bytes(),payload)

    def test_two_positions_and_untimed_footer(self):
        triplet=self.song("00003",footer=b"Nick_Karaoke Professional\r\n")
        snap=edit.scan(self.root,ncn,bulk)
        self.assertEqual(bulk.list_groups(snap,"last",repeats_only=False)["rows"][0]["text"],
                         "ท้ายเพลงเดิม")
        first=bulk.list_groups(snap,"first",repeats_only=False)["rows"][0]["id"]
        last=bulk.list_groups(snap,"last",repeats_only=False)["rows"][0]["id"]
        result=edit.apply(self.root,ncn,bulk,snap,[first,last],"X-Stage Karaoke",
                          self.backup,expected_count=2)
        self.assertEqual(result["changedSongs"],1)
        self.assertIn(b"Nick_Karaoke Professional\r\n",triplet[1].read_bytes())
        self.assertEqual([x["text"] for x in ncn.ncn_document(ncn.resolve_companions(triplet[0]))["lines"]],
                         ["X-Stage Karaoke","เนื้อร้องสอง","เนื้อร้องสาม","X-Stage Karaoke"])

    def test_backward_and_sentinel_on_unselected_line_are_preserved(self):
        mid, lyr, cur = self.song("00231")
        raw = cur.read_bytes()
        even = raw[:-1]
        positions = list(struct.unpack("<"+"H"*(len(even)//2), even))
        parsed = edit._parse(lyr.read_bytes(), raw, bulk)
        second = parsed["entries"][1]
        # Corrupt only the 2nd line's *printable cues*. The renderer already
        # tolerates these legacy anomalies, but the bulk editor must NOT
        # change or repair their timing while editing the first line.
        positions[second["cursor"]+3] = 0
        positions[second["cursor"]+4] = 65535
        cur.write_bytes(struct.pack("<"+"H"*len(positions), *positions)+b"\xff")
        baseline = (mid.read_bytes(), lyr.read_bytes(), cur.read_bytes())
        parsed_before = edit._parse(lyr.read_bytes(), cur.read_bytes(), bulk)
        self.assertTrue(any(row["line"] == second["row"]+1
                            for row in parsed_before["timingWarnings"]))
        snapshot = edit.scan(self.root, ncn, bulk)
        group = bulk.list_groups(snapshot, "first", repeats_only=False)["rows"][0]["id"]
        out = edit.apply(self.root, ncn, bulk, snapshot, [group],
                         "X-Stage Karaoke", self.backup, expected_count=1)
        self.assertGreaterEqual(out["preservedTimingWarnings"], 1)
        parsed_after = edit._parse(lyr.read_bytes(), cur.read_bytes(), bulk)
        for left, right in zip(parsed_before["entries"][1:],
                               parsed_after["entries"][1:]):
            self.assertEqual(left["times"], right["times"])
        self.assertEqual(mid.read_bytes(), baseline[0])
        bulk.undo(self.backup, self.root, out["backupId"])
        self.assertEqual((mid.read_bytes(), lyr.read_bytes(), cur.read_bytes()),
                         baseline)

    def test_untimed_line_marker_does_not_reject_safe_selected_text(self):
        _, lyr, cur = self.song("00232")
        original = cur.read_bytes()
        positions = list(struct.unpack("<"+"H"*((len(original)-1)//2), original[:-1]))
        positions[0] = 65535  # first entry is an unprinted line marker
        cur.write_bytes(struct.pack("<"+"H"*len(positions), *positions)+b"\xff")
        snapshot = edit.scan(self.root, ncn, bulk)
        group = bulk.list_groups(snapshot, "first", repeats_only=False)["rows"][0]["id"]
        out = edit.apply(self.root, ncn, bulk, snapshot, [group],
                         "X-Stage Karaoke", self.backup, expected_count=1)
        new_positions = struct.unpack("<"+"H"*((len(cur.read_bytes())-1)//2),
                                      cur.read_bytes()[:-1])
        self.assertEqual(new_positions[0], 65535)
        self.assertEqual(out["preservedTimingWarnings"], 0)
        self.assertEqual(edit._parse(lyr.read_bytes(), cur.read_bytes(), bulk)["lines"][0],
                         "X-Stage Karaoke")

    def test_selected_line_with_untimed_character_still_blocks_edit(self):
        _, lyr, cur = self.song("00233")
        raw = cur.read_bytes()
        times = list(struct.unpack("<"+"H"*((len(raw)-1)//2), raw[:-1]))
        times[1] = 65535
        cur.write_bytes(struct.pack("<"+"H"*len(times), *times)+b"\xff")
        original = (lyr.read_bytes(), cur.read_bytes())
        snapshot = edit.scan(self.root, ncn, bulk)
        group = bulk.list_groups(snapshot, "first", repeats_only=False)["rows"][0]["id"]
        with self.assertRaisesRegex(ValueError, "ไม่มีข้อมูลจริง.*65535"):
            edit.apply(self.root,ncn,bulk,snapshot,[group],
                       "X-Stage Karaoke",self.backup,expected_count=1)
        self.assertEqual((lyr.read_bytes(),cur.read_bytes()),original)
        self.assertFalse(self.backup.exists())

    def test_selected_line_with_backward_character_cue_uses_existing_player_times(self):
        mid, lyr, cur = self.song("02386")
        raw = cur.read_bytes()
        positions = list(struct.unpack("<"+"H"*((len(raw)-1)//2), raw[:-1]))
        # Simulates the backward cue in the user-reported lyric, which older
        # builds refused before backing up and modifying any content.
        positions[3] = 0
        cur.write_bytes(struct.pack("<"+"H"*len(positions), *positions)+b"\xff")
        initial = (mid.read_bytes(),lyr.read_bytes(),cur.read_bytes())
        before = edit._parse(lyr.read_bytes(),cur.read_bytes(),bulk)
        first = before["entries"][0]
        original_effective, corrections = edit._effective_cues(before["entries"], 0)
        self.assertGreater(corrections, 0)
        self.assertEqual(original_effective, sorted(original_effective))
        snapshot = edit.scan(self.root,ncn,bulk)
        group = bulk.list_groups(snapshot,"first",repeats_only=False)["rows"][0]["id"]
        report = edit.apply(self.root,ncn,bulk,snapshot,[group],
                            "X-Stage Karaoke",self.backup,expected_count=1)
        self.assertGreater(report["projectedCursorCues"],0)
        after = edit._parse(lyr.read_bytes(),cur.read_bytes(),bulk)
        self.assertEqual(after["entries"][0]["times"][1], original_effective[0])
        self.assertEqual(after["entries"][0]["times"][-1], original_effective[-1])
        self.assertEqual(after["entries"][0]["times"][1:],
                         sorted(after["entries"][0]["times"][1:]))
        self.assertEqual([entry["times"] for entry in before["entries"][1:]],
                         [entry["times"] for entry in after["entries"][1:]])
        self.assertEqual(mid.read_bytes(),initial[0])
        bulk.undo(self.backup,self.root,report["backupId"])
        self.assertEqual((mid.read_bytes(),lyr.read_bytes(),cur.read_bytes()),initial)

    def test_reversed_within_selected_line_of_same_cp874_byte_length_leaves_cur_exact(self):
        _,lyr,cur=self.song("00235")
        raw=cur.read_bytes()
        times=list(struct.unpack("<"+"H"*((len(raw)-1)//2),raw[:-1]))
        times[3]=0
        cur.write_bytes(struct.pack("<"+"H"*len(times),*times)+b"\xff")
        unchanged_cur=cur.read_bytes()
        snapshot=edit.scan(self.root,ncn,bulk)
        group=bulk.list_groups(snapshot,"first",repeats_only=False)["rows"][0]["id"]
        original_text="หัวเพลงเดิม"
        same_length="A"*len(original_text.encode("cp874"))
        report=edit.apply(self.root,ncn,bulk,snapshot,[group],same_length,
                          self.backup,expected_count=1)
        self.assertEqual(report["projectedCursorCues"],0)
        self.assertEqual(cur.read_bytes(),unchanged_cur)
        self.assertEqual(edit._parse(lyr.read_bytes(),cur.read_bytes(),bulk)["lines"][0],
                         same_length)

    def test_selected_line_backwards_relative_to_previous_song_line_uses_player_semantics(self):
        _, lyr, cur = self.song("00234")
        raw = cur.read_bytes()
        times = list(struct.unpack("<"+"H"*((len(raw)-1)//2), raw[:-1]))
        parsed = edit._parse(lyr.read_bytes(), raw, bulk)
        last = parsed["entries"][-1]
        # A monotone line whose onset is earlier than the previous lyric.
        start = last["cursor"] + 1
        for j in range(len(last["raw"])):
            times[start+j] = j
        cur.write_bytes(struct.pack("<"+"H"*len(times), *times)+b"\xff")
        snapshot = edit.scan(self.root,ncn,bulk)
        group = bulk.list_groups(snapshot,"last",repeats_only=False)["rows"][0]["id"]
        result=edit.apply(self.root,ncn,bulk,snapshot,[group],"X-Stage",
                          self.backup,expected_count=1)
        self.assertGreater(result["projectedCursorCues"],0)
        after=edit._parse(lyr.read_bytes(),cur.read_bytes(),bulk)
        self.assertEqual(after["entries"][-1]["cueIssue"],None)
        previous=max(position for row in after["entries"][:-1]
                     for position in row["times"][1:] if position!=65535)
        self.assertGreaterEqual(after["entries"][-1]["times"][1],previous)

    def test_stale_files_and_unsupported_cp874_block_changes(self):
        _,lyr,cur=self.song()
        snap=edit.scan(self.root,ncn,bulk)
        group=bulk.list_groups(snap,"first",repeats_only=False)["rows"][0]["id"]
        before=lyr.read_bytes()
        with self.assertRaisesRegex(ValueError,"CP874"):
            edit.apply(self.root,ncn,bulk,snap,[group],"🎤",self.backup,expected_count=1)
        self.assertEqual(lyr.read_bytes(),before)
        # LYR changes are detected against the SHA recorded by the scan.
        lyr.write_bytes(before + b"changed after scan")
        changed_lyr = lyr.read_bytes()
        with self.assertRaisesRegex(ValueError,"LYR เปลี่ยนหลังวิเคราะห์"):
            edit.apply(self.root,ncn,bulk,snap,[group],"X-Stage",self.backup,expected_count=1)
        self.assertEqual(lyr.read_bytes(),changed_lyr)
        self.assertFalse(self.backup.exists())

    def test_incomplete_ncn_is_analyzed_but_cannot_be_replaced_without_cur(self):
        first=self.song("00001")
        _,_,missing=self.song("00002")
        missing.unlink()
        original=[(path,path.read_bytes()) for path in first]
        snap=edit.scan(self.root,ncn,bulk)
        self.assertEqual((snap["songs"],snap["skippedInvalid"]),(2,0))
        group=bulk.list_groups(snap,"first")["rows"][0]["id"]
        with self.assertRaisesRegex(ValueError,"MID|CUR|ไม่ครบ"):
            edit.apply(self.root,ncn,bulk,snap,[group],"X-Stage Karaoke",
                       self.backup,expected_count=2)
        for path,raw in original:
            self.assertEqual(path.read_bytes(),raw)
        self.assertFalse(self.backup.exists())

    def test_scan_only_reads_lyr_and_updates_percentage_without_midi_or_cur(self):
        self.song("00001")
        self.song("00002")
        open_lyr=[]
        progress=[]
        original=Path.read_bytes
        def read_only_lyr(file):
            self.assertEqual(file.suffix.lower(),".lyr",
                             "Analysis must not read MID/CUR")
            open_lyr.append(file)
            return original(file)
        with patch.object(Path,"read_bytes",read_only_lyr), patch.object(
                edit,"_matched_parts",side_effect=AssertionError(
                    "Analysis attempted MID/CUR lookup")):
            snap=edit.scan(self.root,ncn,bulk,
                           on_progress=lambda text,done,total: progress.append((done,total)))
        self.assertEqual(snap["songs"],2)
        self.assertEqual(snap["scanMode"],"lyr-only")
        self.assertEqual(len(open_lyr),2)
        self.assertEqual(progress[0],(0,2))
        self.assertEqual(progress[-1],(2,2))

    def test_standalone_lyrics_folder_is_analyzed_read_only(self):
        _,source,_=self.song("00001")
        standalone=Path(self.tmp.name)/"StandAlone"/"Lyrics"
        standalone.mkdir(parents=True)
        target=standalone/"00001.LYR"
        target.write_bytes(source.read_bytes())
        snap=edit.scan(standalone,ncn,bulk)
        self.assertEqual((snap["songs"],snap["inspected"]),(1,1))
        group=bulk.list_groups(snap,"first",repeats_only=False)["rows"][0]["id"]
        with self.assertRaisesRegex(ValueError,"NCN/Song.*NCN/Cursor"):
            edit.apply(standalone,ncn,bulk,snap,[group],"X-Stage Karaoke",
                       self.backup,expected_count=1)
        self.assertEqual(target.read_bytes(),source.read_bytes())

if __name__=="__main__":
    unittest.main()
