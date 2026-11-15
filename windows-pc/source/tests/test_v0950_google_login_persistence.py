"""Windows Google sign-in persistence: no tokens in plain settings or releases."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from karaoke import google_session as sessions


class SessionStorageTests(unittest.TestCase):
    def test_save_restore_for_same_google_account_and_oauth_client(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)
            # The symmetric stand-in is only a test; production requires Windows DPAPI.
            def fake_protect(payload, *, decrypt=False):
                return payload[::-1]
            with patch.object(sessions,'_protect',side_effect=fake_protect):
                self.assertTrue(sessions.save_session(p,'x.apps.googleusercontent.com',
                                                     'user@gmail.com','refresh-private-abc'))
                raw=sessions.session_path(p).read_bytes()
                self.assertNotIn(b'refresh-private-abc',raw)
                self.assertNotIn(b'user@gmail.com',raw)
                self.assertEqual(sessions.load_session(p)['client_id'],'x.apps.googleusercontent.com')
                def get(url,token='',method='GET',body=None,**kwargs):
                    if url.endswith('/token'):
                        self.assertIn(b'refresh-private-abc',body)
                        return 200,{},json.dumps({'access_token':'short-lived-new-token','expires_in':3600}).encode()
                    return 200,{},json.dumps({'email':'user@gmail.com','email_verified':True}).encode()
                with patch('karaoke.google_drive_sync.load_client',return_value=('x.apps.googleusercontent.com','')),\
                     patch('karaoke.google_drive_sync._request',side_effect=get):
                    result=sessions.restore_session(p,p)
                    self.assertEqual(result[0],'short-lived-new-token')
                    self.assertEqual(result[1],'user@gmail.com')
                    self.assertEqual(result[2],'refresh-private-abc')
                sessions.forget_session(p)
                self.assertFalse(sessions.has_saved_session(p))
                self.assertIsNone(sessions.restore_session(p,p))

    def test_invalid_google_grant_invalidates_saved_session(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)
            with patch.object(sessions,'_protect',side_effect=lambda x,**kw:x[::-1]):
                sessions.save_session(p,'x.apps.googleusercontent.com','user@gmail.com','refresh-token')
                with patch('karaoke.google_drive_sync.load_client',return_value=('x.apps.googleusercontent.com','')),\
                     patch('karaoke.google_drive_sync._request',side_effect=RuntimeError('invalid_grant')):
                    with self.assertRaisesRegex(RuntimeError,'invalid_grant'):
                        sessions.restore_session(p,p)
                self.assertFalse(sessions.has_saved_session(p))

    def test_offline_network_does_not_erase_session(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)
            with patch.object(sessions,'_protect',side_effect=lambda x,**kw:x[::-1]):
                sessions.save_session(p,'x.apps.googleusercontent.com','user@gmail.com','refresh-token')
                with patch('karaoke.google_drive_sync.load_client',return_value=('x.apps.googleusercontent.com','')),\
                     patch('karaoke.google_drive_sync._request',side_effect=RuntimeError('timeout')):
                    with self.assertRaisesRegex(RuntimeError,'timeout'):
                        sessions.restore_session(p,p)
                self.assertTrue(sessions.has_saved_session(p))

    def test_mismatched_desktop_client_cannot_use_stored_refresh_token(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)
            with patch.object(sessions,'_protect',side_effect=lambda x,**kw:x[::-1]):
                sessions.save_session(p,'old.apps.googleusercontent.com','user@gmail.com','secret')
                with patch('karaoke.google_drive_sync.load_client',return_value=('other.apps.googleusercontent.com','')):
                    with self.assertRaisesRegex(RuntimeError,'OAuth Client'):
                        sessions.restore_session(p,p)
                self.assertTrue(sessions.has_saved_session(p))


if __name__=='__main__': unittest.main()
