"""R18 Turbo Sync: bounded upload, atomic catalog, and interrupted chunk recovery.

All inputs and Google Drive endpoints are synthetic; no credentials or real
song files are needed. These tests are safe on Windows and Linux.
"""
import io
import json
import tempfile
import threading
import time
import unittest
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from karaoke.google_drive_sync import Drive
from karaoke.library import SongLibrary
from karaoke.web_drive import ROOT_NAME, _load_current, sync_web_assets
from tests.test_studio import midi_fixture
from tests.test_v0944_web_sync import FakeWebDrive, StubRenderer


class ConcurrentFakeDrive(FakeWebDrive):
    """Drive double with reliable concurrent metadata and measurable uploads."""
    def __init__(self):
        super().__init__()
        self.lock = threading.RLock()
        self.measure_lock = threading.Lock()
        self.active_media = 0
        self.peak_media = 0
        self.fail_lyrics_for = None

    def children(self, parent, name=None):
        with self.lock:
            return super().children(parent, name)

    def folder(self, parent, name):
        with self.lock:
            return super().folder(parent, name)

    def create(self, parent, name, blob, folder=False, existing=None):
        with self.lock:
            return super().create(parent, name, blob, folder=folder, existing=existing)

    def get_metadata(self, file_id):
        with self.lock:
            return super().get_metadata(file_id)

    def download(self, file_id):
        with self.lock:
            return super().download(file_id)

    def _upload(self, path, parent, existing=None):
        name = Path(path).name
        if name.endswith('.json') and self.fail_lyrics_for and name.startswith(self.fail_lyrics_for + '-'):
            raise OSError('synthetic lyrics upload failure')
        is_media = name.endswith('.m4a')
        if is_media:
            with self.measure_lock:
                self.active_media += 1
                self.peak_media = max(self.peak_media, self.active_media)
        try:
            if is_media:
                time.sleep(0.035)
            return super()._upload(path, parent, existing)
        finally:
            if is_media:
                with self.measure_lock:
                    self.active_media -= 1


class R18TurboSyncTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        folder = self.root / 'Data'
        folder.mkdir()
        self.songs = self.root / 'Songs'
        self.songs.mkdir()
        self.font = self.root / 'test.sf2'
        self.font.write_bytes(b'fake-sf2')
        self.library = SongLibrary(folder / 'songs.sqlite3')
        self.cache = self.root / 'WebAssets'
        self.drive = ConcurrentFakeDrive()
        for code in range(97001, 97007):
            (self.songs / f'{code}.mid').write_bytes(midi_fixture())
        self.library.add_files(sorted(self.songs.glob('*.mid')))

    def sync(self, **kwargs):
        return sync_web_assets(self.drive, self.library.path, [self.songs],
            self.root / 'native', {}, self.font, self.cache,
            renderer_factory=StubRenderer, verify_integrity=False,
            first_batch_size=1, batch_size=3, publish_interval=300, **kwargs)

    def catalog(self):
        root = self.drive.children('root', ROOT_NAME)[0]['id']
        return _load_current(self.drive, root)

    def test_bounded_parallel_uploads_and_verified_catalog(self):
        report = self.sync(upload_workers=3)
        self.assertEqual(report['total'], 6)
        self.assertEqual(report['uploaded_files'], 12)
        self.assertGreaterEqual(self.drive.peak_media, 2)
        self.assertLessEqual(self.drive.peak_media, 3)
        _, pointer, catalog = self.catalog()
        self.assertEqual(pointer['songCount'], 6)
        self.assertEqual(len(catalog['songs']), 6)
        for row in catalog['songs']:
            for kind in ('audio', 'lyrics'):
                self.assertEqual(self.drive.get_metadata(row[kind]['fileId'])['md5Checksum'],
                                 row[kind]['md5'])
        before = len(self.drive.uploads)
        repeated = self.sync(upload_workers=3)
        self.assertEqual(repeated['reused'], 6)
        self.assertEqual(repeated['uploaded_files'], 0)
        self.assertEqual(len(self.drive.uploads), before)

    def test_failed_lyrics_pair_is_never_published_and_retry_recovers(self):
        self.drive.fail_lyrics_for = '97003'
        initial = self.sync(upload_workers=3)
        self.assertEqual(len(initial['failed']), 1)
        self.assertTrue(initial['failed'][0][0] == '97003')
        _, _, catalog = self.catalog()
        self.assertEqual(len(catalog['songs']), 5)
        self.assertNotIn('97003', {row['code'] for row in catalog['songs']})
        self.drive.fail_lyrics_for = None
        repaired = self.sync(upload_workers=3)
        self.assertEqual(repaired['failed'], [])
        self.assertEqual(len(self.catalog()[2]['songs']), 6)
        # The first attempt already uploaded an intact M4A; it is reused.
        self.assertEqual(repaired['uploaded_files'], 1)

    def test_upload_workers_are_clamped_and_sequential_mode_stays_safe(self):
        report = self.sync(upload_workers=0)
        self.assertEqual(report['total'], 6)
        self.assertEqual(self.drive.peak_media, 1)


