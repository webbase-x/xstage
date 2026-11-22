"""P2 virtual mixer contracts, independent of ASIO hardware."""
from array import array
import sys
import unittest
from karaoke.virtual_bus_mixer import VirtualBusMixer


def pcm(*samples):
    a = array("f", samples)
    if sys.byteorder != "little":
        a.byteswap()
    return a.tobytes()


def samples(data):
    a = array("f")
    a.frombytes(data)
    if sys.byteorder != "little":
        a.byteswap()
    return list(a)


class VirtualBusMixerTests(unittest.TestCase):
    def test_bus_counts_and_isolated_meters(self):
        for count in (2, 4, 8, 16):
            with self.subTest(count=count):
                mixer = VirtualBusMixer(count)
                self.assertEqual(samples(mixer.process(count - 1, pcm(.5, -.5))), [.5, -.5])
                self.assertEqual(mixer.meters[count - 1], (.5, .5))
                self.assertEqual(mixer.meters[0], (0., 0.))

    def test_gain_pan_and_mute(self):
        mixer = VirtualBusMixer(4)
        mixer.configure(0, gain=.5, pan=-1.)
        self.assertEqual(samples(mixer.process(0, pcm(.8, .8))), [.4000000059604645, 0.])
        mixer.configure(0, mute=True)
        self.assertEqual(samples(mixer.process(0, pcm(.8, .8))), [0., 0.])

    def test_partial_strip_updates_preserve_gain_pan_and_solo(self):
        mixer = VirtualBusMixer(4)
        mixer.configure(1, gain=.5, pan=-1., solo=True)
        mixer.configure(1, mute=True)
        self.assertEqual((mixer.strips[1].gain, mixer.strips[1].pan,
                          mixer.strips[1].solo, mixer.strips[1].mute),
                         (.5, -1., True, True))
        mixer.configure(1, mute=False)
        self.assertEqual(samples(mixer.process(1, pcm(.8, .8))),
                         [.4000000059604645, 0.])
        self.assertEqual(samples(mixer.process(0, pcm(.5, .5))), [0., 0.])
        mixer.configure(1, solo=False)
        self.assertEqual(mixer.strips[1].gain, .5)
        self.assertEqual(mixer.strips[1].pan, -1.)
        self.assertEqual(samples(mixer.process(0, pcm(.5, .5))), [.5, .5])

    def test_invalid_partial_update_does_not_change_existing_strip(self):
        mixer = VirtualBusMixer(2)
        mixer.configure(0, gain=.7, pan=.25, mute=True)
        before = mixer.strips[0]
        with self.assertRaises(ValueError):
            mixer.configure(0, solo=True, gain=float("nan"))
        self.assertEqual(mixer.strips[0], before)

    def test_solo_silences_other_buses(self):
        mixer = VirtualBusMixer(4)
        mixer.configure(2, solo=True)
        self.assertEqual(samples(mixer.process(0, pcm(.5, .5))), [0., 0.])
        self.assertEqual(samples(mixer.process(2, pcm(.5, .5))), [.5, .5])

    def test_nonfinite_samples_are_sanitized_and_peak_limited(self):
        mixer = VirtualBusMixer(2)
        out = samples(mixer.process(0, pcm(float("nan"), float("inf"), 4., -4.)))
        self.assertEqual(out[:2], [0., 0.])
        self.assertTrue(all(abs(value) <= .981 for value in out))
        self.assertTrue(all(value == value for value in out))

    def test_rejects_invalid_config_and_pcm(self):
        mixer = VirtualBusMixer(2)
        with self.assertRaises(ValueError):
            mixer.configure(0, gain=float("nan"))
        with self.assertRaises(ValueError):
            mixer.configure(0, pan=2.)
        with self.assertRaises(ValueError):
            mixer.process(9, b"")
        with self.assertRaises(ValueError):
            mixer.process(0, b"bad")


if __name__ == "__main__":
    unittest.main()
