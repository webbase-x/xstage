"""Software-only runtime failover contracts; no hardware playback."""
import unittest

from karaoke.asio_failover import FailoverMidiOutput


class Output:
    def __init__(self):
        self.events = []
        self.closed = False
        self.failed = False
        self.effects = []
    def check_health(self):
        if self.failed:
            raise OSError('ASIO driver disconnected')
    def send(self, msg):
        self.check_health()
        self.events.append(bytes(msg))
    def reset(self):
        self.events.clear()
    def set_channel_tone(self, *args, **kwargs):
        self.effects.append(('tone', args, kwargs))
    def set_drum_tone(self, *args, **kwargs):
        self.effects.append(('drum', args, kwargs))
    def set_channel_eq(self, *args, **kwargs):
        self.effects.append(('eq', args, kwargs))
    def close(self):
        self.closed = True


class AsioLiveRecoveryTests(unittest.TestCase):
    def test_runtime_failure_replays_controller_program_pitch_and_active_notes(self):
        primary, backup, messages = Output(), Output(), []
        driver = FailoverMidiOutput(primary, lambda: backup, notify=messages.append)
        driver.send(bytes([0xB0, 7, 100]))
        driver.send(bytes([0xC0, 5]))
        driver.send(bytes([0xE0, 0, 64]))
        driver.send(bytes([0x90, 60, 98]))
        driver.send(bytes([0x90, 61, 88]))
        driver.send(bytes([0x80, 61, 0]))
        driver.set_channel_tone(0, cutoff=80)
        primary.failed = True
        driver.poll()
        self.assertTrue(primary.closed)
        self.assertIs(driver.active, backup)
        self.assertIn(bytes([0xB0, 7, 100]), backup.events)
        self.assertIn(bytes([0xC0, 5]), backup.events)
        self.assertIn(bytes([0xE0, 0, 64]), backup.events)
        self.assertIn(bytes([0x90, 60, 98]), backup.events)
        self.assertNotIn(bytes([0x90, 61, 88]), backup.events)
        self.assertEqual(backup.effects[0], ('tone', (0,), {'cutoff': 80}))
        self.assertEqual(len(messages), 1)
        driver.send(bytes([0x90, 62, 90]))
        self.assertIn(bytes([0x90, 62, 90]), backup.events)
        driver.close()
        self.assertTrue(backup.closed)

    def test_failed_asio_free_does_not_open_second_audio_backend(self):
        class FailingClose(Output):
            def close(self):
                raise OSError('driver release failed')
        primary = FailingClose()
        primary.failed = True
        created = []
        driver = FailoverMidiOutput(primary, lambda: created.append(Output()))
        with self.assertRaises(OSError):
            driver.poll()
        self.assertEqual(created, [])

    def test_reset_drops_old_notes_and_controllers(self):
        primary, backup = Output(), Output()
        driver = FailoverMidiOutput(primary, lambda: backup)
        driver.send(bytes([0x90, 60, 90]))
        driver.reset()
        primary.failed = True
        driver.poll()
        self.assertNotIn(bytes([0x90, 60, 90]), backup.events)


if __name__ == '__main__':
    unittest.main()
