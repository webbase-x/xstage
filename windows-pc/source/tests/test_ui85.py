import logging
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock
from karaoke.eq_ui_state import resize_size
from karaoke.log_viewer import read_tail,log_directory
from karaoke.runtime_diagnostics import CategoryFilter

class UI85Tests(unittest.TestCase):
    def test_resize_bounds_and_control_space(self):
        self.assertEqual(resize_size((900,700),(1500,900),500),(900,700))
        self.assertEqual(resize_size((10,10),(1500,900),500),(760,500))
        self.assertEqual(resize_size((2000,2000),(600,350),500),(600,350))
    def test_log_tail_bounded_and_unicode(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'XStageKaraoke.log'
            p.write_text('เก่า\n'*100+'ล่าสุด\n',encoding='utf-8')
            text=read_tail(p,60)
            self.assertIn('ล่าสุด',text)
            self.assertNotIn('\ufffd',text)
            self.assertLess(len(text),150)
    def test_log_directory_uses_actual_diagnostics(self):
        self.assertEqual(log_directory(NS(_diagnostics=NS(directory=Path('/chosen')))),Path('/chosen'))
    def test_categories(self):
        for module,message,expected in [('audio_dialog','open','SOUNDFONT'),('graphic_eq_ui','set','EQ'),('ui','Cannot load song','PLAYER'),('remote_server','start','REMOTE')]:
            record=logging.LogRecord('root',logging.INFO,module+'.py',1,message,(),None)
            CategoryFilter().filter(record)
            self.assertEqual(record.category,expected)
    def test_stage_escape_keeps_borderless(self):
        from karaoke.ui import KaraokeApp
        stage=Mock();app=NS(stage=stage,stage_fullscreen=True)
        KaraokeApp.exit_stage_fullscreen(app)
        stage.attributes.assert_called_once_with('-fullscreen',False)
        stage.overrideredirect.assert_called_once_with(True)
        self.assertFalse(app.stage_fullscreen)
