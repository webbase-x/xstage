import unittest
from pathlib import Path
from karaoke.remote_page import PAGE
from karaoke.tooltip import attach, tooltip_geometry, Tooltip

class Ui095Tests(unittest.TestCase):
    def test_mobile_page_has_large_touch_targets_and_stable_status(self):
        self.assertIn('min-height:50px', PAGE)
        self.assertIn('min-height:52px', PAGE)
        self.assertIn('min-height:34px', PAGE)
        self.assertIn('id="reconnect"', PAGE)
        self.assertIn('reconnectNow', PAGE)
        self.assertIn('pollController', PAGE)
        self.assertIn('pollGeneration', PAGE)
        self.assertIn("e.name==='AbortError'", PAGE)
        self.assertIn('margin:4px 16px', PAGE)
        self.assertIn('env(safe-area-inset-left)', PAGE)
    def test_tooltip_helper_is_importable(self):
        self.assertTrue(callable(attach))

    def test_tooltip_geometry_clamps_right_and_flips_above_bottom(self):
        x, y = tooltip_geometry(1880, 1060, 40, 30, 220, 48, 1920, 1080)
        self.assertLessEqual(x + 220, 1912)
        self.assertGreaterEqual(x, 8)
        self.assertLess(y, 1060)

    def test_tooltip_destroy_cancels_pending_timer(self):
        class FakeWidget:
            def __init__(self):
                self.cancelled=[]
            def bind(self, event, handler, add=None):
                pass
            def after_cancel(self, timer):
                self.cancelled.append(timer)
        widget=FakeWidget(); tooltip=Tooltip(widget, 'x'); tooltip.after_id='timer-1'; tooltip._destroy()
        self.assertEqual(widget.cancelled, ['timer-1'])
        self.assertIsNone(tooltip.after_id)

    def test_static_player_reads_private_web_catalog_without_old_backup(self):
        root=Path(__file__).parents[1]/'web'
        app=(root/'app.js').read_text(encoding='utf-8')
        html=(root/'index.html').read_text(encoding='utf-8')
        self.assertIn('XStageWeb', app)
        self.assertIn('drive.file', app)
        self.assertIn('current.json', app)
        self.assertIn('catalogFileId', app)
        self.assertIn('song.audio.fileId', app)
        self.assertIn('song.lyrics.fileId', app)
        self.assertIn('URL.revokeObjectURL', app)
        self.assertIn("id=\"lyrics\"", html)
        self.assertIn("id=\"logout\"", html)
        self.assertNotIn('web-manifest.json', app)
        self.assertNotIn("'XStageKaraoke'", app)

if __name__=='__main__': unittest.main()
