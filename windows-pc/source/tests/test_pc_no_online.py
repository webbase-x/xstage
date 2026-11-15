"""Windows PC must remain independent of the X-Stage Karaoke Online service."""
from pathlib import Path
import ast
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

    def test_no_remaining_runtime_import_of_retired_cloud_modules(self):
        removed = {
            'cloud_sync', 'drive_storage', 'google_account_ui',
            'google_drive_sync', 'google_session', 'online_eta',
            'online_preflight', 'online_sync_feedback', 'online_wizard',
            'visible_sync', 'web_assets', 'web_drive', 'web_environment',
            'web_resume', 'offline_generator',
        }
        for path in (ROOT / 'karaoke').glob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotIn(node.module.rsplit('.', 1)[-1], removed,
                                     f'{path.name}:{node.lineno}')
                if isinstance(node, ast.Import):
                    for name in node.names:
                        self.assertNotIn(name.name.rsplit('.', 1)[-1], removed,
                                         f'{path.name}:{node.lineno}')

if __name__ == '__main__':
    unittest.main()
