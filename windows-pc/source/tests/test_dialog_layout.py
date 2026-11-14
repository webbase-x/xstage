import unittest
from karaoke.dialog_layout import fit_rect


class DialogGeometryTests(unittest.TestCase):
    def test_large_dialog_stays_inside_laptop_work_area(self):
        area = (0, 0, 1366, 728)
        width, height, x, y = fit_rect(area, (1400, 1100))
        self.assertGreaterEqual(x, area[0])
        self.assertGreaterEqual(y, area[1])
        self.assertLessEqual(x + width, area[2])
        self.assertLessEqual(y + height + 32, area[3])

    def test_secondary_monitor_negative_origin(self):
        width, height, x, y = fit_rect((-1920, 0, 0, 1040), (900, 740))
        self.assertEqual((width, height), (900, 740))
        self.assertGreaterEqual(x, -1920)
        self.assertLessEqual(x + width, 0)

    def test_small_high_dpi_logical_work_area_overrides_minimum(self):
        width, height, x, y = fit_rect((0, 0, 380, 260), (850, 760))
        self.assertLess(width, 380)
        self.assertLess(height, 260)
        self.assertGreater(width, 0)
        self.assertGreater(height, 0)

    def test_compact_form_does_not_fill_desktop(self):
        width, height, _, _ = fit_rect((0, 0, 1920, 1040), (600, 350))
        self.assertEqual((width, height), (600, 350))

    def test_scrollbars_do_not_oscillate_when_both_dimensions_fit(self):
        from karaoke.dialog_layout import viewport_metrics
        self.assertEqual(viewport_metrics(1080, 701, 1073, 700, 15, 15), (1080, 701, False, False))
        self.assertEqual(viewport_metrics(640, 460, 800, 600, 15, 15), (625, 445, True, True))
        self.assertEqual(viewport_metrics(640, 460, 630, 600, 15, 15), (625, 445, True, True))
