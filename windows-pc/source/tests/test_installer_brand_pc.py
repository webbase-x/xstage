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
        installer = (REPO / 'windows-pc/installer/XStageKaraoke.iss').read_text(encoding='utf-8')
        self.assertIn('AppName=X-Stage Karaoke PC', installer)
        self.assertIn('OutputBaseFilename=X-Stage-Karaoke-PC-Windows-', installer)
        updater = (REPO / 'windows-pc/Check-Update.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('X-Stage-Karaoke-PC-Windows-v', updater)
        self.assertIn('X-Stage-Karaoke-PC-Windows-v', (ROOT / 'karaoke/program_updates.py').read_text(encoding='utf-8'))

    def test_keep_legacy_binary_and_data_paths_for_existing_installations(self):
        installer = (ROOT / 'install_to_D.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('XStageKaraoke.exe', installer)
        self.assertIn('X-Stage Karaoke PC.lnk', installer)
        self.assertIn('Start-Karaoke.cmd', installer)
        self.assertIn('D:\\newKaraoke\\Karaoke', installer)

if __name__ == '__main__':
    unittest.main()
