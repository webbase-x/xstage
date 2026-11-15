"""Regression coverage for Windows R7 build gate errors seen on 2026-11-09.

These checks must not require a real Tk display or Google Drive credentials.
"""
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from karaoke.library import SongLibrary
from karaoke.performer import PlaybackApp
from karaoke.shutdown import ShutdownError
from karaoke.web_drive import sync_web_assets
from tests.test_studio import midi_fixture
from tests.test_v0944_web_sync import FakeWebDrive, StubRenderer


class BuildGateR8Tests(unittest.TestCase):
    def test_uninitialized_tk_account_close_failure_still_completes_all_shutdown_layers(self):
        # Tk subclass without tk interpreter: getattr(...) previously infinitely
        # recursed. Account close must also use the guarded shutdown pipeline.
        app = PlaybackApp.__new__(PlaybackApp)
        app.cancel_scan = threading.Event()
        app.tick_after = None
        app.search_after = None
        app.save_settings = Mock()
        app.song_queue = SimpleNamespace(save=Mock())
        app.engine = SimpleNamespace(close=Mock())
        app.destroy = Mock()
        app.show_error = Mock()
        app.remote = None
        app.recorder = None
        app._search_condition = threading.Condition()
        app._keyboard_voice = Mock()
        app._fx_rack = Mock()
        app.system_volume = Mock()
        app.google_account = Mock()
        app.google_account.close.side_effect = OSError('test Google account cleanup')
        with patch('karaoke.medley_decks.cleanup') as medley_cleanup, \
             self.assertLogs(level='ERROR'), self.assertRaises(ShutdownError):
            PlaybackApp.close_app(app)
        app.google_account.close.assert_called_once()
        medley_cleanup.assert_called_once()
        app._keyboard_voice.close.assert_called_once()
        app._fx_rack.close.assert_called_once()
        app.system_volume.close.assert_called_once()
        app.song_queue.save.assert_called_once()
        app.engine.close.assert_called_once()
        app.destroy.assert_called_once()
        self.assertTrue(app._search_stopping)
        self.assertIn('ปิดบัญชี Google', [name for name, _ in app._shutdown_errors])

    def test_verified_final_catalog_emits_expected_publication_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / 'Songs'
            source.mkdir()
            (source / '98101.mid').write_bytes(midi_fixture())
            lib = SongLibrary(base / 'Data' / 'songs.sqlite3')
            lib.add_files([source / '98101.mid'])
            font = base / 'demo.sf2'
            font.write_bytes(b'fixture')
            notices = []
            result = sync_web_assets(
                FakeWebDrive(), lib.path, [source], base / 'native', {}, font,
                base / 'WebAssets', renderer_factory=StubRenderer,
                progress=lambda msg, *args: notices.append(msg),
                first_batch_size=10, batch_size=200, publish_interval=9999,
            )
            self.assertEqual(result['total'], 1)
            self.assertTrue(any('เผยแพร่ฐานเพลงรุ่น' in msg for msg in notices))
            self.assertTrue(any('Catalog ฉบับสมบูรณ์พร้อมเล่น' in msg for msg in notices))


if __name__ == '__main__':
    unittest.main()
