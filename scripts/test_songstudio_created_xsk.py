"""Pure local regressions for the Pro catalog -> authenticated XSK workflow."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1] / "songstudio-pc"


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CreatedXskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "XStageSong"
        self.module = load("created_xsk_export")
        self.package = load("xsk_package")
        self.codes = load("code_registry")
        self.json_manager = load("created_json_manager")
        self.key = bytes(range(32))
        self.records = {}
        self.export = SimpleNamespace(
            safe_media_path=self.safe_media_path,
            existing_records=lambda _root: [],
            lyrics_identity=load("song_export").lyrics_identity,
        )
        self.created = SimpleNamespace(
            _records=lambda _root, _exp: self.records,
            _validate=self.json_manager._validate,
        )

    def safe_media_path(self, root, rel, kind):
        self.assertTrue(rel.startswith(kind + "/"))
        path = Path(root) / rel
        self.assertTrue(path.resolve().is_relative_to(Path(root).resolve()))
        return path

    def song(self, code, suffix):
        midi = self.root / "audio" / "0" / (code + ".mid")
        lyrics = self.root / "lyrics" / "0" / (code + ".json")
        midi.parent.mkdir(parents=True, exist_ok=True)
        lyrics.parent.mkdir(parents=True, exist_ok=True)
        midi.write_bytes(b"MThd" + suffix * 40)
        lyrics.write_text(json.dumps({
            "schemaVersion": 1, "songCode": code,
            "lines": [{"text": "ทดสอบ", "startTime": 1.0, "endTime": 2.0}],
        }, ensure_ascii=False), encoding="utf-8")
        row = {"code": code, "title": "ทดสอบ", "artist": "XStage",
               "audio": {"path": "audio/0/" + midi.name}}
        key = "lyrics/0/" + lyrics.name
        self.records[key] = (lyrics, row)
        return key

    def build(self, keys, dest=None):
        return self.module.export_selected(
            self.root, keys, self.export, self.created, self.package,
            self.codes, self.key, destination_root=dest)

    def test_xsk_uses_product_publisher_without_windows_personal_identity(self):
        selected = self.song("00012", b"P")
        result = self.build([selected])
        self.assertEqual(result["created"], 1)
        file = self.root / "MIDI" / "XSK" / "0" / "00012.xsk"
        document = self.package.open_package(file, self.key)
        self.assertEqual(document["createdBy"], "X-Stage Song Studio")
        self.assertEqual(document["publisher"], "X-Stage Song Studio")
        self.assertEqual(document["artist"], "XStage")
        for forbidden in ("owner", "computer", "userName", "machineName",
                          "hostname", "windowsUser"):
            self.assertNotIn(forbidden, document)

    def test_xsk_uses_real_json_metadata_when_catalog_has_placeholders(self):
        selected = self.song("00021", b"P")
        lyrics, record = self.records[selected]
        record["title"] = "00021"
        record["artist"] = "ไม่ระบุศิลปิน"
        doc = json.loads(lyrics.read_text(encoding="utf-8"))
        doc["metadata"] = {"title": "เพลงจาก NCN", "artist": "ศิลปินจาก NCN"}
        lyrics.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        result = self.build([selected])
        self.assertEqual(result["created"], 1)
        file = self.root / "MIDI" / "XSK" / "0" / "00021.xsk"
        packed = self.package.open_package(file)
        self.assertEqual((packed["title"], packed["artist"]),
                         ("เพลงจาก NCN", "ศิลปินจาก NCN"))

    def test_encrypted_xsk1_kept_while_new_xsk2_gets_unused_code(self):
        original = self.song("00001", b"A")
        old = self.root / "MIDI" / "XSK" / "0" / "00001.xsk"
        old.parent.mkdir(parents=True, exist_ok=True)
        old.write_bytes(b"XSK1" + b"legacy-encrypted-file")
        result = self.build([original])
        self.assertEqual(result["created"], 1)
        self.assertEqual(old.read_bytes(), b"XSK1" + b"legacy-encrypted-file")
        portable = self.root / "MIDI" / "XSK" / "0" / "00002.xsk"
        self.assertTrue(portable.is_file())
        self.assertEqual(portable.read_bytes()[:4], b"XSK2")
        document = self.package.open_package(portable)
        self.assertEqual(document["songCode"], "00002")
        self.assertEqual(document["title"], "ทดสอบ")

    def test_first_export_preserves_code_and_duplicate_midi_is_skipped(self):
        first = self.song("00002", b"A")
        r1 = self.build([first])
        self.assertEqual(r1["created"], 1)
        target = self.root / "MIDI" / "XSK" / "0" / "00002.xsk"
        self.assertTrue(target.is_file())
        before = target.read_bytes()
        r2 = self.build([first])
        self.assertEqual(r2["skipped"], 1)
        self.assertEqual(target.read_bytes(), before)

    def test_code_collision_uses_first_available_gap_without_overwrite(self):
        one = self.song("00001", b"A")
        three = self.song("00003", b"C")
        self.build([one, three])
        # A different MIDI with an already used XSK code must use 00002.
        changed = self.song("00001", b"B")
        result = self.build([changed])
        self.assertEqual(result["created"], 1)
        self.assertTrue((self.root/"MIDI"/"XSK"/"0"/"00002.xsk").is_file())

    def test_malformed_json_skipped_without_modification(self):
        code = self.song("00004", b"A")
        file = self.records[code][0]
        file.write_text("{bad", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "ไม่พบเพลงที่สร้าง XSK สำเร็จ"):
            self.build([code])
        self.assertEqual(file.read_text(encoding="utf-8"), "{bad")

    def test_export_more_than_one_hundred_in_one_job(self):
        keys = []
        for number in range(1, 102):
            code = f"{number:05d}"
            keys.append(self.song(code, number.to_bytes(2, "big")))
        result = self.build(keys)
        self.assertEqual(result["total"], 101)
        self.assertEqual(result["created"], 101)
        self.assertEqual(result["errors"], 0)

    def test_bulk_catalog_selection_filters_midi_and_search(self):
        first = self.song("00101", b"A")
        second = self.song("00102", b"B")
        self.records[second][1]["audio"]["path"] = "audio/0/00102.mp3"
        selected = self.json_manager.list_created_paths(
            self.root, SimpleNamespace(existing_records=lambda _root: [
                {"code": "00101", "title": "Test A", "artist": "XStage",
                 "lyrics": {"path": first}, "audio": {"path": "audio/0/00101.mid"}},
                {"code": "00102", "title": "Test B", "artist": "XStage",
                 "lyrics": {"path": second}, "audio": {"path": "audio/0/00102.mp3"}},
            ], safe_media_path=self.safe_media_path), search="Test")
        self.assertEqual(selected["paths"], [first])

    def test_independent_output_destination(self):
        code = self.song("00005", b"A")
        dest = Path(self.temp.name) / "output"
        result = self.build([code], dest)
        self.assertEqual(result["created"], 1)
        self.assertTrue((dest/"XStageSong"/"MIDI"/"XSK"/"0"/"00005.xsk").exists())
        self.assertFalse((self.root/"MIDI"/"XSK").exists())


if __name__ == "__main__":
    unittest.main()
