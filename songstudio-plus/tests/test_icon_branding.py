"""Regression tests for the Song Studio Pro (not Plus) Windows icon."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None


@unittest.skipUnless(Image is not None, "Pillow is installed in the Windows build job")
class StudioProIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).resolve().parents[1] / "make_icon.py"
        spec = importlib.util.spec_from_file_location("studio_pro_icon_generator", source)
        cls.generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.generator)

    def test_raster_has_pro_badge_not_legacy_plus(self):
        icon = self.generator.render_icon()
        self.assertEqual(icon.size, (512, 512))
        # Inside the rounded badge, far enough left to avoid the PRO glyph.
        self.assertEqual(icon.getpixel((355, 120))[:3], self.generator.BADGE_FILL)
        # Ensure the PRO lettering is actually painted in its designated color.
        badge = icon.crop((362, 84, 464, 143)).convert("RGB")
        pro_ink = sum(pixel == self.generator.BADGE_TEXT for pixel in badge.getdata())
        self.assertGreater(pro_ink, 90, "PRO text must be present in the Windows icon")

    def test_multiresolution_ico_contains_all_windows_sizes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = self.generator.save_icon(Path(directory) / "test-pro.ico")
            with Image.open(output) as icon:
                self.assertTrue({(16, 16), (24, 24), (32, 32),
                                 (48, 48), (64, 64), (128, 128),
                                 (256, 256)} <= icon.ico.sizes())


if __name__ == "__main__":
    unittest.main()
