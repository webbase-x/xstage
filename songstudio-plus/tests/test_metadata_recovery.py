import sys
import tempfile
import unittest
from pathlib import Path
import shutil
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import plus_core as core
import ncn_reader
import metadata_recovery

class MetadataRecoveryTests(unittest.TestCase):
    def test_utf16_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"song.lyr"
            p.write_bytes("ชื่อเพลง: เพลงทดสอบ\r\nศิลปิน: นักร้อง\r\nC\r\n\r\nทดสอบ".encode("utf-16"))
            self.assertEqual(ncn_reader.lyric_metadata(p)["title"],"เพลงทดสอบ")
            self.assertEqual(ncn_reader.lyric_metadata(p)["artist"],"นักร้อง")
            self.assertTrue(core.identity_missing("00001","00001"))
    def test_repair_existing_export_and_idempotent(self):
        fixture=Path(__file__).parent/"fixtures"/"dontreecrab_ncn"
        with tempfile.TemporaryDirectory() as d:
            workspace=Path(d)/"workspace"
            source=Path(d)/"source"
            shutil.copytree(fixture,source)
            core.import_folder(workspace,source)
            song=core.songs(workspace)[0]
            with core.connect(workspace) as db:
                db.execute("UPDATE xstage_songs SET title=original_code,artist='' WHERE id=?",(song["id"],))
                db.execute("UPDATE xstage_lyric_versions SET title=?,artist='' WHERE song_id=?",(song["original_code"],song["id"]))
            first=core.build_song(workspace,song["id"])
            output=Path(first["path"])
            fixed=metadata_recovery.run(workspace)
            self.assertEqual(fixed["updated"],1)
            self.assertEqual(fixed["rebuilt"],1)
            self.assertEqual(core.read_xfile(output)["title"],"Test Song")
            self.assertEqual(core.read_xfile(output)["artist"],"DontreeCrab")
            self.assertEqual(core.songs(workspace)[0]["export_code"],song["export_code"])
            self.assertEqual(metadata_recovery.run(workspace)["rebuilt"],0)

    def test_utf8_native_cursor_with_verified_byte_groups(self):
        import struct
        fixture=Path(__file__).parent/"fixtures"/"dontreecrab_ncn"
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"source"
            shutil.copytree(fixture,root)
            midi=root/"Song"/"1"/"test.mid"
            lyr=root/"Lyrics"/"1"/"test.lyr"
            cur=root/"Cursor"/"1"/"test.cur"
            lyr.write_text("เพลงทดสอบ\nนักร้อง\nC\n\nกข\n",encoding="utf-8")
            cur.write_bytes(struct.pack("<7H",0,1,1,1,2,2,2))
            doc=ncn_reader.ncn_document(ncn_reader.resolve_companions(midi))
            self.assertEqual(doc["lines"][0]["text"],"กข")
            self.assertTrue(doc["metadata"]["timingComplete"])
            self.assertEqual(doc["metadata"]["cursorEncoding"],"utf-8")
            cur.write_bytes(struct.pack("<7H",0,1,2,3,4,5,6))
            with self.assertRaisesRegex(ValueError,"ambiguous"):
                ncn_reader.ncn_document(ncn_reader.resolve_companions(midi))
