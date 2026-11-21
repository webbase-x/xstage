"""Software-only ABI regression for the compiled Windows ASIO bridge.

Runs on the Windows build runner before packaging. It calls the real exported
callback but never initializes an ASIO driver or opens an audio device.
"""
import ctypes
import os
from pathlib import Path
import struct
import unittest

from karaoke.asio_native_bridge import NativePcmBridge


NATIVE = Path(__file__).resolve().parents[1] / 'native' / 'x64'


@unittest.skipUnless(os.name == 'nt', 'Native ASIO callback requires Windows')
class NativeAsioAbiTests(unittest.TestCase):
    def setUp(self):
        if not (NATIVE / 'xstage_asio_pcm.dll').is_file():
            if os.environ.get('XSTAGE_REQUIRE_ASIO_NATIVE') == '1':
                self.fail('Missing compiled ASIO DLL; check the MSVC build step')
            self.skipTest('Optional native ASIO bridge not compiled on this workstation')
        self.bridge = NativePcmBridge(NATIVE, capacity_frames=4)

    def tearDown(self):
        self.bridge.close()

    def callback(self, pcm_buffer, byte_count, *, input_channel=False):
        fn = self.bridge.dll.xstage_asio_callback
        return fn(int(input_channel), 0, ctypes.cast(pcm_buffer, ctypes.c_void_p),
                  byte_count, ctypes.c_void_p(self.bridge.handle))

    def test_interleaved_stereo_float32_and_underrun(self):
        frames = struct.pack('<4f', .25, -.25, .75, -.75)
        self.assertEqual(self.bridge.push(frames), 2)
        self.assertEqual(self.bridge.buffered_frames(), 2)
        buf = ctypes.create_string_buffer(32)
        self.assertEqual(self.callback(buf, 32), 32)
        self.assertEqual(buf.raw, frames + bytes(16))
        self.assertEqual(self.bridge.buffered_frames(), 0)
        self.assertEqual(self.bridge.dll.xstage_pcm_underruns(self.bridge.handle), 2)

    def test_bounded_fifo_overrun_and_wrap(self):
        self.assertEqual(self.bridge.push(bytes(4 * 8)), 4)
        self.assertEqual(self.bridge.push(struct.pack('<2f', 1, -1)), 0)
        self.assertEqual(self.bridge.dll.xstage_pcm_overruns(self.bridge.handle), 1)
        first = ctypes.create_string_buffer(32)
        self.assertEqual(self.callback(first, 32), 32)
        self.assertEqual(self.bridge.buffered_frames(), 0)
        self.assertEqual(self.bridge.push(struct.pack('<2f', .5, -.5)), 1)
        second = ctypes.create_string_buffer(8)
        self.assertEqual(self.callback(second, 8), 8)
        self.assertEqual(second.raw, struct.pack('<2f', .5, -.5))

    def test_input_callback_does_not_overwrite_driver_buffer(self):
        captured = ctypes.create_string_buffer(b'INPUT123', 8)
        self.assertEqual(self.callback(captured, 8, input_channel=True), 0)
        self.assertEqual(captured.raw, b'INPUT123')
        self.assertEqual(self.bridge.buffered_frames(), 0)

    def test_unaligned_callback_is_silent(self):
        buf = ctypes.create_string_buffer(b'ABCDEF', 6)
        self.assertEqual(self.callback(buf, 6), 0)
        self.assertEqual(buf.raw, bytes(6))


if __name__ == '__main__':
    unittest.main()
