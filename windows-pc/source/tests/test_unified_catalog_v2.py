"""Offline Windows unified V2 bridge tests: no Google or network access."""
import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from karaoke.library import SongLibrary
from karaoke.catalog_v2_bridge import export_catalog,preview_import,import_catalog,row_to_catalog_song
from karaoke.unified_catalog_v2 import CatalogValidationError, validate_catalog


class UnifiedWindowsV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.library=SongLibrary(self.base/"db"/"songs.sqlite3")
        self.media=self.base/"Songs"
        self.media.mkdir()
        self.mp3=self.media/"A0001.mp3"
        self.mp3.write_bytes(b"ID3"+b"A"*100)
        self.library.upsert_catalog([{
            "path":str(self.mp3),"code":"A0001","title":"เพลงไทย",
            "artist":"นักร้อง","kind":"MP3","format":"MP3",
            "playable":1,"first_lyric":"","rhythm":"","key_signature":"",
            "bpm":"","source_catalog":"local"
        }])
        self.output=self.base/"my-catalog-v2.json"

    def test_export_local_sqlite_no_mutation(self):
        with closing(sqlite3.connect(self.library.path)) as db:
            before=db.execute("SELECT code,title,artist,favorite FROM songs").fetchall()
        result=export_catalog(self.library.path,self.output)
        self.assertEqual(result["exported"],1)
        doc=json.loads(self.output.read_text(encoding="utf8"))
        self.assertEqual(doc["schemaVersion"],2)
        self.assertEqual(doc["catalogScope"],"local-offline")
        validate_catalog(doc,cloud=False)
        song=doc["songs"][0]
        self.assertEqual(song["code"],"A0001")
        self.assertEqual(song["media"]["mp3"]["localPath"].casefold(),str(self.mp3.resolve()).casefold())
        self.assertNotIn("fileId",song["media"]["mp3"])
        with sqlite3.connect(self.library.path) as db:
            after=db.execute("SELECT code,title,artist,favorite FROM songs").fetchall()
        self.assertEqual(before,after)

    def test_import_requires_preview_confirmation_and_sqlite_backup(self):
        export_catalog(self.library.path,self.output)
        other=SongLibrary(self.base/"new-db"/"songs.sqlite3")
        preview=import_catalog(other.path,self.output)
        self.assertEqual(preview["ready"],1)
        self.assertTrue(preview["dryRun"])
        with other.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM songs").fetchone()[0],0)
        result=import_catalog(other.path,self.output,confirmation="IMPORT_UNIFIED_V2")
        self.assertFalse(result["dryRun"])
        self.assertEqual(result["imported"],1)
        self.assertTrue(Path(result["backup"]).is_file())
        with other.connect() as db:
            self.assertEqual(db.execute("SELECT title FROM songs").fetchone()[0],"เพลงไทย")

    def test_rejects_cloud_only_catalog_on_pc(self):
        export_catalog(self.library.path,self.output)
        doc=json.loads(self.output.read_text(encoding="utf8"))
        song=doc["songs"][0]
        song["media"]["mp3"]={"fileId":"opaque_drive_file"}
        self.output.write_text(json.dumps(doc,ensure_ascii=False),encoding="utf8")
        with self.assertRaises(CatalogValidationError):
            preview_import(self.library.path,self.output)

    def test_corrupt_source_does_not_overwrite_completed_export(self):
        export_catalog(self.library.path,self.output)
        original=self.output.read_bytes()
        (self.media/"A0001.mp3").unlink()
        result=export_catalog(self.library.path,self.output)
        self.assertEqual(result["skipped"],1)
        # The catalog is valid but explicitly reports no usable original file.
        self.assertEqual(json.loads(self.output.read_text(encoding="utf8"))["songs"],[])
        self.assertNotEqual(self.output.read_bytes(),original)

    def test_ncn_requires_lyr_cur_verified(self):
        root=self.base/"MIDI"/"NCN"
        midi=root/"Songs"/"0"/"B0001.mid"
        midi.parent.mkdir(parents=True)
        midi.write_bytes(b"MThd"+b"Z"*22)
        row={"id":17,"path":str(midi),"code":"B0001","title":"NCN",
             "artist":"","kind":"NCN","format":"NCN"}
        with self.assertRaises(CatalogValidationError):
            row_to_catalog_song(row)
        lyr=root/"Lyrics"/"0"/"B0001.lyr"
        cur=root/"Cursor"/"0"/"B0001.cur"
        lyr.parent.mkdir(parents=True);cur.parent.mkdir(parents=True)
        lyr.write_bytes(b"test");cur.write_bytes(b"test")
        song=row_to_catalog_song(row)
        self.assertEqual(song["media"]["midi"]["type"],"ncn")
        self.assertTrue(song["media"]["midi"]["lyr"]["localPath"].endswith(".lyr"))
        self.assertTrue(song["media"]["midi"]["cur"]["localPath"].endswith(".cur"))

    def test_incomplete_input_never_changes_current_db(self):
        export_catalog(self.library.path,self.output)
        doc=json.loads(self.output.read_text(encoding="utf8"))
        doc["songs"][0]["media"]["mp3"]["localPath"]="/nonexistent/file.mp3"
        self.output.write_text(json.dumps(doc),encoding="utf8")
        before=list(self.base.rglob("*-before-unified-v2-*.sqlite3"))
        with self.assertRaises(CatalogValidationError):
            import_catalog(self.library.path,self.output,confirmation="IMPORT_UNIFIED_V2")
        self.assertEqual(list(self.base.rglob("*-before-unified-v2-*.sqlite3")),before)
        with self.library.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM songs").fetchone()[0],1)

if __name__=="__main__":
    unittest.main()
