"""P2 virtual mixer contracts, independent of ASIO hardware."""
from array import array
import math
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
    def test_process_many_validates_entire_batch_before_meter_mutation(self):
        mixer = VirtualBusMixer(4)
        original = mixer.diagnostics_snapshot()
        with self.assertRaises(ValueError):
            mixer.process_many({0: pcm(1.5, 0.0), 1: b"bad"})
        self.assertEqual(mixer.diagnostics_snapshot(), original)
        with self.assertRaises(ValueError):
            mixer.process_many({0: pcm(1.5, 0.0), True: pcm(.1, .1)})
        self.assertEqual(mixer.diagnostics_snapshot(), original)

    def test_process_many_isolates_buses_and_preserves_preset(self):
        mixer = VirtualBusMixer(4)
        mixer.configure(1, gain=.5)
        preset = mixer.snapshot()
        output = mixer.process_many({0: pcm(.25, -.25), 1: pcm(.5, -.5)})
        self.assertEqual(list(output), [0, 1])
        self.assertEqual(samples(output[0]), [.25, -.25])
        self.assertEqual(samples(output[1]), [.25, -.25])
        self.assertEqual(mixer.meters[2], (0., 0.))
        self.assertEqual(mixer.snapshot(), preset)
        self.assertEqual(mixer.process_many({}), {})

    def test_limiter_reduction_db_is_per_channel_and_clears_on_silence(self):
        mixer = VirtualBusMixer(2, ceiling=.5)
        mixer.process(0, pcm(1., .25))
        reduction = mixer.limiter_reduction_db_snapshot()
        self.assertAlmostEqual(reduction[0][0], 20 * math.log10(.5), places=5)
        self.assertEqual(reduction[0][1], 0.)
        self.assertEqual(reduction[1], (0., 0.))
        reduction[0] = (100., 100.)
        self.assertLess(mixer.limiter_reduction_db_snapshot()[0][0], 0.)
        preset = mixer.snapshot()
        mixer.process(0, b"")
        self.assertEqual(mixer.limiter_reduction_db_snapshot()[0], (0., 0.))
        self.assertEqual(mixer.snapshot(), preset)

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

    def test_atomic_multi_strip_scene_preserves_unmodified_controls_and_meters(self):
        mixer = VirtualBusMixer(4)
        mixer.configure(0, gain=.5, pan=-.25)
        mixer.process(0, pcm(.5, .5))
        diagnostics = mixer.diagnostics_snapshot()
        mixer.configure_many({0: {"mute": True}, 2: {"gain": 1.5, "solo": True}})
        self.assertEqual(mixer.strips[0].gain, .5)
        self.assertEqual(mixer.strips[0].pan, -.25)
        self.assertTrue(mixer.strips[0].mute)
        self.assertEqual(mixer.strips[2].gain, 1.5)
        self.assertTrue(mixer.strips[2].solo)
        self.assertEqual(mixer.strips[1].gain, 1.)
        self.assertEqual(mixer.diagnostics_snapshot(), diagnostics)

    def test_atomic_multi_strip_scene_rejects_all_invalid_changes_without_partial_write(self):
        mixer = VirtualBusMixer(2)
        mixer.configure(0, gain=.7)
        before = mixer.snapshot()
        invalid = [
            {0: {"mute": True}, 1: {"gain": float("nan")}},
            {0: {"mute": True}, 2: {"gain": .5}},
            {0: {"mute": True}, True: {"solo": True}},
            {0: {"mute": True}, 1: {"unknown": 1}},
            {0: {"mute": True}, 1: {}},
            {0: {"mute": True}, 1: {"solo": 1}},
            [(0, {"gain": .5})],
            None,
        ]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                mixer.configure_many(changes)
            self.assertEqual(mixer.snapshot(), before)
        mixer.configure_many({})
        self.assertEqual(mixer.snapshot(), before)

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
        self.assertAlmostEqual(mixer.meters[0][0], output[0], places=6)
        self.assertAlmostEqual(mixer.meters[0][1], abs(output[1]), places=6)
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

    def test_pre_limiter_peak_distinguishes_overdrive_from_output_ceiling(self):
        mixer = VirtualBusMixer(2, ceiling=.8)
        mixer.configure(0, gain=2.)
        mixer.process(0, pcm(.6, -.3, .1, -.1))
        self.assertAlmostEqual(mixer.pre_limit_peaks[0][0], 1.2, places=6)
        self.assertAlmostEqual(mixer.pre_limit_peaks[0][1], .6, places=6)
        self.assertAlmostEqual(mixer.meters[0][0], .8, places=6)
        self.assertEqual(mixer.clipped_samples[0], 1)
        self.assertEqual(mixer.pre_limit_peaks[1], (0., 0.))
        mixer.configure(0, mute=True)
        mixer.process(0, pcm(.9, .9))
        self.assertEqual(mixer.pre_limit_peaks[0], (0., 0.))
        mixer.process(0, b"")
        self.assertEqual(mixer.pre_limit_peaks[0], (0., 0.))

    def test_pre_limiter_peak_sanitizes_nonfinite_inputs(self):
        mixer = VirtualBusMixer(2)
        mixer.process(0, pcm(float("nan"), float("inf"), .5, -.25))
        self.assertAlmostEqual(mixer.pre_limit_peaks[0][0], .5)
        self.assertAlmostEqual(mixer.pre_limit_peaks[0][1], .25)

    def test_cumulative_clipping_is_isolated_and_explicitly_reset(self):
        mixer = VirtualBusMixer(2, ceiling=.8)
        mixer.process(0, pcm(1., -1.))
        mixer.process(0, pcm(1., .1))
        mixer.process(1, pcm(1., 1.))
        self.assertEqual(mixer.clipped_samples, {0: 1, 1: 2})
        self.assertEqual(mixer.total_clipped_samples, {0: 3, 1: 2})
        mixer.process(0, b"")
        self.assertEqual(mixer.clipped_samples[0], 0)
        self.assertEqual(mixer.total_clipped_samples[0], 3)
        mixer.reset_clipping_totals(0)
        self.assertEqual(mixer.total_clipped_samples, {0: 0, 1: 2})
        before = mixer.total_clipped_samples.copy()
        for invalid in (-1, 2, True, "0"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                mixer.reset_clipping_totals(invalid)
            self.assertEqual(mixer.total_clipped_samples, before)
        mixer.reset_clipping_totals()
        self.assertEqual(mixer.total_clipped_samples, {0: 0, 1: 0})

    def test_cumulative_clipping_ignores_mute_and_invalid_samples(self):
        mixer = VirtualBusMixer(2)
        mixer.configure(0, mute=True)
        mixer.process(0, pcm(2., -2.))
        mixer.configure(0, mute=False)
        mixer.process(0, pcm(float("inf"), float("nan")))
        self.assertEqual(mixer.total_clipped_samples[0], 0)

    def test_peak_holds_survive_silence_and_reset_independently(self):
        mixer = VirtualBusMixer(2, ceiling=.8)
        mixer.process(0, pcm(.7, -.4))
        mixer.process(0, pcm(.2, -.1))
        self.assertAlmostEqual(mixer.peak_holds[0][0], .7, places=6)
        self.assertAlmostEqual(mixer.peak_holds[0][1], .4, places=6)
        mixer.process(0, b"")
        self.assertEqual(mixer.meters[0], (0., 0.))
        self.assertAlmostEqual(mixer.peak_holds[0][0], .7, places=6)
        mixer.process(1, pcm(1., -1.))
        self.assertEqual(mixer.total_clipped_samples[1], 2)
        mixer.reset_peak_holds(0)
        self.assertEqual(mixer.peak_holds[0], (0., 0.))
        self.assertAlmostEqual(mixer.peak_holds[1][0], .8, places=6)
        self.assertEqual(mixer.total_clipped_samples[1], 2)
        before = mixer.peak_holds.copy()
        for invalid in (-1, 2, True, "0"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                mixer.reset_peak_holds(invalid)
            self.assertEqual(mixer.peak_holds, before)
        mixer.reset_peak_holds()
        self.assertEqual(mixer.peak_holds, {0: (0., 0.), 1: (0., 0.)})

    def test_peak_hold_respects_mute_and_solo(self):
        mixer = VirtualBusMixer(2)
        mixer.configure(1, solo=True)
        mixer.process(0, pcm(.9, .9))
        self.assertEqual(mixer.peak_holds[0], (0., 0.))
        mixer.configure(1, mute=True)
        mixer.process(1, pcm(.9, .9))
        self.assertEqual(mixer.peak_holds[1], (0., 0.))

    def test_extreme_finite_float32_input_is_safely_limited(self):
        mixer = VirtualBusMixer(2, ceiling=.8)
        mixer.configure(0, gain=2.)
        extreme = 3.4028234663852886e38
        output = samples(mixer.process(0, pcm(extreme, -extreme)))
        self.assertAlmostEqual(output[0], .8, places=6)
        self.assertAlmostEqual(output[1], -.8, places=6)
        self.assertEqual(mixer.clipped_samples[0], 2)
        self.assertTrue(all(math.isfinite(x) for x in output))
        self.assertTrue(all(math.isfinite(x) for x in mixer.pre_limit_peaks[0]))
        # The diagnostic must report the actual overload, not the limiter
        # ceiling, even when float32 samples approach their maximum value.
        self.assertGreater(mixer.pre_limit_peaks[0][0], extreme)
        self.assertGreater(mixer.pre_limit_peak_holds[0][1], extreme)
        self.assertGreater(mixer.levels_dbfs_snapshot()["pre_limit_peak_dbfs"][0][0], 700.)
        self.assertEqual(mixer.invalid_samples[0], 0)
        self.assertEqual(mixer.total_clipped_samples[0], 2)

    def test_diagnostics_snapshot_is_detached_and_presets_stay_clean(self):
        mixer = VirtualBusMixer(2, ceiling=.8)
        mixer.process(0, pcm(1., -.5))
        before = mixer.diagnostics_snapshot()
        self.assertEqual(before["clipped_samples"][0], 1)
        self.assertEqual(before["total_clipped_samples"][0], 1)
        self.assertEqual(before["meters"][1], (0., 0.))
        self.assertEqual(set(before), {
            "meters", "rms_meters", "pre_limit_peaks", "peak_holds",
            "pre_limit_peak_holds",
            "clipped_samples", "invalid_samples", "total_invalid_samples",
            "total_clipped_samples",
        })
        for field in before:
            before[field][0] = None
        after = mixer.diagnostics_snapshot()
        self.assertEqual(after["clipped_samples"][0], 1)
        self.assertEqual(after["total_clipped_samples"][0], 1)
        self.assertNotEqual(after["meters"][0], None)
        self.assertEqual(set(mixer.snapshot()), {"version", "bus_count", "strips"})
        mixer.reset_clipping_totals(0)
        self.assertEqual(mixer.diagnostics_snapshot()["total_clipped_samples"][0], 0)

    def test_explicit_diagnostics_reset_is_isolated_and_preserves_presets(self):
        mixer = VirtualBusMixer(2, ceiling=.8)
        mixer.configure(0, gain=2., pan=.25)
        mixer.process(0, pcm(.9, -.9))
        mixer.process(1, pcm(.9, -.9))
        preset = mixer.snapshot()
        other = mixer.diagnostics_snapshot()
        mixer.reset_diagnostics(0)
        cleared = mixer.diagnostics_snapshot()
        for field in other:
            self.assertEqual(cleared[field][1], other[field][1])
            self.assertEqual(cleared[field][0], 0 if "samples" in field else (0., 0.))
        self.assertEqual(mixer.snapshot(), preset)
        before = mixer.diagnostics_snapshot()
        for invalid in (-1, 2, True, "0"):
            with self.subTest(bus=invalid), self.assertRaises(ValueError):
                mixer.reset_diagnostics(invalid)
            self.assertEqual(mixer.diagnostics_snapshot(), before)
        mixer.reset_diagnostics()
        for field, buses in mixer.diagnostics_snapshot().items():
            for value in buses.values():
                self.assertEqual(value, 0 if "samples" in field else (0., 0.))
        self.assertEqual(mixer.snapshot(), preset)

    def test_dbfs_snapshot_is_finite_isolated_and_does_not_change_audio(self):
        mixer = VirtualBusMixer(2, ceiling=.8)
        mixer.process(0, pcm(.5, -.5))
        before = mixer.snapshot()
        levels = mixer.levels_dbfs_snapshot()
        self.assertAlmostEqual(levels["peak_dbfs"][0][0],
                               20 * math.log10(.5), places=5)
        self.assertAlmostEqual(levels["rms_dbfs"][0][1],
                               20 * math.log10(.5), places=5)
        self.assertEqual(levels["peak_dbfs"][1], (-120., -120.))
        self.assertTrue(all(math.isfinite(v) for group in levels.values()
                            for pair in group.values() for v in pair))
        levels["peak_dbfs"][0] = (999., 999.)
        self.assertNotEqual(mixer.levels_dbfs_snapshot()["peak_dbfs"][0],
                            (999., 999.))
        self.assertEqual(mixer.snapshot(), before)
        mixer.process(0, b"")
        self.assertEqual(mixer.levels_dbfs_snapshot()["peak_dbfs"][0],
                         (-120., -120.))
        self.assertAlmostEqual(mixer.levels_dbfs_snapshot()["peak_hold_dbfs"][0][0],
                               20 * math.log10(.5), places=5)
        mixer.reset_diagnostics(0)
        self.assertEqual(mixer.levels_dbfs_snapshot()["peak_hold_dbfs"][0],
                         (-120., -120.))

    def test_pre_limiter_dbfs_exposes_overdrive_without_changing_output(self):
        mixer = VirtualBusMixer(2, ceiling=.8)
        mixer.configure(0, gain=2.)
        mixer.process(0, pcm(.6, -.25))
        levels = mixer.levels_dbfs_snapshot()
        self.assertAlmostEqual(levels["pre_limit_peak_dbfs"][0][0],
                               20 * math.log10(1.2), places=5)
        self.assertAlmostEqual(levels["pre_limit_peak_dbfs"][0][1],
                               20 * math.log10(.5), places=5)
        self.assertAlmostEqual(levels["peak_dbfs"][0][0],
                               20 * math.log10(.8), places=5)
        self.assertEqual(levels["pre_limit_peak_dbfs"][1], (-120., -120.))
        levels["pre_limit_peak_dbfs"][0] = (999., 999.)
        self.assertNotEqual(mixer.levels_dbfs_snapshot()["pre_limit_peak_dbfs"][0],
                            (999., 999.))
        mixer.process(0, b"")
        self.assertEqual(mixer.levels_dbfs_snapshot()["pre_limit_peak_dbfs"][0],
                         (-120., -120.))
        mixer.process(0, pcm(.6, -.25))
        mixer.reset_diagnostics(0)
        self.assertEqual(mixer.levels_dbfs_snapshot()["pre_limit_peak_dbfs"][0],
                         (-120., -120.))

    def test_pre_limit_peak_hold_survives_silence_and_resets_per_bus(self):
        mixer = VirtualBusMixer(2, ceiling=.8)
        mixer.configure(0, gain=2.)
        mixer.process(0, pcm(.75, -.5))
        mixer.process(0, pcm(.1, -.1))
        self.assertAlmostEqual(mixer.pre_limit_peak_holds[0][0], 1.5, places=5)
        self.assertAlmostEqual(mixer.pre_limit_peak_holds[0][1], 1., places=5)
        self.assertAlmostEqual(
            mixer.levels_dbfs_snapshot()["pre_limit_peak_hold_dbfs"][0][0],
            20 * math.log10(1.5), places=5)
        mixer.process(0, b"")
        self.assertEqual(mixer.pre_limit_peaks[0], (0., 0.))
        self.assertGreater(mixer.pre_limit_peak_holds[0][0], 1.)
        mixer.process(1, pcm(.5, .5))
        other = mixer.pre_limit_peak_holds[1]
        preset = mixer.snapshot()
        mixer.reset_peak_holds(0)
        self.assertEqual(mixer.pre_limit_peak_holds[0], (0., 0.))
        self.assertEqual(mixer.pre_limit_peak_holds[1], other)
        self.assertEqual(mixer.snapshot(), preset)
        mixer.process(0, pcm(.75, -.5))
        mixer.reset_diagnostics()
        self.assertEqual(mixer.pre_limit_peak_holds,
                         {0: (0., 0.), 1: (0., 0.)})
        self.assertEqual(mixer.snapshot(), preset)

    def test_dbfs_floor_validation_and_custom_floor(self):
        mixer = VirtualBusMixer(2)
        for invalid in (float("nan"), float("inf"), True, "minus 60", -301, 1):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                mixer.levels_dbfs_snapshot(floor_db=invalid)
        self.assertEqual(mixer.levels_dbfs_snapshot(floor_db=-60)["rms_dbfs"][0],
                         (-60., -60.))
        mixer.process(0, pcm(.00001, .00001))
        self.assertEqual(mixer.levels_dbfs_snapshot(floor_db=-60)["peak_dbfs"][0],
                         (-60., -60.))

    def test_nonfinite_pcm_is_silenced_counted_and_reset_per_bus(self):
        mixer = VirtualBusMixer(2)
        output = samples(mixer.process(0, pcm(float("nan"), float("inf"),
                                               float("-inf"), .25)))
        self.assertEqual(output[:3], [0., 0., 0.])
        self.assertAlmostEqual(output[3], .25, places=6)
        self.assertEqual(mixer.diagnostics_snapshot()["invalid_samples"], {0: 3, 1: 0})
        mixer.process(1, pcm(float("nan"), .5))
        mixer.process(0, b"")
        self.assertEqual(mixer.invalid_samples, {0: 0, 1: 1})
        mixer.reset_diagnostics(1)
        self.assertEqual(mixer.invalid_samples, {0: 0, 1: 0})

    def test_cumulative_invalid_pcm_survives_silence_and_isolated_reset(self):
        mixer = VirtualBusMixer(2)
        preset = mixer.snapshot()
        mixer.process(0, pcm(float("nan"), float("inf")))
        mixer.process(0, pcm(float("-inf"), .25))
        mixer.process(1, pcm(float("nan"), .5))
        self.assertEqual(mixer.diagnostics_snapshot()["total_invalid_samples"],
                         {0: 3, 1: 1})
        mixer.process(0, b"")
        self.assertEqual(mixer.invalid_samples[0], 0)
        self.assertEqual(mixer.total_invalid_samples[0], 3)
        detached = mixer.diagnostics_snapshot()
        detached["total_invalid_samples"][0] = 999
        self.assertEqual(mixer.total_invalid_samples[0], 3)
        for bad in (-1, True, "0"):
            with self.assertRaises(ValueError):
                mixer.reset_diagnostics(bad)
            self.assertEqual(mixer.total_invalid_samples, {0: 3, 1: 1})
        mixer.reset_diagnostics(0)
        self.assertEqual(mixer.total_invalid_samples, {0: 0, 1: 1})
        mixer.reset_diagnostics()
        self.assertEqual(mixer.total_invalid_samples, {0: 0, 1: 0})
        self.assertEqual(mixer.snapshot(), preset)

    def test_reset_invalid_totals_preserves_live_meters_and_other_bus(self):
        mixer = VirtualBusMixer(2)
        mixer.configure(0, gain=1.5)
        mixer.process(0, pcm(float("nan"), .5))
        mixer.process(1, pcm(float("inf"), -.25))
        preset = mixer.snapshot()
        before = mixer.diagnostics_snapshot()
        self.assertEqual(before["total_invalid_samples"], {0: 1, 1: 1})
        for invalid in (-1, 2, True, "0"):
            with self.subTest(bus=invalid), self.assertRaises(ValueError):
                mixer.reset_invalid_totals(invalid)
            self.assertEqual(mixer.diagnostics_snapshot(), before)
        mixer.reset_invalid_totals(0)
        after = mixer.diagnostics_snapshot()
        self.assertEqual(after["total_invalid_samples"], {0: 0, 1: 1})
        for field in before:
            if field != "total_invalid_samples":
                self.assertEqual(after[field], before[field])
        self.assertEqual(mixer.snapshot(), preset)
        mixer.reset_invalid_totals()
        self.assertEqual(mixer.total_invalid_samples, {0: 0, 1: 0})
        self.assertEqual(mixer.invalid_samples, before["invalid_samples"])

    def test_overload_flags_track_current_block_and_are_detached(self):
        mixer = VirtualBusMixer(2, ceiling=.8)
        self.assertEqual(mixer.overload_snapshot(), {0: False, 1: False})
        mixer.process(0, pcm(.9, .1))
        self.assertEqual(mixer.overload_snapshot(), {0: True, 1: False})
        flags = mixer.overload_snapshot()
        flags[0] = False
        self.assertTrue(mixer.overload_snapshot()[0])
        mixer.process(1, pcm(.95, -.95))
        mixer.process(0, pcm(.2, .2))
        self.assertEqual(mixer.overload_snapshot(), {0: False, 1: True})
        mixer.process(1, b"")
        self.assertEqual(mixer.overload_snapshot(), {0: False, 1: False})
        mixer.process(0, pcm(1., 1.))
        preset = mixer.snapshot()
        mixer.reset_diagnostics(0)
        self.assertEqual(mixer.overload_snapshot(), {0: False, 1: False})
        self.assertEqual(mixer.snapshot(), preset)

    def test_health_flags_snapshot_tracks_latest_block_and_is_detached(self):
        mixer = VirtualBusMixer(2, ceiling=.8)
        clean = {"overload": False, "invalid_pcm": False}
        self.assertEqual(mixer.health_flags_snapshot(), {0: clean, 1: clean})
        preset = mixer.snapshot()
        mixer.process(0, pcm(float("nan"), .5))
        mixer.process(1, pcm(.9, .25))
        expected = {
            0: {"overload": False, "invalid_pcm": True},
            1: {"overload": True, "invalid_pcm": False},
        }
        self.assertEqual(mixer.health_flags_snapshot(), expected)
        detached = mixer.health_flags_snapshot()
        detached[0]["invalid_pcm"] = False
        detached[1]["overload"] = False
        self.assertEqual(mixer.health_flags_snapshot(), expected)
        mixer.process(0, b"")
        self.assertEqual(mixer.health_flags_snapshot()[0], clean)
        self.assertEqual(mixer.health_flags_snapshot()[1], expected[1])
        mixer.reset_diagnostics(1)
        self.assertEqual(mixer.health_flags_snapshot(), {0: clean, 1: clean})
        self.assertEqual(mixer.snapshot(), preset)

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
