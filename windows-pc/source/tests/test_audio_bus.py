"""P1 bus-routing contract tests (hardware-independent)."""
import unittest

from karaoke.audio_bus import AudioBusPlan, AudioBusRoute, plan_from_mapping, stereo_plan, performance_plan, DrumKeyRoute, PerformanceBusPlan, MidiBusDispatcher


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


class MidiBusDispatcherTests(unittest.TestCase):
    def test_drum_note_on_off_and_velocity_zero_share_bus(self):
        sent = {bus: [] for bus in range(4)}
        plan = performance_plan(4, {ch: 0 for ch in range(16)}, {36: 2})
        dispatcher = MidiBusDispatcher(plan, {bus: sent[bus].append for bus in sent})
        for message in (bytes([0x99, 36, 100]), bytes([0x89, 36, 0]),
                        bytes([0x99, 36, 0])):
            self.assertEqual(dispatcher.dispatch(message), 2)
        self.assertEqual(len(sent[2]), 3)
        self.assertEqual(dispatcher.dispatch(bytes([0x90, 36, 100])), 0)

    def test_program_change_and_control_change_route_by_channel(self):
        sent = {bus: [] for bus in range(4)}
        plan = performance_plan(4, {ch: ch % 4 for ch in range(16)})
        dispatcher = MidiBusDispatcher(plan, {bus: sent[bus].append for bus in sent})
        self.assertEqual(dispatcher.dispatch(bytes([0xC3, 5])), 3)
        self.assertEqual(dispatcher.dispatch(bytes([0xB2, 7, 100])), 2)

    def test_drum_state_broadcasts_to_every_override_bus_without_duplicate(self):
        sent = {bus: [] for bus in range(4)}
        plan = performance_plan(4, {ch: 0 for ch in range(16)},
                                {36: 2, 38: 3, 42: 2})
        dispatcher = MidiBusDispatcher(plan, {bus: sent[bus].append for bus in sent})
        for data in (bytes([0xC9, 8]), bytes([0xB9, 7, 95]),
                     bytes([0xB9, 123, 0]), bytes([0xE9, 0, 64])):
            self.assertEqual(dispatcher.dispatch(data), 0)
            for bus in (0, 2, 3):
                self.assertEqual(sent[bus][-1], data)
        self.assertEqual([len(sent[bus]) for bus in range(4)], [4, 0, 4, 4])
        self.assertEqual(dispatcher.dispatch(bytes([0x99, 36, 100])), 2)
        self.assertEqual([len(sent[bus]) for bus in range(4)], [4, 0, 5, 4])
        self.assertEqual(dispatcher.dispatch(bytes([0x89, 36, 0])), 2)

    def test_rejects_malformed_messages_and_incomplete_sinks(self):
        plan = performance_plan(4)
        with self.assertRaises(ValueError):
            MidiBusDispatcher(plan, {0: lambda _: None})
        dispatcher = MidiBusDispatcher(plan, {bus: lambda _: None for bus in range(4)})
        for message in (b'', bytes([0xF0, 1]), bytes([0x90, 60]),
                        bytes([0xC0, 1, 2]), bytes([0x90, 128, 10])):
            with self.subTest(message=message), self.assertRaises(ValueError):
                dispatcher.dispatch(message)


if __name__ == '__main__':
    unittest.main()
