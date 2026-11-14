"""Safeguards for selecting StageWeb or an independent LRC lyrics folder."""
import ast
import json
import tempfile
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / "songstudio-pc" / "engine.py"


class SelectedLyricFolderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
        cls.helper = next(node for node in tree.body
                          if isinstance(node, ast.FunctionDef) and node.name == "lyric_source_root")
        cls.engine_text = ENGINE.read_text(encoding="utf-8")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.workspace = self.home / "พื้นที่งาน"
        self.workspace.mkdir()
        self.context = {
            "Path": Path,
            "json": json,
            "PREFS": {"workspace": str(self.workspace), "lyric_source": ""},
        }
        class FakeExport:
            @staticmethod
            def songs_root(workspace):
                return Path(workspace) / "StageWeb"
        self.context["_song_export_module"] = lambda: FakeExport()
        class StubNativeNCN:
            @staticmethod
            def locate(folder):
                return None
        self.context["LYRIC_NCN"] = StubNativeNCN()
        exec(compile(ast.Module(body=[self.helper], type_ignores=[]),
                     str(ENGINE), "exec"), self.context)
        self.resolve = self.context["lyric_source_root"]

    def catalog(self, path):
        path.mkdir(parents=True, exist_ok=True)
        (path / "current.json").write_text(json.dumps({
            "format": "xstage-local-current",
            "schemaVersion": 1,
            "catalogFiles": [],
            "songCount": 0,
        }), encoding="utf-8")
        return path

    def test_default_keeps_primary_workspace(self):
        expected = self.workspace / "StageWeb"
        self.assertEqual(self.resolve(), expected)
        self.assertFalse(expected.exists(), "Resolving default must not create a library")

    def test_choose_stageweb_or_parent_with_thai_path(self):
        parent = self.home / "เพลงสำรอง"
        library = self.catalog(parent / "StageWeb")
        expected = library.resolve()
        self.assertEqual(self.resolve(str(library)), expected)
        self.assertEqual(self.resolve(str(parent)), expected)
        self.assertEqual(self.resolve(str(parent / ".")), expected)

    def test_choose_raw_folder_without_mutating_it(self):
        folder = self.home / "ต้นฉบับ"
        folder.mkdir()
        (folder / "song.mp3").write_bytes(b"data")
        with self.assertRaisesRegex(ValueError, "Lyrics JSON|current.json"):
            self.resolve(str(folder))
        self.assertFalse((folder / "StageWeb").exists())
        self.assertEqual((folder / "song.mp3").read_bytes(), b"data")

    def test_choose_stageweb_lyrics_subfolder(self):
        library = self.catalog(self.home / "SongStudio" / "StageWeb")
        lyrics = library / "lyrics"
        lyrics.mkdir()
        self.assertEqual(self.resolve(str(lyrics)), library.resolve())

    def test_reject_nonexistent_and_file_paths(self):
        with self.assertRaises(ValueError):
            self.resolve(str(self.home / "no-folder"))
        song_file = self.home / "song.mp3"
        song_file.write_bytes(b"data")
        with self.assertRaisesRegex(ValueError, "โฟลเดอร์"):
            self.resolve(str(song_file))

    def test_reject_wrong_or_malformed_catalog(self):
        path = self.home / "not-a-catalog"
        path.mkdir()
        pointer = path / "current.json"
        pointer.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "ไม่ใช่คลัง"):
            self.resolve(str(path))
        pointer.write_text("not-json", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "อ่าน current.json"):
            self.resolve(str(path))
        self.assertEqual(pointer.read_text(encoding="utf-8"), "not-json")

    def test_restore_selected_path_for_scan_apply_undo_and_backup(self):
        code = self.engine_text
        self.assertIn('elif action == "lyric-groups-scan":\n            root = lyric_source_root()', code)
        self.assertIn('elif action == "lyric-groups-undo":\n            root = lyric_source_root()', code)
        self.assertIn('root = lyric_source_root()\n            groups = options.get("groups")', code)
        self.assertIn('LYRIC_TEXT_BACKUPS, lyric_source_root())', code)
        self.assertIn('previous_lyric_source != PREFS["lyric_source"]', code)
        self.assertIn('LYRIC_TEXT.scan(', code)
        self.assertIn('LYRIC_TEXT.apply_many_smart(', code)
        self.assertNotIn('LYRIC_NCN.', code)
        self.assertIn('ไม่แก้ LYR/CUR/NCN ต้นฉบับ', code)


if __name__ == "__main__":
    unittest.main()
