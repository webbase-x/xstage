"""Regression tests for direct NCN head/tail replacement."""
import importlib.util
import struct
import tempfile
import unittest
from pathlib import Path

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
        self.assertIsNone(edit.locate(Path(self.tmp.name)))

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

    def test_stale_files_and_unsupported_cp874_block_changes(self):
        _,lyr,cur=self.song()
        snap=edit.scan(self.root,ncn,bulk)
        group=bulk.list_groups(snap,"first",repeats_only=False)["rows"][0]["id"]
        before=lyr.read_bytes()
        with self.assertRaisesRegex(ValueError,"CP874"):
            edit.apply(self.root,ncn,bulk,snap,[group],"🎤",self.backup,expected_count=1)
        self.assertEqual(lyr.read_bytes(),before)
        cur.write_bytes(cur.read_bytes()+b"\x00")
        changed=cur.read_bytes()
        with self.assertRaisesRegex(ValueError,"เปลี่ยนหลังสแกน"):
            edit.apply(self.root,ncn,bulk,snap,[group],"X-Stage",self.backup,expected_count=1)
        self.assertEqual(cur.read_bytes(),changed)
        self.assertFalse(self.backup.exists())

    def test_incomplete_ncn_is_skipped(self):
        self.song("00001")
        _,_,missing=self.song("00002")
        missing.unlink()
        snap=edit.scan(self.root,ncn,bulk)
        self.assertEqual((snap["songs"],snap["skippedInvalid"]),(1,1))

if __name__=="__main__":
    unittest.main()
