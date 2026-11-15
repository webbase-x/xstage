"""Prevent Windows cp874/default-locale decoding from breaking UTF-8 song manifests."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

class WindowsEncoding0943Tests(unittest.TestCase):
    def test_visible_ncn_drive_manifest_survives_cp874_legacy_codepage(self):
        # Simulate the Windows Thai ANSI codepage for any JSON Path.read_text
        # caller which omits the encoding, even when tests run on Linux.
        from test_v0941_ncn_bundle import NCN0941Tests
        original = Path.read_text

        def windows_read_text(path, *args, **kwargs):
            if not args and kwargs.get('encoding') is None and path.suffix == '.json':
                kwargs['encoding'] = 'cp874'
            return original(path, *args, **kwargs)

        with patch.object(Path, 'read_text', windows_read_text):
            result = unittest.TestResult()
            NCN0941Tests('test_drive_includes_only_visible_complete_ncn_triple').run(result)
        errors = [detail for _, detail in result.errors + result.failures]
        self.assertFalse(errors, '\n'.join(errors))
        self.assertEqual(result.testsRun, 1)
        self.assertTrue(result.wasSuccessful())

    def test_thai_utf8_json_does_not_require_windows_ansi_codepage(self):
        with self.subTest('UTF-8 can encode Thai characters'):
            payload = json.dumps({'song': 'เพลงรักภาษาไทย'}, ensure_ascii=False).encode('utf-8')
            self.assertEqual(json.loads(payload.decode('utf-8'))['song'], 'เพลงรักภาษาไทย')
            with self.assertRaises(UnicodeDecodeError):
                payload.decode('cp874')


if __name__ == '__main__':
    unittest.main()
