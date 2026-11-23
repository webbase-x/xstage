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

    def test_preset_round_trip_and_independent_snapshot(self):
        mixer = VirtualBusMixer(4)
        mixer.configure(0, gain=.25, pan=-.5, solo=True)
        mixer.configure(3, gain=1.5, mute=True)
        preset = mixer.snapshot()
        preset["strips"][0]["gain"] = .75
        self.assertEqual(mixer.strips[0].gain, .25)
        restored = VirtualBusMixer(4)
        restored.apply_snapshot(preset)
        self.assertEqual(restored.strips[0].gain, .75)
        self.assertEqual(restored.strips[0].pan, -.5)
        self.assertTrue(restored.strips[0].solo)
        self.assertTrue(restored.strips[3].mute)
        self.assertEqual(restored.snapshot(), preset)

    def test_invalid_presets_are_rejected_atomically(self):
        mixer = VirtualBusMixer(2)
        mixer.configure(0, gain=.6, pan=.2)
        original = mixer.snapshot()
        import copy
        invalid = []
        for field, value in (("version", 2), ("bus_count", 4), ("strips", [])):
            preset = copy.deepcopy(original)
            preset[field] = value
            invalid.append(preset)
        for bus, field, value in ((0, "gain", float("nan")),
                                  (1, "mute", 1), (1, "pan", 2)):
            preset = copy.deepcopy(original)
            preset["strips"][bus][field] = value
            invalid.append(preset)
        preset = copy.deepcopy(original)
        preset["strips"][1]["unexpected"] = True
        invalid.append(preset)
        for preset in invalid:
            with self.subTest(preset=preset):
                with self.assertRaises(ValueError):
                    mixer.apply_snapshot(preset)
                self.assertEqual(mixer.snapshot(), original)

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

    def test_clipping_diagnostics_are_per_bus_and_reset_each_block(self):
        mixer = VirtualBusMixer(2, ceiling=.8)
        mixer.configure(0, gain=2.)
        output = samples(mixer.process(0, pcm(.6, -.6, .1, -.1)))
        self.assertEqual(mixer.clipped_samples[0], 2)
        self.assertEqual(mixer.clipped_samples[1], 0)
        self.assertAlmostEqual(output[0], .8, places=6)
        self.assertAlmostEqual(output[1], -.8, places=6)
        self.assertEqual(mixer.meters[0], (output[0], abs(output[1])))
        mixer.process(0, pcm(.1, .1))
        self.assertEqual(mixer.clipped_samples[0], 0)
        mixer.process(1, pcm(2., 2.))
        self.assertEqual(mixer.clipped_samples[1], 2)
        mixer.process(1, b"")
        self.assertEqual(mixer.clipped_samples[1], 0)

    def test_muted_and_nonfinite_input_do_not_report_false_clipping(self):
        mixer = VirtualBusMixer(2)
        mixer.configure(0, mute=True)
        mixer.process(0, pcm(3., -3.))
        self.assertEqual(mixer.clipped_samples[0], 0)
        mixer.configure(0, mute=False)
        mixer.process(0, pcm(float("inf"), float("nan")))
        self.assertEqual(mixer.clipped_samples[0], 0)

    def test_rms_meters_track_post_fader_audio_and_reset_per_block(self):
        mixer = VirtualBusMixer(2, ceiling=.8)
        mixer.configure(0, gain=.5)
        mixer.process(0, pcm(.4, -.4, .8, -.8))
        self.assertAlmostEqual(mixer.rms_meters[0][0], (0.2 ** 2 / 2 + 0.4 ** 2 / 2) ** .5)
        self.assertAlmostEqual(mixer.rms_meters[0][1], mixer.rms_meters[0][0])
        self.assertEqual(mixer.rms_meters[1], (0., 0.))
        mixer.configure(0, mute=True)
        mixer.process(0, pcm(.8, .8))
        self.assertEqual(mixer.rms_meters[0], (0., 0.))
        mixer.configure(0, mute=False, gain=2.)
        mixer.process(0, pcm(.8, -.8))
        self.assertAlmostEqual(mixer.rms_meters[0][0], .8, places=6)
        self.assertEqual(mixer.clipped_samples[0], 2)
        mixer.process(0, b"")
        self.assertEqual(mixer.rms_meters[0], (0., 0.))

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
