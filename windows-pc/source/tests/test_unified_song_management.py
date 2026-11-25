"""Regression for the five shared song management entry points."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from karaoke import catalog_window, duplicate_dialog, shared_catalog_builder_ui
from karaoke import drive_online_catalog_ui, shared_drive_sync_ui


class UnifiedSongManagementTests(unittest.TestCase):
    def test_all_entry_points_reuse_one_manager(self):
        app = SimpleNamespace()
        manager = Mock()
        manager.window.winfo_exists.return_value = True
        with patch.object(catalog_window, "CatalogWindow", return_value=manager) as create:
            catalog_window.open_song_management(app)
            shared_catalog_builder_ui.open_builder(app, initial_root="G:/Songs")
            drive_online_catalog_ui.open_shared_drive_catalog(app)
            shared_drive_sync_ui.open_drive_push(app)
            duplicate_dialog.open_exact_duplicates(app)
            create.assert_called_once_with(app)
        self.assertEqual([c.args for c in manager.show_page.call_args_list],
            [("local", None), ("build", "G:/Songs"), ("drive", None),
             ("sync", None), ("duplicates", None)])

    def test_destroyed_manager_is_recreated(self):
        previous = Mock()
        previous.window.winfo_exists.return_value = False
        app = SimpleNamespace(catalog_window=previous)
        with patch.object(catalog_window, "CatalogWindow") as create:
            catalog_window.open_song_management(app, "drive")
            create.assert_called_once_with(app)
            create.return_value.show_page.assert_called_once_with("drive", None)


if __name__ == "__main__":
    unittest.main()
