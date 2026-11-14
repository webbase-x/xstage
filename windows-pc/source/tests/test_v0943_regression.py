"""Regressions for 0.9.43: diagnostics and source-backed sync, no real song deletions."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from karaoke.cloud_sync import create_snapshot, validate_snapshot
from karaoke.google_drive_sync import Drive
from karaoke.library import SongLibrary, write_json
from tests.test_google_drive_sync import FakeDrive
from tools.run_build_tests import summarize


class XStage0943Regression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='xstage-0943-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root/'Data'
        self.data.mkdir()
        self.songs = self.root/'Songs'
        self.songs.mkdir()
        self.lib = SongLibrary(self.data/'songs.sqlite3')
        write_json(self.data/'settings.json', {})
        write_json(self.data/'queue.json', [])

    def test_snapshot_fails_if_required_database_hash_is_removed(self):
        snapshot = create_snapshot(self.data, self.root/'Drive', 'user@example.com', self.songs)
        manifest = snapshot/'manifest.json'
        payload = json.loads(manifest.read_text(encoding='utf-8'))
        del payload['checksums']['songs.sqlite3']
        manifest.write_text(json.dumps(payload), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            validate_snapshot(snapshot)

    def test_snapshot_fails_if_queue_hash_is_removed(self):
        snapshot = create_snapshot(self.data, self.root/'Drive', 'user@example.com', self.songs)
        manifest = snapshot/'manifest.json'
        payload = json.loads(manifest.read_text(encoding='utf-8'))
        del payload['checksums']['queue.json']
        manifest.write_text(json.dumps(payload), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            validate_snapshot(snapshot)

    def test_drive_uses_staged_md5_without_rereading_unchanged_song(self):
        song = self.songs/'one.wav'
        song.write_bytes(b'sample-audio-data')
        fake = FakeDrive()
        parent = fake.folder('root', 'test')
        songs = fake.folder(parent['id'], 'Songs')
        fake._upload(song, songs['id'])
        fake.uploaded.clear()
        proof = {'one.wav': {'md5': hashlib.md5(song.read_bytes()).hexdigest()}}
        with patch('karaoke.google_drive_sync.hashlib.md5', side_effect=AssertionError('unexpected full reread')):
            fake.upload_visible_files({'one.wav': song}, parent['id'], proofs=proof)
        self.assertEqual(fake.uploaded, [])

    def test_drive_missing_manifest_proof_fails_closed(self):
        song = self.songs/'one.wav'
        song.write_bytes(b'sample-audio-data')
        fake = FakeDrive()
        parent = fake.folder('root', 'test')
        with self.assertRaisesRegex(ValueError, 'MD5'):
            fake.upload_visible_files({'one.wav': song}, parent['id'], proofs={})
        self.assertEqual(fake.uploaded, [])

    def test_diagnostic_summary_retains_test_failure_ids(self):
        case = unittest.FunctionTestCase(lambda: None)
        result = unittest.TestResult()
        result.startTest(case)
        try:
            raise RuntimeError('Native Windows failure')
        except RuntimeError:
            import sys
            result.addError(case, sys.exc_info())
        result.stopTest(case)
        payload = summarize(result)
        self.assertFalse(payload['pass'])
        self.assertEqual(payload['tests_run'], 1)
        self.assertEqual(len(payload['errors']), 1)
        self.assertIn('RuntimeError', payload['errors'][0]['traceback'])

    def test_duplicate_scan_rejects_legacy_automatic_hiding_mode(self):
        from karaoke.duplicates import scan
        with self.assertRaisesRegex(ValueError, 'ไม่อนุญาต'):
            scan(self.lib, verify_only=False)
        self.assertEqual(self.lib.count(), 0)

    def test_release_keeps_hard_build_gate_and_diagnostics(self):
        source = Path(__file__).resolve().parents[1]
        build = (source/'build.ps1').read_text(encoding='utf-8-sig')
        install = (source/'tools/Install-Logged.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('Tests failed; no executable was built', build)
        self.assertIn('build-tests-summary.json', build)
        self.assertIn('build-tests-summary.json', install)
        self.assertIn('Build test diagnostics', install)

    def test_version_stays_consistent(self):
        from karaoke import __version__
        from tools.verify_release import check_source
        self.assertRegex(__version__, r'^\d+\.\d+\.\d+$')
        self.assertEqual(check_source(Path(__file__).resolve().parents[1]), __version__)


if __name__ == '__main__':
    unittest.main()
