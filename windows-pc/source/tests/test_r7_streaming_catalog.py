"""Tests for batch/pipelined X-Stage Web catalog publication.

Uses a fake private Drive and stub audio encoder. Never accesses the network.
"""
import json
import tempfile
import threading
import unittest
from pathlib import Path

from karaoke.library import SongLibrary
from karaoke.web_drive import _load_current, sync_web_assets, ROOT_NAME
from tests.test_studio import midi_fixture
from tests.test_v0944_web_sync import FakeWebDrive, StubRenderer


class StreamingCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'Songs'
        self.source.mkdir()
        self.data = self.root / 'Data'
        self.data.mkdir()
        self.font = self.root / 'quality.sf2'
        self.font.write_bytes(b'fake-test-font')
        self.library = SongLibrary(self.data / 'songs.sqlite3')
        self.drive = FakeWebDrive()
        self.cache = self.root / 'WebAssets'
        StubRenderer.builds = 0
        for n in range(6):
            (self.source / f'{88001+n:05d}.mid').write_bytes(midi_fixture())
        self.library.add_files(sorted(self.source.glob('*.mid')))

    def sync(self, *, cancel=None, progress=None):
        return sync_web_assets(self.drive, self.library.path, [self.source],
                               self.root / 'native', {}, self.font, self.cache,
                               renderer_factory=StubRenderer, cancel=cancel,
                               progress=progress, first_batch_size=2,
                               batch_size=2, publish_interval=9999)

    def published(self):
        root = self.drive.children('root', ROOT_NAME)[0]['id']
        _, pointer, catalog = _load_current(self.drive, root)
        return pointer, catalog

    def test_first_batch_is_playable_before_all_songs_are_done(self):
        stopped = threading.Event()
        def progress(message, completed=0, total=0):
            if 'เว็บไซต์เปิดเพลงได้แล้ว' in message:
                stopped.set()
        with self.assertRaisesRegex(RuntimeError, 'ยกเลิก'):
            self.sync(cancel=stopped, progress=progress)
        pointer, catalog = self.published()
        self.assertEqual(len(catalog['songs']), 2)
        self.assertEqual(pointer['songCount'], 2)
        self.assertFalse(pointer.get('deltaFileIds'))
        for song in catalog['songs']:
            self.assertTrue(self.drive.get_metadata(song['audio']['fileId']))
            self.assertTrue(self.drive.get_metadata(song['lyrics']['fileId']))
        # The original singer can open a published catalog even after cancel.
        self.assertEqual(len(self.drive.children(self.drive.children('root',ROOT_NAME)[0]['id'], 'current.json')), 1)

    def test_second_batch_publishes_delta_not_entire_database(self):
        stopped = threading.Event()
        published = []
        def progress(message, completed=0, total=0):
            if 'เว็บไซต์เปิดเพลงได้แล้ว' in message:
                published.append(completed)
                if len(published) == 2:
                    stopped.set()
        with self.assertRaisesRegex(RuntimeError, 'ยกเลิก'):
            self.sync(cancel=stopped, progress=progress)
        pointer, catalog = self.published()
        self.assertEqual(published, [2, 4])
        self.assertEqual(pointer['songCount'], 4)
        self.assertEqual(len(pointer['deltaFileIds']), 1)
        self.assertEqual(len(catalog['songs']), 4)
        delta = json.loads(self.drive.download(pointer['deltaFileIds'][0]))
        self.assertEqual(len(delta['upserts']), 2)
        self.assertEqual(delta['removes'], [])
        self.assertGreaterEqual(StubRenderer.builds, 4)  # bounded prefetch
        # Resuming reuses already verified audio, continues remaining conversions,
        # then compacts delta chain to a complete snapshot.
        result = self.sync()
        final, catalog = self.published()
        self.assertEqual(len(catalog['songs']), 6)
        self.assertEqual(final['songCount'], 6)
        self.assertFalse(final.get('deltaFileIds'))
        self.assertEqual(result['total'], 6)
        self.assertGreaterEqual(result['reused'], 4)
        self.assertEqual(len([x for x in self.drive.uploads if x.endswith('.m4a')]), 6)

    def test_second_song_is_rendering_while_first_upload_is_active(self):
        """Explicit pipeline regression: conversion and upload overlap in time."""
        import time
        from threading import Event
        second_started = Event()
        first_upload_observed = []

        class SignalingRenderer(StubRenderer):
            def build(self, song, parts, cancel=None):
                if str(song['code']) == '88002':
                    second_started.set()
                return super().build(song, parts, cancel)

        original = self.drive._upload
        def spy_upload(path, parent, existing=None):
            if Path(path).name.startswith('88001') and Path(path).suffix == '.m4a':
                first_upload_observed.append(second_started.wait(timeout=4))
            return original(path, parent, existing)
        self.drive._upload = spy_upload
        sync_web_assets(self.drive, self.library.path, [self.source],
                        self.root / 'native', {}, self.font, self.cache,
                        renderer_factory=SignalingRenderer, first_batch_size=2,
                        batch_size=2, publish_interval=9999)
        self.assertTrue(first_upload_observed)
        self.assertTrue(all(first_upload_observed), 'Second song did not render while first uploaded')

    def test_final_compaction_failure_preserves_intermediate_website(self):
        """Failure uploading final current.json does not undo visible batches."""
        original = self.drive._upload
        pointer_writes = 0
        def fail_final(path,parent,existing=None):
            nonlocal pointer_writes
            if Path(path).name == 'current.json':
                pointer_writes += 1
                if pointer_writes == 4:  # 2 batches + final? fail late publication
                    raise OSError('failure publishing full snapshot')
            return original(path,parent,existing)
        self.drive._upload = fail_final
        with self.assertRaisesRegex(OSError, 'failure publishing full snapshot'):
            self.sync()
        pointer, catalog = self.published()
        self.assertGreaterEqual(pointer['songCount'],2)
        self.assertLessEqual(pointer['songCount'],6)
        self.assertEqual(len(catalog['songs']),pointer['songCount'])
        self.drive._upload = original
        result = self.sync()
        pointer, catalog = self.published()
        self.assertEqual(len(catalog['songs']),6)
        self.assertEqual(result['total'],6)

    def test_failed_second_batch_cannot_break_first_catalog(self):
        # Crash only while writing the first delta, leaving the original
        # snapshot and its media accessible on the private Drive.
        def failure(message, completed=0, total=0):
            if 'เว็บไซต์เปิดเพลงได้แล้ว' in message:
                self.drive.fail_suffix='delta-'
        # FakeWebDrive compares suffix; monkey-patch _upload to fail on delta.
        original = self.drive._upload
        def upload(path,parent,existing=None):
            if Path(path).name.startswith('delta-'):
                raise OSError('network failed on delta upload')
            return original(path,parent,existing)
        self.drive._upload = upload
        with self.assertRaisesRegex(RuntimeError, 'network failed'):
            self.sync(progress=failure)
        pointer, catalog = self.published()
        self.assertEqual(pointer['songCount'],2)
        self.assertEqual(len(catalog['songs']),2)


if __name__ == '__main__':
    unittest.main()
