"""Mocked BASSASIO discovery contracts; no real audio device required."""
import ctypes
import unittest
from unittest.mock import Mock

from karaoke.asio_devices import discover_asio


class AsioDeviceTests(unittest.TestCase):
    def test_discover_driver_names_without_initializing_audio(self):
        dll = Mock()
        dll.BASS_ASIO_GetVersion.return_value = 0x1040000
        names = [(b'ASIO Driver A', b'a.dll'), (b'ASIO Driver B', b'b.dll')]
        def info(index, pointer):
            if index >= len(names):
                return 0
            from karaoke.asio_devices import BASS_ASIO_DEVICEINFO
            record = ctypes.cast(pointer, ctypes.POINTER(BASS_ASIO_DEVICEINFO)).contents
            record.name, record.driver = names[index]
            return 1
        dll.BASS_ASIO_GetDeviceInfo.side_effect = info
        result = discover_asio('.', bindings=dll)
        self.assertEqual([(item.index, item.name) for item in result],
                         [(0, 'ASIO Driver A'), (1, 'ASIO Driver B')])
        dll.BASS_ASIO_Init.assert_not_called()

    def test_reject_incompatible_addon(self):
        dll = Mock()
        dll.BASS_ASIO_GetVersion.return_value = 0x2030000
        with self.assertRaises(OSError):
            discover_asio('.', bindings=dll)


if __name__ == '__main__':
    unittest.main()
