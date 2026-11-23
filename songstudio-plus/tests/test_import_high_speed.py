"""Import performance refactor tests: no-copy, stable CUR links and safe indexing."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from import_directory_index import ImportDirectoryIndex
import plus_core as core


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def test_cached_directory_is_scanned_once_for_lyr_cur(self):
        folder = self.base / "NCN"
        folder.mkdir()
        lyr = folder / "A023327.LYR"
        cur = folder / "A023327.CUR"
        lyr.write_bytes(b"lyr")
        cur.write_bytes(b"cur")
        index = ImportDirectoryIndex()
        with patch("import_directory_index.os.scandir", wraps=os.scandir) as scanned:
            self.assertEqual(index.exact(folder, "A023327", ".lyr"), lyr)
            self.assertEqual(index.exact(folder, "A023327", ".cur"), cur)
            self.assertEqual(scanned.call_count, 1)

    def test_new_sidecar_refreshes_directory_index(self):
        folder = self.base / "Lyrics"
        folder.mkdir()
        index = ImportDirectoryIndex()
        self.assertIsNone(index.exact(folder, "song", ".lyr"))
        lyr = folder / "song.lyr"
        lyr.write_bytes(b"new lyrics")
        # Force an observable directory timestamp even on coarse filesystems.
        ts = folder.stat().st_mtime_ns
        os.utime(folder, ns=(ts + 2_000_000_000, ts + 2_000_000_000))
        self.assertEqual(index.exact(folder, "song", ".lyr"), lyr)

    def test_ambiguous_cloud_code_refuses_match(self):
        folder = self.base / "LYR"
        folder.mkdir()
        first = folder / ("song-" + "1" * 16 + ".lyr")
        first.write_bytes(b"lyrics one")
        index = ImportDirectoryIndex()
        self.assertEqual(index.cloud_code(folder, "song", ".lyr"), first)
        second = folder / ("song-" + "2" * 16 + ".lyr")
        second.write_bytes(b"lyrics two")
        ts = folder.stat().st_mtime_ns
        os.utime(folder, ns=(ts + 2_000_000_000, ts + 2_000_000_000))
        self.assertIsNone(index.cloud_code(folder, "song", ".lyr"))

    def test_cloud_companions_match_different_hash_suffixes(self):
        root = self.base / "SONGS" / "MIDI" / "NCN"
        song = root / "SONG" / "A" / ("A023327-" + "0" * 16 + ".mid")
        lyr = root / "LYR" / "A" / ("A023327-" + "1" * 16 + ".lyr")
        cur = root / "CUR" / "A" / ("A023327-" + "2" * 16 + ".cur")
        for path in (song, lyr, cur):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"data")
        found = core.companion_candidates(song, ImportDirectoryIndex())
        self.assertEqual(found[".lyr"], lyr)
        self.assertEqual(found[".cur"], cur)


class SqliteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.workspace = self.base / "workspace"
        self.folder = self.base / "เพลงต้นฉบับ"
        self.folder.mkdir()
        core.init(self.workspace)

    def test_import_stores_original_path_and_never_copies_media(self):
        source = self.folder / "original.mp3"
        contents = b"keep original" * 500
        source.write_bytes(contents)
        result = core.import_folder(self.workspace, self.folder)
        self.assertEqual((result["files_new"], result["failures"]), (1, 0))
        self.assertEqual(source.read_bytes(), contents)
        with core.connect(self.workspace) as db:
            self.assertEqual(db.execute("SELECT stored_path FROM xstage_media").fetchone()[0], "")
            self.assertEqual(db.execute("SELECT source_path FROM xstage_media_sources").fetchone()[0], str(source))
        self.assertFalse((self.workspace / "SOURCE").exists())

    def test_bulk_sqlite_line_cue_mapping_remains_exact(self):
        source = self.folder / "original.mp3"
        source.write_bytes(b"audio")
        core.import_folder(self.workspace, self.folder)
        document = {"metadata": {"timingComplete": True}, "lines": [
            {"text": "abc", "startTime": 0, "endTime": 2, "syllables": [
                {"text": "a", "start": 0, "duration": 1},
                {"text": "bc", "start": 1, "duration": 1}]},
            {"text": "XYZ", "startTime": 2, "endTime": 4, "syllables": [
                {"text": "X", "start": 2, "duration": 1},
                {"text": "YZ", "start": 3, "duration": 1}]}]}
        with core.connect(self.workspace) as db:
            song = db.execute("SELECT * FROM xstage_songs").fetchone()
            media = db.execute("SELECT * FROM xstage_media").fetchone()
            version, created = core.insert_version(db, song, media, document, None)
            self.assertTrue(created)
            rows = db.execute("SELECT id,position FROM xstage_lyric_lines WHERE version_id=? ORDER BY position",
                              (version,)).fetchall()
            self.assertEqual([row["position"] for row in rows], [0, 1])
            for row, expected in zip(rows, [("a", "bc"), ("X", "YZ")]):
                actual = db.execute("SELECT text FROM xstage_lyric_cues WHERE line_id=? ORDER BY position",
                                    (row["id"],)).fetchall()
                self.assertEqual(tuple(x["text"] for x in actual), expected)


if __name__ == "__main__":
    unittest.main()
