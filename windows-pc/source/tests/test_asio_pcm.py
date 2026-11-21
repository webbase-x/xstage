"""Pure PCM staging contracts; does not access real ASIO hardware."""
import ctypes
import unittest
from karaoke.asio_pcm import AsioPcmQueue, copy_pcm_to_buffer


class AsioPcmQueueTests(unittest.TestCase):
    def test_preserves_frames_and_fills_underrun_with_silence(self):
        q = AsioPcmQueue(4)
        q.push(b'abcdefgh' * 2)
        self.assertEqual(q.pop(3), b'abcdefgh' * 2 + bytes(8))
        self.assertEqual(q.underrun_frames, 1)
        self.assertEqual(q.buffered_frames, 0)

    def test_discards_oldest_audio_when_full(self):
        q = AsioPcmQueue(2)
        q.push(b'abcdefgh')
        q.push(b'ABCDEFGH' * 2)
        self.assertEqual(q.pop(2), b'ABCDEFGH' * 2)
        self.assertEqual(q.dropped_frames, 1)

    def test_native_copy_and_invalid_alignment(self):
        q = AsioPcmQueue(2)
        with self.assertRaises(ValueError):
            q.push(b'bad')
        q.push(b'12345678')
        target = ctypes.create_string_buffer(16)
        self.assertEqual(copy_pcm_to_buffer(q, target, 2), 16)
        self.assertEqual(target.raw, b'12345678' + bytes(8))


if __name__ == '__main__':
    unittest.main()
