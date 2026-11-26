"""Preview channel remains separate from stable and rejects untrusted URLs."""
import unittest
from unittest.mock import patch
from karaoke import program_updates as updater


class PreviewUpdate1090Tests(unittest.TestCase):
    def preview(self, **overrides):
        data = dict(channel='preview', platform='windows-x64', available=True,
                    version='1.0.90', build=1090, installer_file='X-StageKaraoke.exe',
                    sha256='a'*64, download_url=updater.DOWNLOADS+'X-StageKaraoke.exe')
        data.update(overrides)
        return data

    def test_old_build_sees_preview_without_promoting_stable(self):
        with patch.object(updater, '_read_feed', side_effect=[{'available': False}, self.preview()]) as read:
            result = updater.check_release('1.0.89', 1089)
        self.assertEqual(result['channel'], 'preview')
        self.assertEqual(result['version'], '1.0.90')
        self.assertEqual([x.args[0] for x in read.call_args_list], [updater.FEED, updater.PREVIEW_FEED])

    def test_same_build_not_offered(self):
        with patch.object(updater, '_read_feed', side_effect=[{'available': False}, self.preview()]):
            self.assertIsNone(updater.check_release('1.0.90', 1090))

    def test_untrusted_preview_url_rejected(self):
        with patch.object(updater, '_read_feed', side_effect=[{'available': False}, self.preview(download_url='https://example.org/X-StageKaraoke.exe')]):
            with self.assertRaises(ValueError):
                updater.check_release('1.0.89', 1089)

    def test_stable_takes_priority(self):
        stable = self.preview()
        with patch.object(updater, '_read_feed', return_value=stable) as read:
            self.assertEqual(updater.check_release('1.0.89', 1089)['channel'], 'stable')
            read.assert_called_once_with(updater.FEED)
