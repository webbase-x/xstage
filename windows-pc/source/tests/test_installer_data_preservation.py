"""Installer regression: song and SQLite data must not be deleted on upgrade."""
from pathlib import Path
import unittest


INSTALLER = Path(__file__).resolve().parents[2] / 'installer' / 'XStageKaraoke.iss'


class InstallerDataPreservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = INSTALLER.read_text(encoding='utf-8')

    def test_installed_database_is_default(self):
        self.assertIn('Name: "{app}\\data"; Permissions: users-modify; Flags: uninsneveruninstall', self.script)
        self.assertNotIn('Parameters: "--data-dir', self.script)

    def test_song_drop_folders_are_persistent(self):
        for name in ('Songs', 'Songs\\MIDI', 'Songs\\MIDI\\NCN',
                     'Songs\\MIDI\\EMK', 'Songs\\MP3', 'Songs\\VIDEO'):
            with self.subTest(name=name):
                self.assertIn('Name: "{app}\\' + name + '"', self.script)
        self.assertIn('Name: "{app}\\Songs"; Permissions: users-modify; Flags: uninsneveruninstall', self.script)

    def test_installer_does_not_ship_or_delete_song_database(self):
        self.assertNotIn('Flags: deleteafterinstall', self.script)
        self.assertNotIn('[UninstallDelete]', self.script)
        self.assertNotIn('Source: "..\\source\\dist\\XStageKaraoke\\data', self.script)


if __name__ == '__main__':
    unittest.main()
