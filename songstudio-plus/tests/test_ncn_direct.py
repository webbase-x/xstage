import tempfile
import unittest
from pathlib import Path
import struct
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ncn_direct as direct
import plus_core as core

def fixture(root,header,body="ทดสอบ"):
    root.mkdir(parents=True,exist_ok=True)
    midi=root/"00001.mid"
    track=b"\x00\x90\x3c\x40\x83\x60\x80\x3c\x00\x00\xff\x2f\x00"
    midi.write_bytes(b"MThd"+struct.pack(">IHHH",6,0,1,480)+b"MTrk"+struct.pack(">I",len(track))+track)
    midi.with_suffix(".lyr").write_bytes(("\r\n".join(header+[body])+"\r\n").encode("cp874"))
    midi.with_suffix(".cur").write_bytes(struct.pack("<"+"H"*(len(body)+1),*range(len(body)+1)))
    return midi

class DirectTests(unittest.TestCase):
    def test_classic_and_reordered_labels(self):
        for header in (["ชื่อจริง","ศิลปินจริง","C",""],["Artist: ศิลปินจริง","Key: C","Title: ชื่อจริง"]):
            with self.subTest(header=header),tempfile.TemporaryDirectory() as d:
                root=Path(d)/"ncn";out=Path(d)/"xmid"
                midi=fixture(root,header)
                before={p.name:p.read_bytes() for p in root.iterdir()}
                result=direct.convert_folder(str(root),str(out))
                self.assertEqual(result["converted"],1,result)
                self.assertEqual(direct.convert_folder(str(root),str(out))["skipped"],1)
                self.assertFalse(list(Path(d).rglob("*.sqlite*")))
                self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir()})
                core.read_xfile(out/"00001.xmid",verify_media=True)
    def test_ambiguous_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"ncn";out=Path(d)/"out"
            fixture(root,["ศิลปินจริง","ชื่อจริง","unknown"])
            self.assertEqual(direct.convert_folder(str(root),str(out))["failed"],1)
            self.assertFalse(list(out.glob("*.xmid")))


class DirectHardeningTests(unittest.TestCase):
    def test_bom_and_thai_labels(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"in";out=Path(d)/"out"
            midi=fixture(root,["ศิลปิน: คนร้อง","คีย์: C","ชื่อเพลง: ชื่อจริง"])
            lyr=midi.with_suffix(".lyr")
            lyr.write_bytes(lyr.read_bytes().decode("cp874").encode("utf-8-sig"))
            self.assertEqual(direct.convert_folder(str(root),str(out))["converted"],1)

    def test_short_backward_or_sentinel_cur(self):
        for positions in ([0,1],[0,2,1,3,4,5],[0,1,2,65535,4,5],[0,1,2,3,4,65534]):
            with self.subTest(positions=positions),tempfile.TemporaryDirectory() as d:
                root=Path(d)/"in";out=Path(d)/"out"
                midi=fixture(root,["ชื่อจริง","ศิลปินจริง","C",""])
                midi.with_suffix(".cur").write_bytes(struct.pack("<"+"H"*len(positions),*positions))
                self.assertEqual(direct.convert_folder(str(root),str(out))["failed"],1)
                self.assertFalse(list(out.glob("*.xmid")))

    def test_code_reservation_stable_cancel_resume_and_add(self):
        import threading
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"in";out=Path(d)/"out"
            midi=fixture(root,["ชื่อจริง","ศิลปินจริง","C",""])
            for p in list(root.iterdir()):
                p.rename(p.with_stem("legacy-z"))
            cancel=threading.Event()
            def notify(stats,message):
                if stats.get("done")==1:
                    cancel.set()
            self.assertEqual(direct.convert_folder(str(root),str(out),notify,cancel)["converted"],1)
            before=(out/"00001.xmid").read_bytes()
            midi=fixture(root,["เพลงใหม่","ผู้ร้องใหม่","C",""])
            for p in root.glob("00001.*"):
                p.rename(p.with_stem("legacy-a"))
            result=direct.convert_folder(str(root),str(out))
            self.assertEqual((result["converted"],result["skipped"]),(1,1),result)
            self.assertEqual((out/"00001.xmid").read_bytes(),before)
            self.assertTrue((out/"00002.xmid").exists())

    def test_component_change_rejected_before_publish(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"in";out=Path(d)/"out"
            midi=fixture(root,["ชื่อจริง","ศิลปินจริง","C",""])
            original=direct.reader.ncn_document
            def change(*args,**kwargs):
                result=original(*args,**kwargs)
                midi.with_suffix(".lyr").write_bytes(b"changed")
                return result
            with patch.object(direct.reader,"ncn_document",side_effect=change):
                self.assertEqual(direct.convert_folder(str(root),str(out))["failed"],1)
            self.assertFalse(list(out.glob("*.xmid")))

    def test_split_tree_case_insensitive(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"NCN";out=Path(d)/"out"
            midi=fixture(root/"SoNg"/"A",["ชื่อจริง","ศิลปินจริง","C",""])
            for name,ext in (("LYRICS",".lyr"),("CuRsOr",".cur")):
                folder=root/name/"A";folder.mkdir(parents=True)
                midi.with_suffix(ext).rename(folder/("00001"+ext.upper()))
            self.assertEqual(direct.convert_folder(str(root),str(out))["converted"],1)

    def test_plan_100000_virtual_paths_and_stable_resume(self):
        # Allocation/ledger benchmark, not 100k actual file conversions.
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"source";out=Path(d)/"out";out.mkdir()
            mids=[root/("legacy-%06d.mid"%n) for n in range(100000)]
            first=direct.plan_codes(root,out,mids)
            self.assertEqual(len(set(first.values())),100000)
            self.assertIn("a00001",first.values())
            second=direct.plan_codes(root,out,[root/"earlier.mid"]+mids)
            self.assertEqual({m:second[m] for m in mids},first)

    def test_non_overwrite_and_nested_path(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"in";out=Path(d)/"out";out.mkdir()
            fixture(root,["ชื่อจริง","ศิลปินจริง","C",""])
            existing=out/"00001.xmid";existing.write_bytes(b"user content")
            self.assertEqual(direct.convert_folder(str(root),str(out))["failed"],1)
            self.assertEqual(existing.read_bytes(),b"user content")
            with self.assertRaises(ValueError):
                direct.convert_folder(str(root),str(root/"out"))
