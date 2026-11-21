"""Regression tests: Windows client area, HiDPI zoom and no clipped pages."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from desktop_ui import fit_zoom


class DesktopLayoutTests(unittest.TestCase):
    def test_laptop_1366x768_does_not_force_120_percent_zoom(self):
        value=fit_zoom(1366,768)
        self.assertAlmostEqual(value,1.0)
        self.assertGreaterEqual(value,0.90)
        self.assertLessEqual(value,1.0)

    def test_maximized_1080p_stays_readable(self):
        value=fit_zoom(1920,1080)
        self.assertGreaterEqual(value,1.10)
        self.assertLessEqual(value,1.20)

    def test_4k_desktop_zoom_capped(self):
        self.assertEqual(fit_zoom(2560,1440),1.20)

    def test_small_window_never_enlarges_beyond_available_area(self):
        self.assertEqual(fit_zoom(930,620),0.90)
        self.assertEqual(fit_zoom(800,600),0.90)

    def test_fit_monotonic_and_stable_across_resize(self):
        sizes=[(960,620),(1200,750),(1366,768),(1600,900),(1920,1080)]
        # A taller and wider physical work area permits at least as much zoom
        self.assertEqual(fit_zoom(800,600),fit_zoom(930,620))
        self.assertLess(fit_zoom(1200,750),fit_zoom(1600,900))
        self.assertEqual(fit_zoom(1366,768),fit_zoom(1366,768))

    def test_no_window_level_scroll_and_all_views_have_contained_fallback(self):
        css=(Path(__file__).resolve().parents[1]/"web"/"style.css").read_text(
            encoding="utf-8")
        native=(Path(__file__).resolve().parents[1]/"desktop_ui.py").read_text(
            encoding="utf-8")
        for needle in (
            "v0.1.30: desktop viewport containment",
            ".app{width:100%;overflow:hidden}",
            "#view-lyrics.is-visible",
            "#view-import.is-visible",
            "#view-build.is-visible",
            "overflow-y:auto",
            "scrollbar-width:none",
            "@media(max-width:900px)",
        ):
            self.assertIn(needle,css)
        self.assertIn("QTimer.singleShot(0,self._fit_screen)",native)
        self.assertIn("Ctrl+0",native)
        self.assertIn("self._manual_zoom=True",native)

    def test_responsive_typography_keeps_ui_labels_readable(self):
        css=(Path(__file__).resolve().parents[1]/"web"/"style.css").read_text(
            encoding="utf-8")
        for needle in (
            "--studio-ui-text:clamp(13px",
            "--studio-ui-small:clamp(12px",
            "--studio-ui-button:clamp(12px",
            ".nav-link>span:last-child",
            ".panel-head,.modal-head{flex-wrap:wrap}",
            ".toolbar button,.folder-actions button,.dialog-actions button",
            "overflow-wrap:anywhere",
            "@media(max-width:600px)",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle,css)
        self.assertGreaterEqual(fit_zoom(1366,768),1.0)
        self.assertGreaterEqual(fit_zoom(960,620),0.90)


if __name__=="__main__":
    unittest.main()
