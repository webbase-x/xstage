"""Prevent Windows cp874/default-locale decoding from breaking UTF-8 song manifests."""
import json
import unittest

class WindowsEncoding0943Tests(unittest.TestCase):
    def test_thai_utf8_json_does_not_require_windows_ansi_codepage(self):
        with self.subTest('UTF-8 can encode Thai characters'):
            payload = json.dumps({'song': 'เพลงรักภาษาไทย'}, ensure_ascii=False).encode('utf-8')
            self.assertEqual(json.loads(payload.decode('utf-8'))['song'], 'เพลงรักภาษาไทย')
            with self.assertRaises(UnicodeDecodeError):
                payload.decode('cp874')


if __name__ == '__main__':
    unittest.main()
