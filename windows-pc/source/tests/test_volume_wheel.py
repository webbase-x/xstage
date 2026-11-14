import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from karaoke.volume_wheel import wheel_change
from karaoke.performer import PlaybackApp


class VolumeWheelTests(unittest.TestCase):
    def test_direction_and_multiple_notches(self):
        self.assertEqual(wheel_change(0, 120), (0, 5))
        self.assertEqual(wheel_change(0, -240), (0, -10))
        self.assertEqual(wheel_change(0, button=4), (0, 5))
        self.assertEqual(wheel_change(0, button=5), (0, -5))

    def test_small_deltas_accumulate_without_overshoot(self):
        remainder, change = wheel_change(0, 30)
        self.assertEqual(change, 0)
        remainder, change = wheel_change(remainder, 90)
        self.assertEqual((remainder, change), (0, 5))
        self.assertEqual(wheel_change(60, -60), (0, 0))

    def app(self, volume):
        app = SimpleNamespace(surface=object(), preview=object(), video_frame=object(),
            stage=None, stage_canvas=None, stage_video=None,
            volume_var=Mock(get=lambda: volume), apply_volume=Mock(), show_volume_overlay=Mock())
        return app

    def test_clamp_and_apply_live(self):
        for value, delta, expected in ((98, 120, 100), (2, -120, 0), (75, 120, 80)):
            app = self.app(value)
            self.assertEqual(PlaybackApp.volume_wheel(app, SimpleNamespace(widget=app.preview, delta=delta)), 'break')
            app.volume_var.set.assert_called_once_with(expected)
            app.apply_volume.assert_called_once()
            app.show_volume_overlay.assert_called_once()

    def test_list_wheel_is_not_consumed(self):
        app = self.app(75)
        self.assertIsNone(PlaybackApp.volume_wheel(app, SimpleNamespace(widget=object(), delta=120)))
        app.apply_volume.assert_not_called()
        app.volume_var.set.assert_not_called()

    def test_pointer_target_takes_priority_over_focused_input(self):
        app = self.app(75)
        app.winfo_containing = Mock(return_value=app.preview)
        PlaybackApp.volume_wheel(app, SimpleNamespace(widget=object(), delta=120, x_root=100, y_root=200))
        app.volume_var.set.assert_called_once_with(80)
