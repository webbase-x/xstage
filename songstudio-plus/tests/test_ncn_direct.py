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
