"""P1 explicit native output device selection contract."""
import unittest
from karaoke import audio_device


class FakeBass:
    def __init__(self):
        self.init_calls = []
        self.selected = []
        self.freed = 0
        self.device = 0

    def BASS_Init(self, requested, frequency, flags, window, clsid):
        self.init_calls.append(requested)
        self.device = 1 if requested == -1 else requested
        return True

    def BASS_GetDevice(self):
        return self.device

    def BASS_SetDevice(self, device):
        self.selected.append(device)
        self.device = device
        return True

    def BASS_Free(self):
        self.freed += 1
        return True


class AudioDeviceSelectionTests(unittest.TestCase):
    def test_explicit_devices_are_independent_and_reference_counted(self):
        dll = FakeBass()
        a, _ = audio_device.acquire(dll, device_id=2)
        b, _ = audio_device.acquire(dll, device_id=3)
        a2, _ = audio_device.acquire(dll, device_id=2)
        self.assertEqual(a, a2)
        self.assertNotEqual(a, b)
        self.assertEqual(dll.init_calls, [2, 3])
        audio_device.release(dll, a)
        self.assertEqual(dll.freed, 0)
        audio_device.release(dll, a2)
        audio_device.release(dll, b)
        self.assertEqual(dll.freed, 2)

    def test_default_stereo_and_decode_device_preserved(self):
        dll = FakeBass()
        live, _ = audio_device.acquire(dll)
        decode, _ = audio_device.acquire(dll, decode=True)
        self.assertEqual(dll.init_calls, [-1, 0])
        audio_device.release(dll, decode)
        audio_device.release(dll, live)

    def test_invalid_devices_fail_before_native_init(self):
        dll = FakeBass()
        for options in ({'device_id': -2}, {'device_id': True},
                        {'decode': True, 'device_id': 2}):
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    audio_device.acquire(dll, **options)
        self.assertEqual(dll.init_calls, [])


if __name__ == '__main__':
    unittest.main()