class FakeResponse:
    def __init__(self, value):
        self.status = 200
        self.value = value
    def __enter__(self):
        return self
    def __exit__(self, *_):
        pass
    def read(self):
        return json.dumps(self.value).encode('utf-8')


class ResumableUploadTests(unittest.TestCase):
    def test_timeout_probes_accepted_offset_instead_of_replaying_chunk(self):
        with tempfile.TemporaryDirectory() as home:
            path = Path(home) / 'song.m4a'
            path.write_bytes(b'12345678')
            drive = Drive('token')
            seen = []
            session = 'https://www.googleapis.com/upload/session-id-for-test'
            def urlopen(request, timeout=None):
                body = request.data
                header = request.get_header('Content-range')
                seen.append((header, body))
                if body == b'1234':
                    raise TimeoutError('server accepted first chunk but response was lost')
                if body == b'':
                    raise urllib.error.HTTPError(session, 308, 'Resume Incomplete',
                        {'Range': 'bytes=0-3'}, None)
                if body == b'5678':
                    return FakeResponse({'id':'complete', 'md5Checksum':'x'})
                raise AssertionError(f'unexpected retransmission {body!r}')
            with patch('karaoke.google_drive_sync._request',
                       return_value=(200, {'Location': session}, b'')), \
                 patch('karaoke.google_drive_sync.CHUNK', 4), \
                 patch('karaoke.google_drive_sync.time.sleep'), \
                 patch('karaoke.google_drive_sync.urllib.request.urlopen', side_effect=urlopen):
                result = drive._upload(path, 'parent')
            self.assertEqual(result['id'], 'complete')
            self.assertEqual([v[1] for v in seen], [b'1234', b'', b'5678'])
            self.assertEqual(seen[1][0], 'bytes */8')
            self.assertEqual(seen[2][0], 'bytes 4-7/8')

    def test_malformed_range_is_rejected_without_advancing(self):
        with tempfile.TemporaryDirectory() as home:
            path=Path(home)/'a.m4a';path.write_bytes(b'1234')
            session='https://www.googleapis.com/upload/test'
            with patch('karaoke.google_drive_sync._request',
                       return_value=(200, {'Location': session}, b'')), \
                 patch('karaoke.google_drive_sync.urllib.request.urlopen',
                       side_effect=urllib.error.HTTPError(session, 308, 'Incomplete',
                           {'Range':'bytes=0-99999999'}, None)):
                with self.assertRaisesRegex(OSError, 'เกินขนาด'):
                    Drive('token')._upload(path,'parent')

    def test_parallel_refresh_is_single_flight(self):
        drive = Drive('expired', client_id='id', refresh_token='secret', expires_at=0)
        calls=[]
        lock=threading.Lock()
        def fake_request(*args, **kwargs):
            with lock:
                calls.append(1)
            time.sleep(.015)
            return 200, {}, json.dumps({'access_token':'new', 'expires_in':3600}).encode()
        with patch('karaoke.google_drive_sync._request', side_effect=fake_request):
            with ThreadPoolExecutor(max_workers=10) as pool:
                result=list(pool.map(lambda _:drive.access_token(), range(10)))
        self.assertEqual(result, ['new'] * 10)
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
