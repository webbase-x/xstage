"""ASIO host lifecycle contracts with fake native bindings; no hardware."""
import unittest
from karaoke.asio_output import AsioOutput


class Function:
    def __init__(self, value=1):
        self.value = value
        self.calls = []
    def __call__(self, *args):
        self.calls.append(args)
        return self.value


class Bindings:
    def __init__(self, fail=None):
        for name in ('Init', 'Free', 'ChannelEnable', 'ChannelJoin',
                     'ChannelSetFormat', 'ChannelSetRate', 'Start', 'Stop', 'IsStarted'):
            setattr(self, 'BASS_ASIO_' + name, Function(0 if name == fail else 1))
        self.BASS_ASIO_ErrorGetCode = Function(7)


class Bridge:
    instances = []
    def __init__(self, native, capacity_frames):
        self.handle = 123
        self.closed = False
        self.__class__.instances.append(self)
    def callback_address(self):
        return 456
    def push(self, pcm):
        return len(pcm) // 8
    def close(self):
        self.closed = True


class AsioHostTests(unittest.TestCase):
    def test_start_push_and_close(self):
        dll = Bindings()
        host = AsioOutput('unused', device=0, bindings=dll, bridge_factory=Bridge)
        self.assertTrue(host.started)
        self.assertEqual(host.push(bytes(16)), 2)
        host.close()
        self.assertEqual(len(dll.BASS_ASIO_Stop.calls), 1)
        self.assertEqual(len(dll.BASS_ASIO_Free.calls), 1)
        self.assertTrue(Bridge.instances[-1].closed)

    def test_early_driver_stop_reports_failure(self):
        dll = Bindings()
        host = AsioOutput('unused', device=0, bindings=dll, bridge_factory=Bridge)
        self.assertTrue(host.check_health())
        dll.BASS_ASIO_IsStarted.value = 0
        with self.assertRaises(OSError):
            host.check_health()
        host.close()

    def test_failed_start_releases_native_bridge(self):
        dll = Bindings(fail='Start')
        with self.assertRaises(OSError):
            AsioOutput('unused', device=0, bindings=dll, bridge_factory=Bridge)
        self.assertEqual(len(dll.BASS_ASIO_Free.calls), 1)
        self.assertTrue(Bridge.instances[-1].closed)

    def test_failed_driver_free_keeps_callback_buffer_alive(self):
        dll = Bindings()
        host = AsioOutput('unused', device=0, bindings=dll, bridge_factory=Bridge)
        owned = host.bridge
        dll.BASS_ASIO_Free.value = 0
        with self.assertRaises(OSError):
            host.close()
        self.assertFalse(owned.closed)
        self.assertTrue(host.initialized)
        dll.BASS_ASIO_Free.value = 1
        host.close()
        self.assertTrue(owned.closed)

    def test_rejects_odd_stereo_channel(self):
        with self.assertRaises(ValueError):
            AsioOutput('unused', device=0, channel=1, bindings=Bindings(),
                       bridge_factory=Bridge)


if __name__ == '__main__':
    unittest.main()
