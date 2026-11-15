import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock
from karaoke.runtime_diagnostics import Diagnostics
from karaoke.audio_dialog import AudioSettings

class DiagnosticsTests(unittest.TestCase):
    def test_callback_and_thread_errors_are_logged_and_queued(self):
        with TemporaryDirectory() as folder:
            d=Diagnostics(folder)
            try:
                try: raise ValueError('callback fixture')
                except ValueError as e:
                    d.callback_exception(type(e),e,e.__traceback__)
                    d.thread_exception(SimpleNamespace(exc_type=type(e),exc_value=e,exc_traceback=e.__traceback__))
                self.assertEqual(d.errors.qsize(),2)
                text=(Path(folder)/'XStageKaraoke.log').read_text(encoding='utf-8')
                self.assertIn('callback fixture',text)
                self.assertIn('Traceback',text)
            finally:d.close()
            self.assertIn('SESSION_END',(Path(folder)/'XStageKaraoke.log').read_text(encoding='utf-8'))

    def test_stall_dump_once_per_episode_and_bounded(self):
        with TemporaryDirectory() as folder:
            d=Diagnostics(folder,timeout=15)
            try:
                with patch('karaoke.runtime_diagnostics.faulthandler.dump_traceback') as dump:
                    for _ in range(5):
                        d.last_beat=0
                        d.check_stall(20);d.check_stall(30)
                        self.assertTrue(d.stalled)
                        d.check_stall(1)
                        self.assertFalse(d.stalled)
                    self.assertEqual(dump.call_count,3)
            finally:d.close()

    def test_hidden_dialog_releases_only_its_own_grab(self):
        owner=SimpleNamespace(state=lambda:'withdrawn',grab_release=Mock())
        owner.grab_current=lambda:owner
        AudioSettings.release_hidden_grab(owner,SimpleNamespace(widget=owner))
        owner.grab_release.assert_called_once()
        owner.grab_release.reset_mock()
        owner.grab_current=lambda:object()
        AudioSettings.release_hidden_grab(owner,SimpleNamespace(widget=owner))
        owner.grab_release.assert_not_called()

class CategoryCoverageTests(unittest.TestCase):
    def test_core_modules_use_specific_categories(self):
        from karaoke.runtime_diagnostics import CategoryFilter
        for module,category in [('soundfont','SOUNDFONT'),('soundfont_check_ui','SOUNDFONT'),('font_mapping','SOUNDFONT'),('pcm_player','PLAYER'),('medley_decks','PLAYER'),('remote','REMOTE')]:
            with self.subTest(module=module):
                record=logging.LogRecord('root',logging.ERROR,module+'.py',1,'fixture',(),None)
                CategoryFilter().filter(record)
                self.assertEqual(record.category,category)
