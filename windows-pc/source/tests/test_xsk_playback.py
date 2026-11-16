"""XSK1 regression: authenticated roundtrip and legacy MIDI isolation."""
import hashlib
import io
import json
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from karaoke.xsk_reader import read_xsk

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    AESGCM = None

KEY = bytes(range(32))
MIDI = (b'MThd' + struct.pack('>IHHH', 6, 0, 1, 480) +
        b'MTrk' + struct.pack('>I', 13) +
        bytes.fromhex('00 90 3c 50 81 70 80 3c 00 00 ff 2f 00'))


@unittest.skipUnless(AESGCM is not None, 'cryptography required')
class XskPlaybackTests(unittest.TestCase):
    def package(self, root):
        doc = {
            'format': 'XSK', 'formatVersion': 1, 'songCode': '00001',
            'title': 'เพลงทดสอบ', 'artist': 'X-Stage',
            'audio': {'file': '00001.mid', 'type': 'MID',
                      'size': len(MIDI), 'sha256': hashlib.sha256(MIDI).hexdigest()},
            'lines': [{'startTime': 0.0, 'text': 'สวัสดี'}]}
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('00001.mid', MIDI)
            z.writestr('00001.json', json.dumps(doc, ensure_ascii=False))
        nonce = bytes(range(12))
        path = root / '00001.xsk'
        path.write_bytes(b'XSK1' + nonce + AESGCM(KEY).encrypt(nonce, out.getvalue(), b'XSK1'))
        return path

    def test_authenticated_container_and_legacy_loader(self):
        from karaoke.smf import load_midi, parse_midi
        with tempfile.TemporaryDirectory() as dirname:
            path = self.package(Path(dirname))
            raw, doc = read_xsk(path, key=KEY)
            self.assertEqual(raw, MIDI)
            self.assertEqual(doc['title'], 'เพลงทดสอบ')
            with patch('karaoke.xsk_reader.existing_key', return_value=KEY):
                song = load_midi(path)
            self.assertEqual(song.title, 'เพลงทดสอบ')
            self.assertEqual(song.lyrics.lines[0].text, 'สวัสดี')
            legacy = parse_midi(MIDI, legacy=True)
            self.assertEqual(len(legacy.events), len(song.events))

    def test_tamper_and_wrong_key_fail_closed(self):
        with tempfile.TemporaryDirectory() as dirname:
            path = self.package(Path(dirname))
            with self.assertRaises(Exception):
                read_xsk(path, key=bytes([1]) * 32)
            data = bytearray(path.read_bytes())
            data[-1] ^= 1
            path.write_bytes(data)
            with self.assertRaises(Exception):
                read_xsk(path, key=KEY)

    def test_no_key_never_creates_key(self):
        with tempfile.TemporaryDirectory() as dirname:
            path = self.package(Path(dirname))
            with patch('karaoke.xsk_reader.existing_key', side_effect=PermissionError('locked')):
                with self.assertRaises(PermissionError):
                    read_xsk(path)
