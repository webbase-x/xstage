"""P1 virtual-hardware acceptance: routing and ASIO failover without a sound card.

Run: python -m unittest discover -s tests -p 'test_p1_virtual_acceptance.py'
These tests prove software contracts only, NOT physical ASIO certification.
"""
import unittest

from karaoke.audio_bus import MidiBusDispatcher, performance_plan
from karaoke.asio_backend import create_midi_output


class VirtualMidiDevice:
    def __init__(self, *, fail_on_send=False, fail_on_health=False):
        self.messages = []
        self.closed = False
        self.fail_on_send = fail_on_send
        self.fail_on_health = fail_on_health

    def send(self, data):
        if self.fail_on_send:
            raise OSError("virtual ASIO output disconnected")
        self.messages.append(bytes(data))

    def check_health(self):
        if self.fail_on_health:
            raise OSError("virtual ASIO driver lost")

    def close(self):
        self.closed = True


class P1VirtualAcceptance(unittest.TestCase):
    def test_every_channel_isolated_across_four_eight_sixteen_buses(self):
        for count in (4, 8, 16):
            with self.subTest(bus_count=count):
                devices = {bus: VirtualMidiDevice() for bus in range(count)}
                plan = performance_plan(count, {ch: ch % count for ch in range(16)})
                router = MidiBusDispatcher(plan, {b: d.send for b, d in devices.items()})
                for channel in range(16):
                    router.dispatch(bytes([0x90 | channel, 60, 100]))
                for bus, device in devices.items():
                    expected = [bytes([0x90 | ch, 60, 100])
                                for ch in range(16) if ch % count == bus]
                    self.assertEqual(device.messages, expected)

    def test_drum_override_routes_note_off_and_broadcasts_controllers(self):
        devices = {bus: VirtualMidiDevice() for bus in range(4)}
        plan = performance_plan(4, {ch: 0 for ch in range(16)}, {36: 2, 38: 3})
        router = MidiBusDispatcher(plan, {b: d.send for b, d in devices.items()})
        on, off, reset = bytes([0x99, 36, 100]), bytes([0x89, 36, 0]), bytes([0xB9, 123, 0])
        router.dispatch(on)
        router.dispatch(off)
        router.dispatch(reset)
        self.assertEqual(devices[2].messages, [on, off, reset])
        self.assertEqual(devices[0].messages, [reset])
        self.assertEqual(devices[3].messages, [reset])
        self.assertEqual(devices[1].messages, [])

    def test_asio_start_failure_falls_back_to_bass(self):
        bass = VirtualMidiDevice()
        notices = []
        def broken_asio(*args, **kwargs):
            raise OSError("virtual driver unavailable")
        output = create_midi_output(None, {"asio_output": {"enabled": True, "device": 0}},
                                    notify=notices.append, bass_factory=lambda *a, **kw: bass,
                                    asio_factory=broken_asio)
        output.send(bytes([0x90, 60, 100]))
        self.assertEqual(bass.messages, [bytes([0x90, 60, 100])])
        self.assertEqual(len(notices), 1)
        self.assertIn("BASS", notices[0])

    def test_asio_runtime_disconnect_restores_active_note_to_bass(self):
        asio = VirtualMidiDevice()
        bass = VirtualMidiDevice()
        notices = []
        output = create_midi_output(None, {"asio_output": {"enabled": True, "device": 0}},
                                    notify=notices.append, bass_factory=lambda *a, **kw: bass,
                                    asio_factory=lambda *a, **kw: asio)
        note = bytes([0x90, 64, 110])
        output.send(note)
        asio.fail_on_health = True
        output.poll()
        self.assertTrue(asio.closed)
        self.assertIn(note, bass.messages)
        self.assertEqual(len(notices), 1)
        self.assertIn("BASS", notices[0])
        output.send(bytes([0x80, 64, 0]))
        self.assertEqual(bass.messages[-1], bytes([0x80, 64, 0]))

    def test_asio_disabled_keeps_legacy_bass_path(self):
        bass = VirtualMidiDevice()
        output = create_midi_output(None, {}, bass_factory=lambda *a, **kw: bass,
                                    asio_factory=lambda *a, **kw: self.fail("ASIO must stay disabled"))
        output.send(bytes([0x90, 60, 90]))
        self.assertEqual(bass.messages, [bytes([0x90, 60, 90])])


if __name__ == "__main__":
    unittest.main()
