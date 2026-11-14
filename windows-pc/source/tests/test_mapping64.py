import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from concurrent.futures import Future
from unittest.mock import Mock, patch
from soundfont_fixture import make_font
from karaoke.font_mapping import extended_entries, retained_mapping, refresh_waiting_audio
from karaoke.medley_decks import Decks, preparation_key

class Mapping64Tests(unittest.TestCase):
    def test_only_existing_gm_presets_override_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            p=make_font(Path(d)/'a.sf2');options={'fonts':[{'path':str(p)}]}
            self.assertEqual(extended_entries(options,[10],{'piano':str(p)}),[(10,0,0,0,0,0),(10,-1,-1,-1,0,0)])
            self.assertEqual(extended_entries(options,[10],{'guitar':str(p)}),[(10,-1,-1,-1,0,0)])
            with self.assertRaises(ValueError):extended_entries(options,[10],{'piano':{'path':str(p),'bank':0,'preset':99}})
    def test_retains_preset_mapping_when_font_exists(self):
        value={'path':'a.sf2','bank':0,'preset':0}
        self.assertEqual(retained_mapping({'piano':value},[{'path':'a.sf2'}]),{'piano':value})
        self.assertEqual(retained_mapping({'piano':value},[]),{})
    def test_audio_refresh_keeps_current_song(self):
        app=NS(engine=Mock(),_medley_decks=Mock(),_keyboard_voice=Mock())
        refresh_waiting_audio(app)
        app._medley_decks.discard.assert_called_once_with()
        app._keyboard_voice.close.assert_called_once_with()
        app.engine.close.assert_not_called()
    def test_prepared_deck_rechecks_file_settings_and_melody(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'song.mid';p.write_bytes(b'old')
            item=NS(song_id=1,key=0,speed=100)
            app=NS(settings={'synth_backend':'bass'},engine=object(),melody_var=Mock(),library=Mock())
            app.melody_var.get.return_value=False;app.library.get.return_value={'path':str(p)}
            for change in ('file','settings','melody','path'):
                decks=Decks();audio=Mock();decks.key=preparation_key(app,item,p)
                decks.future=Future();decks.future.set_result((audio,None))
                self.assertTrue(decks.matches(item,app))
                if change=='file':p.write_bytes(b'changed')
                elif change=='settings':app.settings['synth_backend']='windows'
                elif change=='melody':app.melody_var.get.return_value=True
                else:app.library.get.return_value={'path':str(Path(d)/'gone.mid')}
                self.assertIsNone(decks.take(item,app));audio.close.assert_called_once_with();decks.close()

    def test_audio_dialog_save_refreshes_keyboard_and_waiting_deck(self):
        from karaoke.audio_dialog import AudioSettings
        app=NS(settings={},save_settings=Mock(),status_var=Mock(),_medley_decks=Mock(),_keyboard_voice=Mock())
        dialog=NS(app=app,benchmark_busy=lambda:False,collect=lambda:{'fonts':[]},
            mode=NS(get=lambda:'windows'),stop_preview=Mock(),destroy=Mock())
        AudioSettings.save(dialog)
        app._keyboard_voice.close.assert_called_once_with()
        app._medley_decks.discard.assert_called_once_with()
        dialog.destroy.assert_called_once_with()
