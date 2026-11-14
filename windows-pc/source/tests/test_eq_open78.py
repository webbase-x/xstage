import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from karaoke import graphic_eq_ui,eq_ui

class OpenEQTests(unittest.TestCase):
    def test_first_open_maps_and_lifts_without_second_click(self):
        app=SimpleNamespace();window=Mock();window.winfo_exists.return_value=True
        with patch.object(graphic_eq_ui,'GraphicEQ',return_value=window) as create:
            self.assertIs(eq_ui.open_window(app),window)
            create.assert_called_once_with(app);window.show.assert_called_once()
            self.assertIs(app._eq_window,app._graphic_eq_window)
            self.assertIs(graphic_eq_ui.open_window(app),window)
            create.assert_called_once();self.assertEqual(window.show.call_count,2)
    def test_closed_window_recreated_and_shown(self):
        old=Mock();old.winfo_exists.return_value=False;new=Mock()
        app=SimpleNamespace(_eq_window=old)
        with patch.object(graphic_eq_ui,'GraphicEQ',return_value=new):
            self.assertIs(eq_ui.open_window(app),new);new.show.assert_called_once()
