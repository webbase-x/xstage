"""Regression: independent XStageSong bundles can be imported repeatedly.

No live Google account, no media deletion and no network access. Validates
cross-computer ID/collision rules, XSK2 playback metadata and portable DB.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing

BASE = Path(__file__).resolve().parents[1]


def load(path, tag):
    spec = importlib.util.spec_from_file_location(tag, BASE / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


registry = load("songstudio-pc/song_registry.py", "xstage_test_registry")
export = load("songstudio-pc/song_export.py", "xstage_test_export")
pc = load("songstudio-pc/pc_library_export.py", "xstage_test_pc")
xsk = load("songstudio-pc/xsk_package.py", "xstage_test_xsk")
GROUPS = ["new", "variant", "updated"]


class MultiComputerImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.destination = self.root / "Karaoke"

    def source(self, machine, code="00001", marker=b"A", title="ชื่อเพลงตัวอย่าง"):
        folder = self.root / machine / "XStageSong"
        midi = self.root / machine / "MIDI_INPUT" / (code + ".mid")
        midi.parent.mkdir(parents=True, exist_ok=True)
        midi.write_bytes(b"MThd" + marker * 100)
        document = {"schemaVersion": 1, "format": "XSK",
                    "formatVersion": 2, "songCode": code,
                    "title": title, "artist": "ศิลปินตัวอย่าง",
                    "audioOffsetMs": 0, "audio": {"sha256": xsk._hash_source(midi)},
                    "lines": [{"startTime": 1, "endTime": 3, "text": "ทดลอง"}]}
        target = xsk.destination(folder, code)
        xsk.seal(midi, document, code, title, "ศิลปินตัวอย่าง", target=target)
        verified = xsk.open_package(target)
        registry.register_xsk(folder, target, verified)
        return folder, target

    def test_same_song_from_different_computers_is_detected_without_copy(self):
        one, file_a = self.source("A")
        first = pc.publish(one, str(self.destination), export, groups=GROUPS)
        self.assertEqual(first["songCount"], 1)
        self.assertEqual(first["copied"], 1)
        two, file_b = self.source("B")
        second = pc.publish(two, str(self.destination), export, groups=GROUPS)
        self.assertEqual(second["copied"], 0)
        self.assertEqual(second["songCount"], 1)
        self.assertEqual(second["groups"]["duplicate"], 1)
        self.assertTrue(file_a.is_file())
        self.assertTrue(file_b.is_file())
        self.assertEqual(len(list((self.destination / "XStageSong").rglob("*.xsk"))), 1)

    def test_same_local_song_number_from_different_computers_keeps_both(self):
        first_root, original_a = self.source("A", marker=b"A", title="เพลงหนึ่ง")
        second_root, original_b = self.source("B", marker=b"B", title="เพลงสอง")
        before_b = original_b.read_bytes()
        first = pc.publish(first_root, str(self.destination), export, groups=GROUPS)
        second = pc.publish(second_root, str(self.destination), export, groups=GROUPS)
        self.assertEqual((first["songCount"], second["songCount"]), (1, 2))
        dest = self.destination / "XStageSong"
        files = sorted(dest.rglob("*.xsk"))
        self.assertEqual(len(files), 2)
        self.assertEqual(len({xsk.open_package(item)["audio"]["sha256"] for item in files}), 2)
        self.assertEqual(original_b.read_bytes(), before_b)
        portable = json.loads((dest / "DB" / "songs-portable.json").read_text(encoding="utf-8"))
        self.assertEqual(portable["songCount"], 2)
        self.assertEqual(len({row["webSongId"] for row in portable["songs"]}), 2)
        self.assertEqual(len({row["code"] for row in portable["songs"]}), 2)
        self.assertTrue(all(row.get("sourceRegistry", {}).get("songId")
                            for row in portable["songs"]))
        with closing(sqlite3.connect(dest / "DB" / "songs.sqlite3")) as db:
            self.assertEqual(db.execute("PRAGMA quick_check").fetchone()[0], "ok")
        third = pc.publish(second_root, str(self.destination), export, groups=GROUPS)
        self.assertEqual(third["copied"], 0)
        self.assertEqual(third["songCount"], 2)

    def test_xsk_and_original_midi_lyric_pair_are_related_variants(self):
        source, xsk_file = self.source("A", marker=b"P")
        embedded = xsk.open_package(xsk_file)
        midi = self.root / "B" / "XStageSong" / "MIDI" / "MID" / "SONG" / "0" / "00001.mid"
        midi.parent.mkdir(parents=True, exist_ok=True)
        midi.write_bytes(b"MThd" + b"P" * 100)
        lyrics = self.root / "B" / "XStageSong" / "MIDI" / "MID" / "LYRICS" / "0" / "00001.json"
        lyrics.parent.mkdir(parents=True, exist_ok=True)
        lyrics.write_text(json.dumps({"schemaVersion": 1,
                                      "lines": embedded["lines"],
                                      "audioOffsetMs": embedded["audioOffsetMs"]},
                                     ensure_ascii=False), encoding="utf-8")
        record = {"webSongId": "midi-b-00001", "code": "00001",
                  "title": "ชื่อเพลงตัวอย่าง", "artist": "ศิลปินตัวอย่าง",
                  "bucket": "0", "audio": {"path": "MIDI/MID/SONG/0/00001.mid"},
                  "lyrics": {"path": "MIDI/MID/LYRICS/0/00001.json"},
                  "sourceFormat": "MIDI",
                  "sourceIdentity": {"sha256": embedded["audio"]["sha256"]}}
        source_b = self.root / "B" / "XStageSong"
        export.publish_batch(source_b, [record])
        first = pc.publish(source, str(self.destination), export, groups=GROUPS)
        self.assertEqual(first["songCount"], 1)
        plan = pc.inspect(source_b, str(self.destination), export, groups=GROUPS)
        self.assertEqual(plan["groups"]["variant"], 1)
        second = pc.publish(source_b, str(self.destination), export, groups=GROUPS)
        self.assertEqual(second["songCount"], 2)
        self.assertEqual(len(list((self.destination / "XStageSong").rglob("*.xsk"))), 1)
        self.assertEqual(len(list((self.destination / "XStageSong").rglob("*.mid"))), 1)

    def test_rejects_unrelated_song_with_same_number_without_source_mutation(self):
        source, _ = self.source("A")
        row = registry.source_rows(source, export)[0]
        old_id = row["sourceRegistry"]["songId"]
        alt, _ = self.source("B", marker=b"C", title="อีกเพลง")
        new_id = registry.source_rows(alt, export)[0]["sourceRegistry"]["songId"]
        self.assertNotEqual(old_id, new_id)
        projected = registry.assign_target_codes(registry.source_rows(alt, export), [row])
        self.assertNotEqual(projected[0]["code"], row["code"])
        self.assertEqual(registry.source_rows(alt, export)[0]["code"], row["code"])


if __name__ == "__main__":
    unittest.main()
