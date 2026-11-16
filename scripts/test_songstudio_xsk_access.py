"""Portable authorized XSK access: encrypted, password-verified, no personal data."""
from __future__ import annotations
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1] / "songstudio-pc"
spec=importlib.util.spec_from_file_location("xsk_access",ROOT/"xsk_access.py")
access=importlib.util.module_from_spec(spec)
spec.loader.exec_module(access)


class AccessFileTests(unittest.TestCase):
    def test_password_wrapped_key_roundtrip_no_username_or_machine(self):
        with tempfile.TemporaryDirectory() as temp:
            dest=Path(temp)/"XStageSong-access.xskkey"
            key=bytes(range(32))
            access.export_access(key,"personal password 1234",dest)
            document=json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(access.unwrap_access(document,"personal password 1234"),key)
            self.assertEqual(document["publisher"],"X-Stage Song Studio")
            self.assertNotIn(key.hex(),dest.read_text(encoding="utf-8"))
            for name in ("hostname","computer","machine","user","creator","windowsUser"):
                self.assertNotIn(name,document)
            with self.assertRaises(Exception):
                access.unwrap_access(document,"wrong password 123")
            with self.assertRaises(ValueError):
                access.export_access(key,"personal password 1234",dest)
            self.assertEqual(access.unwrap_access(document,"personal password 1234"),key)

    def test_no_short_password_or_raw_key(self):
        with tempfile.TemporaryDirectory() as temp:
            dest=Path(temp)/"bad.xskkey"
            with self.assertRaisesRegex(ValueError,"12"):
                access.export_access(bytes(range(32)),"short",dest)
            self.assertFalse(dest.exists())
            with self.assertRaises(ValueError):
                access.export_access(b"bad","personal password 1234",dest)
            self.assertFalse(dest.exists())


if __name__=="__main__":
    unittest.main()
