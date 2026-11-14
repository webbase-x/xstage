"""Regression coverage for separate Google Login home, verified profile and secure image.

No live Google authentication or real OAuth configuration is used.
"""
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from karaoke.google_account_ui import safe_profile_picture, fetch_google_profile, display_identity


class ProfileAndLoginTests(unittest.TestCase):
    def test_only_verified_google_identity_is_accepted(self):
        self.assertEqual(display_identity({'email':'real@gmail.com','name':'Known Name'},'real@gmail.com'),'Known Name')
        self.assertEqual(display_identity({'email':'other@gmail.com','name':'Wrong'},'real@gmail.com'),'real@gmail.com')
        self.assertEqual(display_identity({},'real@gmail.com'),'real@gmail.com')

    def test_untrusted_or_http_picture_urls_are_rejected_without_network(self):
        opener=Mock()
        for url in ('http://lh3.googleusercontent.com/a/b','https://evil.example/avatar.png',
                    'https://googleusercontent.com.evil.org/a','file:///etc/passwd'):
            self.assertIsNone(safe_profile_picture(url,opener=opener))
        opener.assert_not_called()

    def test_picture_limit_and_image_type(self):
        class Reply:
            headers={'Content-Type':'image/png'}
            def geturl(self): return 'https://lh3.googleusercontent.com/a'
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def read(self,n):return b'x'* (256*1024+1)
        self.assertIsNone(safe_profile_picture('https://lh3.googleusercontent.com/a',opener=lambda *a,**k:Reply()))
        class Txt(Reply):headers={'Content-Type':'text/html'}
        self.assertIsNone(safe_profile_picture('https://lh3.googleusercontent.com/a',opener=lambda *a,**k:Txt()))

    def test_profile_is_not_used_without_verified_email(self):
        def data(profile):return (200,{},__import__('json').dumps(profile).encode())
        self.assertEqual(fetch_google_profile('test',request=lambda *_args,**kw:data({'email':'a@b.com','email_verified':False,'picture':'https://lh3.googleusercontent.com/x'})),{})
        valid=fetch_google_profile('test',request=lambda *_args,**kw:data({'email':'a@b.com','email_verified':True,'name':'Name','picture':'https://lh3.googleusercontent.com/x'}))
        self.assertEqual(valid['name'],'Name')

    def test_sync_does_not_expose_manual_oauth_picker_or_create_new_token(self):
        from karaoke import ui
        import inspect
        code=inspect.getsource(ui.KaraokeApp.web_online_data)
        self.assertNotIn('เลือก OAuth JSON เดิม',code)
        self.assertNotIn('choose_online_oauth_json_file',code)
        self.assertNotIn("sign_in(client_id, client_secret, cancel)",code)
        self.assertIn('หน้าแรก / จัดการ Google Login',code)


if __name__=='__main__':unittest.main()
