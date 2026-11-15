"""Regression tests for encrypted X-Stage Karaoke packages."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "songstudio-pc"
spec = importlib.util.spec_from_file_location("xsk_package", ROOT / "xsk_package.py")
xsk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xsk)


class XskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
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
        self.key = bytes(range(32))

    def tearDown(self):
        self.temp.cleanup()

    def test_encrypted_package_round_trip_and_destination(self):
        target = xsk.destination(self.root / "XStageSong", "00001")
        self.assertEqual(target.relative_to(self.root).as_posix(),
                         "XStageSong/MIDI/XSK/0/00001.xsk")
        payload = xsk.seal(self.source, self.doc, "00001", "ชื่อเพลง", "ศิลปิน",
                           self.key, target)
        self.assertTrue(payload.startswith(b"XSK1"))
        self.assertNotIn(b"ทดสอบ", payload)
        self.assertNotIn(b"MThd", payload)
        result = xsk.open_package(target, self.key)
        self.assertEqual(result["title"], "ชื่อเพลง")
        self.assertEqual(result["lines"], self.doc["lines"])
        self.assertEqual(result["audio"]["sha256"],
                         hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertFalse((self.root / "XStageSong" / "Projects").exists())
        with self.assertRaises(FileExistsError):
            xsk.seal(self.source, self.doc, "00001", "ชื่อเพลง", "ศิลปิน",
                     self.key, target)

    def test_reject_tampering_and_invalid_key(self):
        raw = xsk.seal(self.source, self.doc, "00001", "เพลง", "ศิลปิน", self.key)
        with self.assertRaises(Exception):
            xsk.open_package(raw, b"1" * 32)
        broken = bytearray(raw); broken[-1] ^= 1
        with self.assertRaises(Exception):
            xsk.open_package(broken, self.key)

    def test_reject_backward_timing_and_traversal(self):
        with self.assertRaises(ValueError):
            xsk.destination(self.root, "../hacked")
        self.doc["lines"].append({"startTime": 1, "text": "ผิด"})
        with self.assertRaises(ValueError):
            xsk.seal(self.source, self.doc, "00001", "เพลง", "", self.key)


if __name__ == "__main__":
    unittest.main()
