import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from karaoke.font_mapping import apply_mapping

class MappingApplyTests(unittest.TestCase):
    def setUp(self):
        patcher=patch('karaoke.soundfont.inspect_font',return_value={'presets':[(0,0,'piano')]})
        patcher.start();self.addCleanup(patcher.stop)

    def app(self):
        return SimpleNamespace(settings={'instrument_fonts': {'piano':'a.sf2'}},
            save_settings=Mock(), _medley_decks=Mock(), _keyboard_voice=Mock(), engine=Mock())
    def test_save_invalidates_waiting_audio_only(self):
        app=self.app()
        apply_mapping(app, {'guitar':'b.sf2'}, [{'path':'a.sf2'}, {'path':'b.sf2'}])
        self.assertEqual(app.settings['instrument_fonts'], {'guitar':'b.sf2'})
        app._medley_decks.discard.assert_called_once_with()
        app._medley_decks.close.assert_not_called()
        app._keyboard_voice.close.assert_called_once_with()
        app.engine.close.assert_not_called()
    def test_invalid_selection_keeps_settings_and_audio(self):
        app=self.app()
        with self.assertRaises(ValueError):apply_mapping(app, {'guitar':'gone.sf2'}, [{'path':'a.sf2'}])
        self.assertEqual(app.settings['instrument_fonts'], {'piano':'a.sf2'})
        app.save_settings.assert_not_called()
        app._medley_decks.discard.assert_not_called()
        app._keyboard_voice.close.assert_not_called()
    def test_save_failure_restores_settings_without_stopping_audio(self):
        app=self.app();app.save_settings.side_effect=OSError('disk full')
        with self.assertRaises(OSError):apply_mapping(app, {}, [{'path':'a.sf2'}])
        self.assertEqual(app.settings['instrument_fonts'], {'piano':'a.sf2'})
        app._medley_decks.discard.assert_not_called()
        app._keyboard_voice.close.assert_not_called()
