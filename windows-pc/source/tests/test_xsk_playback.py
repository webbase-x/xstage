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


class PortableXskPlaybackTests(unittest.TestCase):
    def package_xsk2(self, root):
        doc = {
            'schemaVersion': 2, 'format': 'XSK', 'formatVersion': 2,
            'songCode': '00001', 'title': 'ทำได้เพียง', 'artist': '25 Hours',
            'createdBy': 'X-Stage Song Studio',
            'audio': {'file': '00001.mid', 'type': 'MID', 'size': len(MIDI),
                      'sha256': hashlib.sha256(MIDI).hexdigest()},
            'lines': [{'startTime': 0.0, 'text': 'สวัสดี',
                       'characters': [{'startTime': 0.0, 'text': 'ส'},
                                      {'startTime': 0.2, 'text': 'ว'}]}]}
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('00001.mid', MIDI)
            z.writestr('00001.json', json.dumps(doc, ensure_ascii=False))
        path = root / '00001.xsk'
        path.write_bytes(b'XSK2' + output.getvalue())
        return path

    def test_xsk2_no_key_title_artist_cursor_and_db_inspection(self):
        from karaoke.smf import load_midi
        from karaoke.ingest import Inspector
        with tempfile.TemporaryDirectory() as dirname:
            path = self.package_xsk2(Path(dirname))
            original = path.read_bytes()
            raw, doc = read_xsk(path)
            self.assertEqual(raw, MIDI)
            self.assertEqual((doc['title'], doc['artist']), ('ทำได้เพียง', '25 Hours'))
            song = load_midi(path)
            self.assertEqual((song.title, song.artist), ('ทำได้เพียง', '25 Hours'))
            self.assertEqual(song.lyrics.lines[0].words[1], (0.2, 'ว'))
            indexed, warnings = Inspector().inspect(path)
            self.assertEqual((indexed['title'], indexed['artist']),
                             ('ทำได้เพียง', '25 Hours'))
            self.assertEqual(indexed['format'], 'XSK')
            self.assertEqual(path.read_bytes(), original,
                             'Inspecting or playing XSK2 must never rewrite the source package')

    def test_xsk2_rejects_wrong_sha_without_windows_key(self):
        with tempfile.TemporaryDirectory() as dirname:
            path = self.package_xsk2(Path(dirname))
            with zipfile.ZipFile(io.BytesIO(path.read_bytes()[4:])) as z:
                doc = json.loads(z.read('00001.json'))
            doc['audio']['sha256'] = '0' * 64
            out = io.BytesIO()
            with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
                z.writestr('00001.mid', MIDI)
                z.writestr('00001.json', json.dumps(doc))
            path.write_bytes(b'XSK2' + out.getvalue())
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                read_xsk(path)


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
