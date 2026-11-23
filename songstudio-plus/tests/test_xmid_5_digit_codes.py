"""Five-digit XMID export code is exactly the file stem and metadata code.

Legacy output and original MID source must not be rewritten during the migration
to new filenames. Existing SQLite integer keys stay stable for all song IDs.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import plus_core as core
from test_plus import midi


class XmidFiveDigitCodeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.workspace=self.base/"workspace"
        self.source=self.base/"source"
        self.source.mkdir()
        core.init(self.workspace)

    def test_code_boundaries_and_five_digit_filename(self):
        for code,expected in [(1,"00001"),(9,"00009"),(100,"00100"),
                              (9999,"09999"),(10000,"10000"),(99999,"99999")]:
            self.assertEqual(core.xmid_song_code(code),expected)
            dest=core.destination_for(self.workspace,{"code":code},".mid")
            self.assertEqual(dest.name,expected+".xmid")
            self.assertEqual(dest.parent.name,expected[0])
        for code in ("a00001","b99999","Z00042"):
            self.assertEqual(core.xmid_song_code(code),code)
        for invalid in (0,-1,100000,None,"bad","a00000","ab0001"):
            with self.assertRaises(ValueError):
                core.xmid_song_code(invalid)

    def test_letter_code_matches_filename_sqlite_and_embedded_metadata(self):
        source=self.source/"a00001.mid"
        source.write_bytes(midi())
        (self.source/"a00001.lrc").write_text(
            "[00:01.00]Hello\n[00:03.00]World\n",encoding="utf-8")
        imported=core.import_folder(self.workspace,self.source)
        self.assertEqual(imported["files_new"],1)
        row=core.songs(self.workspace)[0]
        self.assertEqual(row["export_code"],"a00001")
        output=Path(core.build_song(self.workspace,row["id"])["path"])
        self.assertEqual(output.name,"a00001.xmid")
        self.assertEqual(core.read_xfile(output,verify_media=True)["code"],"a00001")
        self.assertTrue(core.build_song(self.workspace,row["id"])["skipped"])
        with core.connect(self.workspace) as db:
            self.assertEqual(db.execute(
                "SELECT export_code FROM xstage_song_export_codes").fetchone()[0],"a00001")

    def test_duplicate_letter_code_case_insensitive_falls_back(self):
        for folder,stem,data in (("X","a00001",midi()),("Y","A00001",midi()+b"extra")):
            source=self.source/folder/(stem+".mid")
            source.parent.mkdir(parents=True,exist_ok=True)
            source.write_bytes(data)
            (source.parent/(stem+".lrc")).write_text(
                "[00:01.00]Hello\n[00:03.00]World\n",encoding="utf-8")
        imported=core.import_folder(self.workspace,self.source)
        self.assertEqual(imported["files_new"],2)
        records=core.songs(self.workspace)
        self.assertEqual(len({r["export_code"].casefold() for r in records}),2)
        for row in records:
            path=Path(core.build_song(self.workspace,row["id"])["path"])
            self.assertEqual(path.stem,row["export_code"])
            self.assertEqual(core.read_xfile(path)["code"],row["export_code"])

    def test_first_export_name_equals_embedded_code_and_database_code(self):
        source=self.source/"A023327.mid"
        source.write_bytes(midi())
        (self.source/"A023327.lrc").write_text(
            "[00:01.00]Hello\n[00:03.00]World\n",encoding="utf-8")
        original=source.read_bytes()
        summary=core.import_folder(self.workspace,self.source)
        self.assertEqual(summary["files_new"],1)
        row=core.songs(self.workspace)[0]
        self.assertEqual(row["code"],1)
        result=core.build_song(self.workspace,row["id"])
        path=Path(result["path"])
        self.assertEqual(path.name,"00001.xmid")
        self.assertEqual(path.stem,core.xmid_song_code(row["code"]))
        self.assertEqual(core.read_xfile(path,verify_media=True)["code"],path.stem)
        self.assertEqual(source.read_bytes(),original)
        self.assertFalse((self.workspace/"SOURCE").exists())
        previous_time=path.stat().st_mtime_ns
        again=core.build_song(self.workspace,row["id"])
        self.assertTrue(again["skipped"])
        self.assertEqual(again["path"],str(path))
        self.assertEqual(path.stat().st_mtime_ns,previous_time)
        with core.connect(self.workspace) as db:
            exported=db.execute(
                "SELECT output_path FROM xstage_exports WHERE song_id=?",
                (row["id"],)).fetchone()
            self.assertEqual(Path(exported["output_path"]).name,path.name)

    def test_legacy_registry_keeps_verified_file_without_creating_duplicate(self):
        source=self.source/"old.mid"
        source.write_bytes(midi())
        (self.source/"old.lrc").write_text(
            "[00:01.00]Hello\n[00:03.00]World\n",encoding="utf-8")
        core.import_folder(self.workspace,self.source)
        song=core.songs(self.workspace)[0]
        first=core.build_song(self.workspace,song["id"])
        canonical=Path(first["path"])
        legacy=canonical.with_name("00000001.xmid")
        legacy.write_bytes(canonical.read_bytes())
        canonical.unlink()
        with core.connect(self.workspace) as db:
            rel=str(legacy.relative_to(self.workspace))
            db.execute("UPDATE xstage_exports SET output_path=? WHERE song_id=?",
                       (rel,song["id"]))
            db.execute("UPDATE xstage_midi_export_registry SET output_path=? WHERE song_id=?",
                       (rel,song["id"]))
        reused=core.build_song(self.workspace,song["id"])
        self.assertTrue(reused["skipped"])
        self.assertEqual(Path(reused["path"]),legacy)
        self.assertFalse(canonical.exists())
        self.assertEqual(len(list(self.workspace.rglob("*.xmid"))),1)


if __name__=="__main__":
    unittest.main()
