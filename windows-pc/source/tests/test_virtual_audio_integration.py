"""Hardware-free cross-phase integration scenarios for X-Stage Karaoke PC.

Virtual sinks model MIDI output; PCM mixer models post-render bus controls.
No claim of real driver, plugin, video, or physical speaker validation.
Run: python -m unittest discover -s tests -p 'test_virtual_audio_integration.py'
"""
from array import array
import sys
import unittest

from karaoke.audio_bus import MidiBusDispatcher, performance_plan
from karaoke.asio_backend import create_midi_output
from karaoke.virtual_bus_mixer import VirtualBusMixer


def stereo_pcm(left, right):
    samples = array("f", (left, right))
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def decode_pcm(data):
    samples = array("f")
    samples.frombytes(data)
    if sys.byteorder != "little":
        samples.byteswap()
    return tuple(samples)


class VirtualDevice:
    def __init__(self):
        self.messages = []
        self.closed = False
        self.unhealthy = False

    def send(self, data):
        self.messages.append(bytes(data))

    def check_health(self):
        if self.unhealthy:
            raise OSError("simulated device loss")

    def close(self):
        self.closed = True


class VirtualAudioIntegration(unittest.TestCase):
    def test_routing_and_mixer_independence_all_bus_counts(self):
        for count in (4, 8, 16):
            with self.subTest(buses=count):
                devices = {bus: VirtualDevice() for bus in range(count)}
                routing = performance_plan(count, {ch: ch % count for ch in range(16)})
                dispatch = MidiBusDispatcher(routing, {b: d.send for b, d in devices.items()})
                mixer = VirtualBusMixer(count)
                mixer.configure(count - 1, mute=True)
                for channel in range(16):
                    dispatch.dispatch(bytes([0x90 | channel, 64, 90]))
                for bus, device in devices.items():
                    self.assertEqual(len(device.messages), len([ch for ch in range(16) if ch % count == bus]))
                    result = decode_pcm(mixer.process(bus, stereo_pcm(.5, .5)))
                    self.assertEqual(result, (0., 0.) if bus == count - 1 else (.5, .5))

    def test_solo_and_asio_disconnect_preserve_fallback(self):
        mixer = VirtualBusMixer(4)
        mixer.configure(1, solo=True)
        self.assertEqual(decode_pcm(mixer.process(0, stereo_pcm(.4, .4))), (0., 0.))
        self.assertAlmostEqual(decode_pcm(mixer.process(1, stereo_pcm(.4, .4)))[0], .4, places=6)
        asio, bass = VirtualDevice(), VirtualDevice()
        notices = []
        output = create_midi_output(None, {"asio_output": {"enabled": True, "device": 0}},
                                    notify=notices.append, asio_factory=lambda *a, **k: asio,
                                    bass_factory=lambda *a, **k: bass)
        note = bytes((0x91, 60, 100))
        output.send(note)
        asio.unhealthy = True
        output.poll()
        self.assertTrue(asio.closed)
        self.assertIn(note, bass.messages)
        self.assertEqual(len(notices), 1)
        self.assertIn("BASS", notices[0])

    def test_malformed_virtual_pcm_rejected_without_device_access(self):
        mixer = VirtualBusMixer(8)
        with self.assertRaises(ValueError):
            mixer.process(0, b"broken")
        self.assertEqual(mixer.meters[0], (0., 0.))


if __name__ == "__main__":
    unittest.main()
