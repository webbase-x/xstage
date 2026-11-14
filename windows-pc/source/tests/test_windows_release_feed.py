"""Offline update feed validation: no GitHub access and no installer download."""
import unittest
from karaoke.program_updates import validate_manifest

class WindowsReleaseFeedTests(unittest.TestCase):
    def setUp(self):
        self.release={
          "version":"1.0.77","build":1077,"available":True,
          "installer_file":"X-Stage-Karaoke-Windows-v1.0.77-build1077.exe",
          "sha256":"a"*64,
          "installer_url":"https://github.com/webbase-x/xstage/releases/download/windows-v1.0.77-build1077/X-Stage-Karaoke-Windows-v1.0.77-build1077.exe"
        }
    def test_accepts_exact_verified_official_release_url(self):
        value=validate_manifest(self.release,"1.0.76",1076)
        self.assertEqual(value["url"],self.release["installer_url"])
        self.assertEqual(value["sha256"],"a"*64)
    def test_rejects_unknown_and_unsafe_download_targets(self):
        for bad in (
          "http://github.com/webbase-x/xstage/releases/download/windows-v1.0.77-build1077/X-Stage-Karaoke-Windows-v1.0.77-build1077.exe",
          "https://github.com.evil.invalid/webbase-x/xstage/releases/download/windows-v1.0.77-build1077/X-Stage-Karaoke-Windows-v1.0.77-build1077.exe",
          "https://github.com/another-owner/xstage/releases/download/windows-v1.0.77-build1077/X-Stage-Karaoke-Windows-v1.0.77-build1077.exe",
          "https://github.com/webbase-x/xstage/releases/download/windows-v1.0.77-build1077/other.exe",
          "https://github.com/webbase-x/xstage/releases/download/windows-v1.0.77-build1077/X-Stage-Karaoke-Windows-v1.0.77-build1077.exe?bypass=1"
        ):
            with self.subTest(url=bad),self.assertRaises(ValueError):
                validate_manifest({**self.release,"installer_url":bad},"1.0.76",1076)
    def test_no_update_when_same_or_older_release(self):
        self.assertIsNone(validate_manifest(self.release,"1.0.77",1077))
        self.assertIsNone(validate_manifest({**self.release,"available":False},"1.0.76",1076))
    def test_legacy_same_origin_feed_remains_supported(self):
        m={**self.release}
        m.pop("installer_url")
        self.assertEqual(validate_manifest(m,"1.0.76",1076)["url"],
            "https://webbase-x.github.io/xstage/downloads/"+m["installer_file"])

if __name__=="__main__":
    unittest.main()
