"""Regression: users can select a future source during an active catalog job."""
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "karaoke" / "catalog_window.py"


class CatalogFolderSelectionBusyTests(unittest.TestCase):
    def test_folder_buttons_not_disabled_by_busy_state(self):
        source = SOURCE.read_text(encoding="utf-8")
        action_buttons = source.split("self.action_buttons = (", 1)[1].split(")", 1)[0]
        self.assertNotIn("self.pick_button", action_buttons)
        self.assertNotIn("self.songs_button", action_buttons)
        self.assertIn("self.update_button", action_buttons)

    def test_current_scan_is_not_restarted_on_selection(self):
        source = SOURCE.read_text(encoding="utf-8")
        chooser = source.split("    def _choose_folder(self):", 1)[1].split("    def _copy_choice", 1)[0]
        self.assertNotIn("start_catalog_maintenance(", chooser)
        self.assertIn("self.source = Path(folder)", chooser)
        self.assertIn("self.source_text.set(str(self.source))", chooser)


if __name__ == "__main__":
    unittest.main()
