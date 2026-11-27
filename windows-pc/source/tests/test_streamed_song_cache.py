import hashlib
import tempfile
import unittest
from pathlib import Path
from karaoke.streamed_song_cache import StreamedSongCache

class StreamedSongCacheTests(unittest.TestCase):
    def test_verified_reuse_offline_and_partial_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "song.xmid"
            data = b"abc123" * 250000
            source.write_bytes(data)
            md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()
            song = {"path": str(source), "payload": {"xmid": {"md5Checksum": md5, "size": len(data)}}}
            folder = root / "cache"
            folder.mkdir()
            partial = folder / f"{md5}-{len(data)}.xmid.part"
            partial.write_bytes(data[:100000])
            cache = StreamedSongCache(folder)
            try:
                cache.request([song])
                cache.future.result(timeout=10)
                saved = cache.lookup(song)
                self.assertIsNotNone(saved)
                self.assertEqual(saved.read_bytes(), data)
                self.assertFalse(partial.exists())
                source.unlink()
                self.assertEqual(cache.lookup(song), saved)
            finally:
                cache.close()
            again = StreamedSongCache(folder)
            try:
                self.assertEqual(again.lookup(song), saved)
            finally:
                again.close()

    def test_bad_checksum_not_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "song.xsk"
            source.write_bytes(b"wrong")
            song = {"path":str(source), "payload":{"xsk":{"md5Checksum":"a"*32,"size":5}}}
            cache = StreamedSongCache(root/"cache")
            try:
                cache.request([song])
                cache.future.result(timeout=10)
                self.assertIsNone(cache.lookup(song))
            finally:
                cache.close()
