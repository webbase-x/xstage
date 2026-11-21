"""P1 bus-routing contract tests (hardware-independent)."""
import unittest

from karaoke.audio_bus import AudioBusPlan, AudioBusRoute, plan_from_mapping, stereo_plan, performance_plan, DrumKeyRoute, PerformanceBusPlan


class AudioBusPlanTests(unittest.TestCase):
    def test_stereo_default_keeps_all_sixteen_channels_on_primary_bus(self):
        plan = stereo_plan()
        self.assertEqual(plan.bus_count, 2)
        self.assertEqual([plan.bus_for_channel(ch) for ch in range(16)], [0] * 16)

    def test_four_eight_sixteen_bus_plans(self):
        for count in (4, 8, 16):
            with self.subTest(count=count):
                plan = plan_from_mapping(count, {ch: ch % count for ch in range(16)})
                self.assertEqual([plan.bus_for_channel(ch) for ch in range(16)],
                                 [ch % count for ch in range(16)])

    def test_rejects_invalid_bus_count_missing_duplicate_or_out_of_range(self):
        with self.assertRaises(ValueError):
            plan_from_mapping(3, {ch: 0 for ch in range(16)})
        with self.assertRaises(ValueError):
            plan_from_mapping(4, {0: 0})
        with self.assertRaises(ValueError):
            plan_from_mapping(4, {ch: 4 if ch == 9 else 0 for ch in range(16)})
        with self.assertRaises(ValueError):
            AudioBusPlan(4, tuple(AudioBusRoute(0, 0) for _ in range(16)))
        with self.assertRaises(ValueError):
            stereo_plan().bus_for_channel(16)

    def test_plan_is_immutable(self):
        plan = stereo_plan()
        with self.assertRaises(AttributeError):
            plan.bus_count = 16




class PercussionRoutingTests(unittest.TestCase):
    def test_drum_key_override_does_not_change_melodic_channels(self):
        plan = performance_plan(8, {ch: ch % 8 for ch in range(16)}, {36: 6, 38: 7})
        self.assertEqual(plan.resolve(9, 36).output_bus, 6)
        self.assertEqual(plan.resolve(9, 38).output_bus, 7)
        self.assertEqual(plan.resolve(9, 42).output_bus, 1)
        self.assertEqual(plan.resolve(0, 36).output_bus, 0)
        self.assertEqual(plan.resolve(9).output_bus, 1)

    def test_default_preserves_stereo_primary_bus(self):
        plan = performance_plan()
        self.assertEqual(plan.resolve(9, 36).output_bus, 0)
        self.assertEqual(plan.resolve(15, 60).output_bus, 0)

    def test_rejects_invalid_or_duplicate_drum_notes(self):
        with self.assertRaises(ValueError):
            performance_plan(4, drum_mapping={128: 1})
        with self.assertRaises(ValueError):
            performance_plan(4, drum_mapping={36: 4})
        with self.assertRaises(ValueError):
            performance_plan(4, drum_mapping={36: True})
        with self.assertRaises(ValueError):
            performance_plan(4, drum_mapping=[(36, 1)])
        with self.assertRaises(ValueError):
            PerformanceBusPlan(stereo_plan(), (DrumKeyRoute(36, 1), DrumKeyRoute(36, 0)))
        with self.assertRaises(ValueError):
            performance_plan().resolve(9, -1)


if __name__ == '__main__':
    unittest.main()
