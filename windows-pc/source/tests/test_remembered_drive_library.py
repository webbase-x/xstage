import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from karaoke.library_setup import drive_library, remember_drive_library, remembered_drive_root, prepare_online

class RememberedDriveTests(unittest.TestCase):
    def test_one_selection_reuses_named_library_and_nested_songs(self):
        with tempfile.TemporaryDirectory() as temp:
            mount = Path(temp) / "My Drive"
            root = mount / "Custom" / "XStageKaraoke"
            nested = root / "SONGS" / "MIDI"
            nested.mkdir(parents=True)
            app = SimpleNamespace(settings={}, save_settings=Mock())
            with patch("karaoke.library_setup.drive_roots", return_value=[mount]):
                self.assertEqual(remember_drive_library(app, nested)[1], root)
                self.assertEqual(remembered_drive_root(app.settings), str(root))
                self.assertEqual(drive_library(root), (mount, root))
                self.assertEqual(prepare_online(nested, mount, root.name, target_root=root), root)
                self.assertTrue((root / "DB").is_dir())
                self.assertFalse((mount / root.name).exists())
                remember_drive_library(app, root)
                app.save_settings.assert_called_once()
            with patch("karaoke.library_setup.drive_roots", return_value=[]):
                with self.assertRaises(ValueError):
                    drive_library(remembered_drive_root(app.settings))
                self.assertEqual(remembered_drive_root(app.settings), str(root))

    def test_existing_active_and_pending_root_migration(self):
        self.assertEqual(remembered_drive_root({"shared_drive_root":"G:/old"}), "G:/old")
        self.assertEqual(remembered_drive_root({"shared_drive_root":"G:/old",
            "pending_online_master":{"root":"H:/new"}}), "H:/new")
        self.assertEqual(remembered_drive_root({"catalog_drive_root":"G:/chosen",
            "shared_drive_root":"G:/old"}), "G:/chosen")
