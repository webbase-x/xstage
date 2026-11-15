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

    def test_independent_output_destination(self):
        code = self.song("00005", b"A")
        dest = Path(self.temp.name) / "output"
        result = self.build([code], dest)
        self.assertEqual(result["created"], 1)
        self.assertTrue((dest/"XStageSong"/"MIDI"/"XSK"/"0"/"00005.xsk").exists())
        self.assertFalse((self.root/"MIDI"/"XSK").exists())


if __name__ == "__main__":
    unittest.main()
