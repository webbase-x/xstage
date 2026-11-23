"""Windows startup paths must survive Thai profile names and redirected Documents."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import plus_core


class WindowsWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.home = self.base / "Users" / "ครูไพรัช อินควรชุม"
        self.home.mkdir(parents=True)
        self.local = self.home / "AppData" / "Local"
        self.local.mkdir(parents=True)
        self.roaming = self.home / "AppData" / "Roaming"
        self.roaming.mkdir(parents=True)
        self.env = {"LOCALAPPDATA": str(self.local), "APPDATA": str(self.roaming)}

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_documents_uses_existing_windows_appdata_parent(self):
        # Regression: Windows 'Documents' is redirected or absent.
        paths = app.workspace_candidates(
            home=self.home, env=self.env, platform="win32",
            documents=self.home / "OneDrive" / "เอกสาร")
        self.assertEqual(paths[0], self.home / "Music" / "XStageSongPlus")
        self.assertNotIn(self.home / "Documents" / "XStageSongPlus", paths)
        self.assertFalse((self.home / "Documents").exists())
        plus_core.init(paths[0])
        self.assertTrue((paths[0] / "DB" / "xstage_plus.sqlite3").is_file())

    def test_preexisting_database_under_thai_documents_is_not_relocated(self):
        old = self.home / "Documents" / "XStageSongPlus"
        plus_core.init(old)
        paths = app.workspace_candidates(
            home=self.home, env=self.env, platform="win32",
            documents=self.home / "OneDrive" / "เอกสาร")
        self.assertEqual(paths[0], old)
        self.assertTrue((old / "DB" / "xstage_plus.sqlite3").exists())

    def test_redirected_windows_documents_keeps_existing_database(self):
        moved = self.home / "OneDrive" / "เอกสาร" / "XStageSongPlus"
        plus_core.init(moved)
        paths = app.workspace_candidates(
            home=self.home, env=self.env, platform="win32",
            documents=moved.parent)
        self.assertEqual(paths[0], moved)

    def test_unsupported_localappdata_uses_roaming_and_then_home(self):
        paths = app.workspace_candidates(
            home=self.home,
            env={"LOCALAPPDATA": str(self.home / "missing"),
                 "APPDATA": str(self.roaming)},
            platform="win32", documents=None)
        self.assertEqual(paths[0], self.home / "Music" / "XStageSongPlus")
        paths = app.workspace_candidates(
            home=self.home, env={}, platform="win32",
            documents=self.home / "Documents")
        self.assertEqual(paths[0], self.home / "Music" / "XStageSongPlus")

    def test_music_folder_can_be_redirected_and_custom_workspace_selected(self):
        redirected=self.home / "OneDrive" / "Music"
        paths=app.workspace_candidates(
            home=self.home, env=self.env, platform="win32",
            documents=self.home / "Documents", music=redirected)
        self.assertEqual(paths[0], redirected / "XStageSongPlus")
        custom=self.base / "CustomMusic" / "Studio"
        self.assertEqual(app.workspace_candidates(
            home=self.home, env=self.env, platform="win32", music=custom.parent)[0],
            custom.parent / "XStageSongPlus")

    def test_existing_appdata_database_stays_in_use_after_new_default(self):
        old=self.local / "XStageSongPlus"
        plus_core.init(old)
        paths=app.workspace_candidates(
            home=self.home, env=self.env, platform="win32",
            documents=self.home / "Documents")
        self.assertEqual(paths[0], old)
        self.assertEqual(plus_core.db_path(paths[0]), old / "DB" / "xstage_plus.sqlite3")
        self.assertEqual(plus_core.destination_for(paths[0], {"code": 1}, ".mid"),
                         old / "MIDI" / "MID" / "XMID" / "0" / "00000001.xmid")

    def test_workspace_preference_persists_outside_song_database(self):
        chosen=self.base / "Music collection"
        chosen.mkdir()
        with patch.object(app, "workspace_preference_path",
                          return_value=self.local / "XStageSongStudioPro" / "settings.json"):
            saved=app.save_workspace_preference(chosen)
            self.assertEqual(saved,chosen.resolve())
            self.assertEqual(app.chosen_workspace(),chosen.resolve())
        self.assertFalse((chosen / "DB").exists())

    def test_explicit_failed_workspace_shows_error_not_unhandled_exception(self):
        invalid = self.base / "invalid" / "XStageSongPlus"
        with patch.object(app, "State", side_effect=FileNotFoundError(
                2, "The system cannot find the file specified", str(invalid))), \
             patch.object(app, "_startup_failure") as report:
            self.assertEqual(app.main(["--workspace", str(invalid),
                                       "--no-browser"]), 1)
            report.assert_called_once()
            self.assertIn(str(invalid), report.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
