"""Windows PC must remain independent of the X-Stage Karaoke Online service."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class OfflineOnlyPCRegression(unittest.TestCase):
    def test_online_menu_and_cloud_entrypoints_absent(self):
        for filename in ('ui.py', 'classic.py', 'context_menu.py'):
            source = (ROOT / 'karaoke' / filename).read_text(encoding='utf-8')
            for token in ('web_online_data', 'cloud_backup_data', 'X-Stage Karaoke Online',
                          'online_wizard', 'google_account_ui', 'google_drive_sync'):
                self.assertNotIn(token, source, (filename, token))

    def test_pc_keeps_local_songstudio_integration(self):
        source = (ROOT / 'karaoke' / 'classic.py').read_text(encoding='utf-8')
        self.assertIn('connect_songstudio_pc_library', source)
        self.assertIn('def restore_data(self):', source)
        self.assertTrue((ROOT / 'karaoke' / 'pc_xstagesong.py').is_file())

    def test_windows_build_does_not_bundle_web_or_oauth(self):
        build = (ROOT / 'build.ps1').read_text(encoding='utf-8-sig')
        self.assertNotIn("'google-oauth-client.json.example'", build)
        self.assertNotIn("'Convert-Web-Assets.cmd'", build)
        self.assertNotIn("'web'", build)

if __name__ == '__main__':
    unittest.main()
