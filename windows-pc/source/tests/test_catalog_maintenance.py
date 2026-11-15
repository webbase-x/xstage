import queue
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from karaoke.catalog_maintenance import maintain_catalog
from karaoke.library import SearchCancelled, SongLibrary, canonical
from karaoke.shutdown import wait_for_index
from karaoke.ui import KaraokeApp


class CatalogMaintenanceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.songs = self.root / 'Songs'
        self.external = self.root / 'External'
        self.library = SongLibrary(self.root / 'Data' / 'songs.sqlite3')

    def song(self, folder, stem, title, artist='นักร้อง', key='C'):
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (stem + '.wav')
        with wave.open(str(path), 'wb') as stream:
            stream.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            stream.writeframes(b'\x00\x00' * 16)
        path.with_suffix('.lrc').write_text(f'[ti:{title}]\n[ar:{artist}]\n[key:{key}]\n[00:00.00]ทดสอบ', encoding='utf-8')
        return path

    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')

    def test_copy_skips_triplet_already_in_songs_and_keeps_distinct_keys(self):
        managed = self.song(self.songs, 'managed', 'ชื่อเพลง')
        duplicate = self.song(self.external, 'duplicate', '  ชื่อเพลง  ')
        unique = self.song(self.external, 'unique', 'ชื่อเพลง', key='Am')
        same_bytes_new_artist = self.song(self.external, 'third', 'ชื่อเพลง', artist='อีกคน')
        keep_id = self.library.add_files([duplicate])[0]
        count, skipped, _ = maintain_catalog(self.library, self.external, self.songs, 'update', True,
                                              protected=[keep_id])
        self.assertEqual((count, skipped), (3, 1))
        self.assertEqual(self.library.get(keep_id)['path'], canonical(managed))
        self.assertFalse((self.songs / 'Audio' / duplicate.name).exists())
        for source in (unique, same_bytes_new_artist):
            target = self.songs / 'Audio' / source.name
            self.assertTrue(target.is_file())
            self.assertEqual(target.with_suffix('.lrc').read_bytes(), source.with_suffix('.lrc').read_bytes())
            self.assertTrue(source.is_file())

    def test_rebuild_removes_stale_and_duplicate_rows_then_clear_keeps_files(self):
        keep = self.song(self.songs, 'first', 'เพลง')
        duplicate = self.song(self.songs, 'duplicate', 'เพลง')
        external = self.song(self.external, 'unrelated', 'นอกโฟลเดอร์')
        keep_id, duplicate_id, external_id = self.library.add_files([keep, duplicate, external])
        count, skipped, _ = maintain_catalog(self.library, self.songs, self.songs, 'rebuild', False,
                                              protected=[keep_id])
        self.assertEqual((count, skipped), (1, 1))
        self.assertIsNotNone(self.library.get(keep_id))
        self.assertIsNone(self.library.get(duplicate_id))
        self.assertIsNone(self.library.get(external_id))
        self.assertTrue(duplicate.is_file())
        maintain_catalog(self.library, self.songs, self.songs, 'clear', False)
        self.assertEqual(self.library.count(), 0)
        self.assertTrue(keep.is_file())
        maintain_catalog(self.library, self.songs, self.songs, 'rebuild', False)
        self.assertGreater(self.library.search()[0]['id'], external_id)

    def test_empty_rebuild_and_cancel_leave_existing_catalog(self):
        existing = self.song(self.songs, 'existing', 'เก็บไว้')
        song_id = self.library.add_files([existing])[0]
        self.external.mkdir()
        with self.assertRaises(ValueError):
            maintain_catalog(self.library, self.external, self.songs, 'rebuild', False)
        self.song(self.external, 'new', 'รายการใหม่')
        cancelled = threading.Event()

        def cancel_at_commit(event):
            if event.get('phase') == 'สำรองและบันทึกรายการเพลง':
                cancelled.set()

        with self.assertRaises(SearchCancelled):
            maintain_catalog(self.library, self.external, self.songs, 'rebuild', False,
                             cancelled, cancel_at_commit)
        self.assertEqual(self.library.count(), 1)
        self.assertIsNotNone(self.library.get(song_id))

    def test_shutdown_cancel_releases_catalog_worker_and_clears_scanning(self):
        window = Mock()
        window.window.winfo_exists.return_value = True
        app = SimpleNamespace(scanning=False, _cloud_backup_busy=False, engine=None,
                              cancel_scan=threading.Event(), catalog_window=window,
                              library=self.library, song_queue=SimpleNamespace(items=[]),
                              status_var=Mock(), after=Mock(return_value='close-wait'),
                              index_protected_ids=set, managed_catalog_root=lambda: self.songs,
                              messages=queue.Queue())

        def wait_for_cancel(*args, cancelled, **kwargs):
            if not cancelled.wait(2):
                raise RuntimeError('Shutdown did not signal cancellation')
            raise SearchCancelled()

        with patch('karaoke.catalog_maintenance.maintain_catalog', side_effect=wait_for_cancel):
            self.assertTrue(KaraokeApp.start_catalog_maintenance(app, self.songs, 'update'))
            self.assertTrue(wait_for_index(app))
            app._index_thread.join(timeout=3)
            self.assertFalse(app._index_thread.is_alive())
            kind, payload = app.messages.get_nowait()
        self.assertEqual((kind, payload), ('catalog_finished', (None, None, {})))
        KaraokeApp.handle_catalog_message(app, kind, payload)
        self.assertFalse(app.scanning)
        self.assertFalse(wait_for_index(app))
        window.finish.assert_called_once_with(result=None, error=None, cancelled=True)

    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')

    def test_copy_retry_reuses_unindexed_bundle_with_catalog_metadata(self):
        song = self.song(self.external, 'legacy', 'จากดัชนี')
        song.with_suffix('.lrc').unlink()
        existing = self.songs / 'Audio' / song.name
        existing.parent.mkdir(parents=True)
        existing.write_bytes(song.read_bytes())
        hints = dict(title='จากดัชนี', artist='นักร้อง', key_signature='C')
        with patch('karaoke.catalog_maintenance.catalog_location', return_value=(None, self.external)), \
                patch('karaoke.catalog_maintenance.catalog_hints', side_effect=lambda plan, *args: plan.add_hint(song, hints)):
            count, _, notes = maintain_catalog(self.library, self.external, self.songs, 'rebuild', True)
        self.assertEqual(count, 1)
        self.assertEqual(list(existing.parent.glob('*.wav')), [existing])
        self.assertEqual(self.library.search()[0]['title'], 'จากดัชนี')
        self.assertIn('คัดลอก 0', notes[0])


if __name__ == '__main__':
    unittest.main()
