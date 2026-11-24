"""Regression: eight direct categories without duplicate labelled actions."""
import ast
from pathlib import Path
import unittest


class ContextCategoryTests(unittest.TestCase):
    def test_categories_and_existing_commands(self):
        source = (Path(__file__).resolve().parents[1] / "karaoke" / "context_menu.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        roots = [n.args[1].value for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "submenu" and isinstance(n.args[0], ast.Name)
                 and n.args[0].id == "menu"]
        self.assertEqual(roots, [
            "1. เพลงและคิว", "2. ควบคุมการเล่น", "3. ระบบเสียงและมิกเซอร์",
            "4. MIDI และ SoundFont", "5. เนื้อร้อง ภาพ และจอแสดงผล",
            "6. เครื่องมือแสดงสด", "7. ตั้งค่าและจัดการระบบ", "8. โปรแกรมและการออก"])
        labels = [n.args[1].value for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id == "command" and isinstance(n.args[1], ast.Constant)]
        self.assertEqual(len(labels), len(set(labels)))
        for callback in ("app.manage_songs", "app.open_mixer", "app.stage_settings",
                         "app.remote_window", "app.medley_window", "app.capabilities"):
            self.assertIn(callback, source)


if __name__ == "__main__":
    unittest.main()
