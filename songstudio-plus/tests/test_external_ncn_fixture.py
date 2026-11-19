"""Check an upstream open-source NCN triplet, not just generated mocks.

Files come from DontreeCrab (MIT), see fixtures/dontreecrab_ncn/LICENSE.
Fixture has surplus CUR entries intentionally: they must never turn into
extra lyrics, and no measured beginning timestamps should be fabricated.
"""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ncn_reader
import plus_core as plus

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "dontreecrab_ncn"
MEDIA = FIXTURE / "Song" / "1" / "test.mid"
LYR = FIXTURE / "Lyrics" / "1" / "test.lyr"
CUR = FIXTURE / "Cursor" / "1" / "test.cur"
EXPECTED_SHA256 = {
    MEDIA: "99e9b2469d6a268bf570a716618e2fe9fc995e94efa9f476e7b5f463dfc64beb",
    LYR: "4ba6c23581e8a0649e6a42291833e4831ad7cb5c75c8c75260fbd670a9e61625",
    CUR: "e8e239d67cedb0e30184dcb208b6a38469d0e387cc430a2b42103fc97959f481",
}


class PublicNcnFixtureTests(unittest.TestCase):
    def test_real_downloaded_upstream_bytes_are_preserved(self):
        for path, expected in EXPECTED_SHA256.items():
            with self.subTest(file=path.name):
                self.assertTrue(path.is_file(), path)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                                 expected)

    def test_upstream_ncn_triplet_timing_and_surplus_cursor(self):
        companions = ncn_reader.resolve_companions(MEDIA)
        self.assertIsNotNone(companions)
        self.assertEqual(companions["missing"], [])
        self.assertEqual(Path(companions["lyrics"]), LYR)
        self.assertEqual(Path(companions["cursor"]), CUR)

        document = ncn_reader.ncn_document(companions)
        self.assertEqual(document["sourceFormat"], "NCN")
        self.assertEqual([line["text"] for line in document["lines"]],
                         ["hello", "world"])
        self.assertEqual(document["metadata"]["title"], "Test Song")
        self.assertEqual(document["metadata"]["artist"], "DontreeCrab")
        self.assertTrue(document["metadata"]["timingComplete"])
        self.assertEqual(document["metadata"]["cursorValues"], 25)
        self.assertEqual(document["metadata"]["unusedCursorValues"], 13)
        self.assertEqual([len(line["characters"]) for line in document["lines"]],
                         [5, 5])
        self.assertAlmostEqual(document["lines"][0]["characters"][0]["startTime"],
                               0.417, places=3)
        for line in document["lines"]:
            self.assertGreater(line["endTime"], line["characters"][-1]["startTime"])
        validated = plus.valid_lines(document)
        self.assertEqual(len(validated), 2)
        self.assertEqual(sum(len(row[3]) for row in validated), 10)

    def test_upstream_ncn_import_and_xmid_export_leave_sources_untouched(self):
        before = dict((path, path.read_bytes()) for path in EXPECTED_SHA256)
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder) / "workspace"
            plus.init(workspace)
            imported = plus.import_folder(workspace, FIXTURE)
            self.assertEqual(imported["files_seen"], 1)
            self.assertEqual(imported["files_new"], 1)
            self.assertEqual(imported["lyrics_new"], 1)
            self.assertEqual(imported["failures"], 0)
            self.assertEqual(imported["skipped_ncn"], 0)
            songs = plus.songs(workspace)
            self.assertEqual(len(songs), 1)
            self.assertEqual(songs[0]["title"], "Test Song")
            self.assertEqual(songs[0]["artist"], "DontreeCrab")
            output = plus.build_song(workspace, songs[0]["id"])
            self.assertEqual(Path(output["path"]).suffix, ".xmid")
            self.assertEqual(plus.inspect_xfile(output["path"], True)["media_sha256"],
                             EXPECTED_SHA256[MEDIA])
        for path, raw in before.items():
            self.assertEqual(path.read_bytes(), raw, path)


if __name__ == "__main__":
    unittest.main()
