"""Regression: six-category navigation preserves discoverable live commands."""
import ast
from pathlib import Path
import unittest


class SixCategoryMenuTests(unittest.TestCase):
    def test_categories_and_existing_commands(self):
        path = Path(__file__).resolve().parents[1] / "karaoke" / "context_menu.py"
        source = path.read_text(encoding="utf-8")
        ast.parse(source)
        self.assertNotIn("menu.add_separator()\n\n    options = submenu", source,
                         "Do not add an extra root separator after categories")
        for label in (
            "เมนูหลัก · 6 หมวด", "เพลงและคิว", "เสียงและ SoundFont",
            "เนื้อร้องและภาพ", "การควบคุม", "เครื่องมือแสดงสด",
            "ระบบและสถานะ",
        ):
            with self.subTest(label=label):
                self.assertIn(label, source)
        for callback in (
            "app.manage_songs", "app.open_mixer", "app.stage_settings",
            "app.remote_window", "app.medley_window", "app.capabilities",
        ):
            self.assertIn(callback, source)


if __name__ == "__main__":
    unittest.main()
