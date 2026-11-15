"""Regression: prefer a Desktop client from current or known old X-Stage folders.
No account access, network calls, or real OAuth JSON is used in these tests.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from karaoke.google_drive_sync import load_client, find_client_file


def write_client(path, *, kind='installed', ident='desktop.apps.googleusercontent.com'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({kind: {'client_id': ident, 'client_secret': 'FAKE-TEST-VALUE'}}), encoding='utf-8')


class LegacyOAuthDiscoveryTests(unittest.TestCase):
    def test_old_home_data_folder_is_discovered(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            old = root / 'Data' / 'client_secret_old.apps.googleusercontent.com.json'
            write_client(old)
            self.assertEqual(find_client_file(root, root / 'new' / 'Data'), old)
            self.assertEqual(load_client(root, root / 'new' / 'Data')[0], 'desktop.apps.googleusercontent.com')

    def test_current_data_takes_precedence(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            old = root / 'Data' / 'google-oauth-client.json'
            current = root / 'new' / 'Data' / 'google-oauth-client.json'
            write_client(old, ident='old.apps.googleusercontent.com')
            write_client(current, ident='new.apps.googleusercontent.com')
            self.assertEqual(load_client(root, current.parent)[0], 'new.apps.googleusercontent.com')

    def test_web_only_client_cannot_be_silently_accepted(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            write_client(root / 'google-oauth-client.json', kind='web')
            with self.assertRaisesRegex(ValueError, 'Web Client'):
                load_client(root, root)

    def test_user_specified_json_path(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            file = root / 'old_config' / 'client.json'
            write_client(file)
            with patch.dict(os.environ, {'XSTAGE_GOOGLE_OAUTH_JSON': str(file)}):
                self.assertEqual(find_client_file(root / 'new', root / 'new' / 'Data'), file)
                self.assertEqual(load_client(root / 'new', root / 'new' / 'Data')[0], 'desktop.apps.googleusercontent.com')

    def test_missing_config_fails_without_leaking_credentials(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(ValueError, 'Desktop Client'):
                    load_client(root, root)

    def test_unreadable_json_reports_error_without_printing_contents(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            (root / 'google-oauth-client.json').write_text('{not json')
            with self.assertRaisesRegex(ValueError, 'อ่านไฟล์ OAuth JSON'):
                load_client(root, root)


if __name__ == '__main__':
    unittest.main()
