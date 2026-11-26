"""Regression checks for consistent X-Stage Karaoke PC branding and upgrade safety."""
from pathlib import Path
import re
import unittest
from karaoke import APP_NAME

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]

class PcBrandingRegression(unittest.TestCase):
    def test_public_pc_name(self):
        self.assertEqual(APP_NAME, 'X-Stage Karaoke PC')
        info = (ROOT / 'version_info.txt').read_text(encoding='utf-8')
        for field in ('FileDescription', 'ProductName'):
            self.assertIn(f"StringStruct('{field}', 'X-Stage Karaoke PC')", info)

    def test_ui_and_installer_names(self):
        for name in ('ui.py', 'classic.py', 'performer.py', 'remote_page.py'):
            source = (ROOT / 'karaoke' / name).read_text(encoding='utf-8')
            self.assertIsNone(re.search(r'X-Stage Karaoke(?! PC| Online)', source), name)
        self.assertIn('X-STAGE KARAOKE PC', (ROOT / 'karaoke/remote_page.py').read_text(encoding='utf-8'))
        # Source-only distributions do not include the repository's Inno wrapper.
        installer_path = REPO / 'windows-pc/installer/XStageKaraoke.iss'
        if installer_path.is_file():
            installer = installer_path.read_text(encoding='utf-8')
            self.assertIn('AppName=X-Stage Karaoke PC', installer)
            self.assertIn('OutputBaseFilename=X-StageKaraoke', installer)
            self.assertIn(r'DefaultDirName={autopf}\X-Stage\Karaoke', installer)
            self.assertIn('UsePreviousAppDir=yes', installer)
            self.assertIn('DisableDirPage=auto', installer)
            self.assertIn('PrivilegesRequired=admin', installer)
            self.assertIn('Uninstallable=yes', installer)
            self.assertIn('#define AppExe "X-StageKaraoke.exe"', installer)
            self.assertIn('DestName: "{#AppExe}"', installer)
            self.assertIn(r'DestDir: "{app}\_internal"', installer)
            self.assertIn(r'DestDir: "{app}"', installer)
            self.assertIn(r'Name: "{app}\data"; Permissions: users-modify; Flags: uninsneveruninstall', installer)
            self.assertNotIn('Parameters: "--data-dir', installer)
            # No blanket dist/* copy or scripts that create Source/ on users' PCs.
            self.assertNotIn(r'DestDir: "{tmp}\\xstage-', installer)
            self.assertNotIn('install_to_D.ps1', installer)
            self.assertNotIn(r'DestDir: "{app}\App"', installer)
            self.assertIn(r'Filename: "{app}\{#AppExe}"', installer)
            self.assertNotIn(r'DestDir: "{app}\\Source"', installer)
            self.assertNotIn(r'dist\\XStageKaraoke\\*"', installer)
        updater_path = REPO / 'windows-pc/Check-Update.ps1'
        if updater_path.is_file():
            updater = updater_path.read_text(encoding='utf-8-sig')
            self.assertIn('X-Stage-Karaoke-PC-Windows-v', updater)
        self.assertIn('X-Stage-Karaoke-PC-Windows-v', (ROOT / 'karaoke/program_updates.py').read_text(encoding='utf-8'))

    def test_keep_legacy_binary_and_data_paths_for_existing_installations(self):
        installer = (ROOT / 'install_to_D.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('XStageKaraoke.exe', installer)
        self.assertIn('X-Stage Karaoke PC.lnk', installer)
        self.assertIn('Start-Karaoke.cmd', installer)
        safety = (ROOT / 'tools/Installer-Safety.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('X-Stage Karaoke PC.cmd', safety)
        self.assertIn('X-Stage Karaoke PC.lnk', safety)
        self.assertIn('D:\\newKaraoke\\Karaoke', installer)

if __name__ == '__main__':
    unittest.main()
