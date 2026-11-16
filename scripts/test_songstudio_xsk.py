"""XSK2 portable no-encryption regression; XSK1 legacy remains readable."""
import hashlib
import importlib.util
import json
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "songstudio-pc"
spec = importlib.util.spec_from_file_location("xsk_package", ROOT / "xsk_package.py")
xsk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xsk)


class XskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "00001.mid"
        self.source.write_bytes(
            b"MThd" + (6).to_bytes(4, "big") + b"\x00\x00\x00\x01\x00\x60"
            + b"MTrk" + (4).to_bytes(4, "big") + b"\x00\xff\x2f\x00"
            + b"\x00" * 20
        )
        self.doc = {"schemaVersion": 1, "songCode": "00001",
                    "audioOffsetMs": 0,
                    "lines": [{"startTime": 2.0, "endTime": 3.0, "text": "ทดสอบ"}],
                    "rawLrc": "[00:02.00]ทดสอบ"}

    def test_portable_xsk2_roundtrip_without_key(self):
        target = xsk.destination(self.root / "XStageSong", "00001")
        self.assertEqual(target.relative_to(self.root).as_posix(),
                         "XStageSong/MIDI/XSK/0/00001.xsk")
        blob = xsk.seal(self.source, self.doc, "00001", "ทำได้เพียง",
                        "25 Hours", target=target)
        self.assertTrue(blob.startswith(b"XSK2PK"))
        self.assertFalse(blob.startswith(b"XSK1"))
        self.assertEqual(blob, target.read_bytes())
        with zipfile.ZipFile(io.BytesIO(blob[4:])) as archive:
            self.assertEqual(set(archive.namelist()), {"00001.mid", "00001.json"})
        result = xsk.open_package(target)
        self.assertEqual(result["formatVersion"], 2)
        self.assertEqual((result["title"], result["artist"]), ("ทำได้เพียง", "25 Hours"))
        self.assertEqual(result["publisher"], "X-Stage Song Studio")
        self.assertEqual(result["lines"], self.doc["lines"])
        self.assertEqual(result["audio"]["sha256"],
                         hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertFalse((self.root / "XStageSong" / "Projects").exists())
        with self.assertRaises(FileExistsError):
            xsk.seal(self.source, self.doc, "00001", "ทำได้เพียง",
                     "25 Hours", target=target)

    def test_xsk2_requires_no_key_even_if_wrong_legacy_key_passed(self):
        blob = xsk.seal(self.source, self.doc, "00001", "ทำได้เพียง", "25 Hours")
        self.assertEqual(xsk.open_package(blob, b"broken")["title"], "ทำได้เพียง")

    def test_size_boundary_and_midi_integrity(self):
        blob = xsk.seal(self.source, self.doc, "00001", "ทำได้เพียง", "25 Hours")
        with patch.object(xsk, "MAX_ENCRYPTED", len(blob) - 1):
            with self.assertRaisesRegex(ValueError, "ใหญ่"):
                xsk.open_package(blob)
            target = self.root / "huge.xsk"
            target.write_bytes(blob)
            with self.assertRaisesRegex(ValueError, "ใหญ่"):
                xsk.open_package(target)
        with zipfile.ZipFile(io.BytesIO(blob[4:])) as archive:
            meta = json.loads(archive.read("00001.json"))
        meta["audio"]["sha256"] = "0" * 64
        edited = io.BytesIO()
        with zipfile.ZipFile(edited, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("00001.mid", self.source.read_bytes())
            z.writestr("00001.json", json.dumps(meta, ensure_ascii=False))
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            xsk.open_package(b"XSK2" + edited.getvalue())

    def test_existing_file_is_not_overwritten(self):
        target = xsk.destination(self.root / "XStageSong", "00001")
        xsk.seal(self.source, self.doc, "00001", "ทำได้เพียง", "25 Hours", target=target)
        old = target.read_bytes()
        with self.assertRaises(FileExistsError):
            xsk.seal(self.source, self.doc, "00001", "ทำได้เพียง", "25 Hours", target=target)
        self.assertEqual(target.read_bytes(), old)

    def test_bad_timing_and_unsafe_code_fail_closed(self):
        with self.assertRaises(ValueError):
            xsk.destination(self.root, "../hacked")
        self.doc["lines"].append({"startTime": 1, "text": "ผิด"})
        with self.assertRaises(ValueError):
            xsk.seal(self.source, self.doc, "00001", "เพลง", "ศิลปิน")

    def test_xsk1_requires_old_key_and_never_rewrites(self):
        with self.assertRaisesRegex(ValueError, "กุญแจ"):
            xsk.open_package(b"XSK1" + b"\x00" * 64)


if __name__ == "__main__":
    unittest.main()
