"""Lightweight many-file smoke tests: Unicode paths, SHA cache and batch imports.

This is a correctness regression, not a claimed hardware throughput benchmark.
It deliberately leaves valuable user media untouched.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import plus_core as core


class BulkImportTests(unittest.TestCase):
    def test_reimport_many_unique_media_under_thai_path_reuses_hash_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            folder=base/"ไฟล์เพลงต้นฉบับ"
            folder.mkdir()
            workspace=base/"ฐานข้อมูลเพลง"
            for index in range(72):
                # Distinct media bytes while staying independent of codecs
                # and external Windows devices.
                (folder/f"เพลง_{index:05d}.mp3").write_bytes(
                    b"MEDIA"+index.to_bytes(4,"little")+b"audio"*32)
            first=core.import_folder(workspace,folder)
            self.assertEqual(first["files_seen"],72)
            self.assertEqual(first["files_new"],72)
            self.assertEqual(first["failures"],0)
            second=core.import_folder(workspace,folder)
            self.assertEqual(second["files_seen"],72)
            self.assertEqual(second["files_new"],0)
            self.assertEqual(second["media_duplicates"],72)
            self.assertEqual(second["hash_cache_hits"],72)
            self.assertEqual(second["bytes_hashed"],0)
            self.assertEqual(core.stats(workspace)["songs"],72)
            with core.connect(workspace) as db:
                self.assertEqual(db.execute(
                    "SELECT COUNT(*) FROM xstage_media_sources").fetchone()[0],72)


if __name__=="__main__":
    unittest.main()
