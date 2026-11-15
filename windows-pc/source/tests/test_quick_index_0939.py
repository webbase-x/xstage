"""v0.9.39 two-phase search-first index regression and safety tests."""
from pathlib import Path
from unittest.mock import patch
import tempfile
import threading
import unittest

from tests.test_fast_catalog_0934 import FastCatalog0934Tests
from karaoke.fast_catalog import build_fast_catalog
from karaoke.quick_catalog import pending_count
from karaoke.library import SongLibrary, SearchCancelled, canonical


class QuickIndex0939Tests(FastCatalog0934Tests):
    def quick(self, source=None, **kwargs):
        return build_fast_catalog(self.lib, source or self.songs, self.songs, mode='quick', **kwargs)

    def test_quick_makes_same_size_new_songs_visible_without_hash(self):
        a = self.add_song('one'); b = self.add_song('two')
        with patch('karaoke.fast_catalog.content_key', side_effect=AssertionError('SHA read')):
            result = self.quick()
        self.assertEqual(result.metrics['added'], 2)
        self.assertEqual(result.metrics['hashed'], 0)
        self.assertEqual(self.lib.count(), 2)
        self.assertEqual(pending_count(self.lib), 2)
        self.assertTrue(result.metrics['reports_deferred'])
        self.assertFalse(result.safe_to_shutdown)
        self.assertTrue(a.is_file() and b.is_file())
        self.assertFalse((self.root/'Data'/'catalog-exact-duplicates.csv').exists())

    def test_phase_two_exact_verification_hides_and_drains_pending(self):
        a = self.add_song('one'); b = self.add_song('two')
        self.quick()
        result = self.run_build(mode='fast')
        self.assertEqual(result.metrics['duplicates'], 1)
        self.assertEqual(self.lib.count(), 2)
        self.assertEqual(pending_count(self.lib), 0)
        self.assertEqual(result.metrics['hashed'], 2)
        self.assertTrue(a.is_file() and b.is_file())

    def test_quick_no_op_does_not_backup_rewrite_or_generate_report(self):
        self.add_song('one')
        self.quick()
        with patch.object(self.lib, 'backup_before_rebuild', side_effect=AssertionError('backup')):
            with patch('karaoke.quick_catalog._quick_commit', side_effect=AssertionError('commit')):
                second = self.quick()
        self.assertEqual(second.metrics['unchanged'], 1)
        self.assertEqual(second.metrics['cache_writes'], 0)
        self.assertFalse(second.metrics['catalog_committed'])
        self.assertEqual(pending_count(self.lib), 1)

    def test_quick_change_preserves_id_user_edit_and_favorite(self):
        a = self.add_song('one')
        self.quick()
        with self.lib.connect() as db:
            sid = db.execute('SELECT id FROM songs WHERE path=?', (canonical(a),)).fetchone()[0]
            db.execute('UPDATE songs SET title=?,user_edited=1,favorite=1 WHERE id=?', ('กำหนดเอง', sid))
        sidecar = a.with_suffix('.lrc')
        sidecar.write_text('[ti:ชื่อใหม่]\n[ar:ศิลปิน]\n[00:00.00]เปลี่ยน', encoding='utf-8')
        updated = self.quick()
        with self.lib.connect() as db:
            row = db.execute('SELECT * FROM songs WHERE path=?', (canonical(a),)).fetchone()
        self.assertEqual(updated.metrics['updated'], 1)
        self.assertEqual(row['id'], sid)
        self.assertEqual(row['title'], 'กำหนดเอง')
        self.assertEqual(row['favorite'], 1)
        self.assertEqual(pending_count(self.lib), 1)

    def test_scope_keeps_disconnected_other_folder_unmodified(self):
        a = self.add_song('one')
        other = self.root/'Other'; b = self.add_song('two', folder=other)
        self.quick()
        build_fast_catalog(self.lib, other, self.songs, mode='quick')
        with self.lib.connect() as db:
            before = dict(db.execute('SELECT * FROM songs WHERE path=?', (canonical(b),)).fetchone())
        b.unlink(); b.with_suffix('.lrc').unlink()
        result = self.quick()
        with self.lib.connect() as db:
            after = dict(db.execute('SELECT * FROM songs WHERE path=?', (canonical(b),)).fetchone())
        self.assertEqual(before, after)
        self.assertEqual(result.metrics['missing'], 0)
        self.assertTrue(a.is_file())

    def test_missing_keeper_keeps_copy_available_then_fast_verifies(self):
        a = self.add_song('one'); b = self.add_song('two')
        self.run_build()
        with self.lib.connect() as db:
            keeper = db.execute('SELECT path FROM songs WHERE duplicate_of=0').fetchone()[0]
        gone = Path(keeper)
        gone.unlink(); gone.with_suffix('.lrc').unlink()
        result = self.quick()
        self.assertEqual(result.metrics['missing'], 1)
        self.assertEqual(self.lib.count(), 1)
        with self.lib.connect() as db:
            survivor = db.execute('SELECT duplicate_of,duplicate_state FROM songs WHERE path<>?', (keeper,)).fetchone()
        self.assertEqual(survivor['duplicate_of'], 0)
        self.run_build()
        self.assertEqual(self.lib.count(), 1)

    def test_deleted_protected_tombstone_not_resurrected(self):
        song = self.add_song('one')
        self.quick()
        with self.lib.connect() as db:
            db.execute("UPDATE songs SET duplicate_state='deleted' WHERE path=?", (canonical(song),))
        self.quick()
        with self.lib.connect() as db:
            state = db.execute('SELECT duplicate_state FROM songs WHERE path=?', (canonical(song),)).fetchone()[0]
        self.assertEqual(state, 'deleted')

    def test_cancel_before_commit_leaves_catalog_empty(self):
        song = self.add_song('one')
        cancel = threading.Event()
        def callback(event):
            if event.get('phase') == 'ยืนยันไฟล์ใหม่ก่อนบันทึกฐาน':
                cancel.set()
        with self.assertRaises(SearchCancelled):
            self.quick(cancelled=cancel, events=callback)
        self.assertEqual(self.lib.count(), 0)
        self.assertEqual(pending_count(self.lib), 0)
        self.assertTrue(song.exists())

    def test_disappearing_file_aborts_before_commit(self):
        song = self.add_song('one')
        def callback(event):
            if event.get('phase') == 'ยืนยันไฟล์ใหม่ก่อนบันทึกฐาน':
                song.unlink()
        with self.assertRaisesRegex(ValueError, 'ไฟล์เพลงเปลี่ยนหรือไม่พร้อมใช้งาน'):
            self.quick(events=callback)
        self.assertEqual(self.lib.count(), 0)

    def test_missing_song_reversible_and_backup_retained(self):
        song = self.add_song('one')
        self.quick()
        song.unlink(); song.with_suffix('.lrc').unlink()
        missing = self.quick()
        self.assertEqual(missing.metrics['missing'], 1)
        self.assertEqual(self.lib.count(), 0)
        self.assertTrue(self.lib.list_reindex_backups())
        self.add_song('one')
        result = self.quick()
        self.assertEqual(result.metrics['updated'], 1)
        self.assertEqual(self.lib.count(), 1)

    def test_pending_survives_new_library_object(self):
        self.add_song('one'); self.quick()
        replacement = SongLibrary(self.lib.path)
        self.assertEqual(pending_count(replacement), 1)
        build_fast_catalog(replacement, self.songs, self.songs, mode='fast')
        self.assertEqual(pending_count(self.lib), 0)

    def test_two_folders_pending_remains_until_each_verified(self):
        self.add_song('one'); other = self.root/'Other'; self.add_song('two', folder=other)
        self.quick()
        build_fast_catalog(self.lib, other, self.songs, mode='quick')
        self.assertEqual(pending_count(self.lib), 2)
        self.run_build(mode='fast')
        self.assertEqual(pending_count(self.lib), 1)
        build_fast_catalog(self.lib, other, self.songs, mode='fast')
        self.assertEqual(pending_count(self.lib), 0)

    def test_phase_two_clears_pending_for_confirmed_missing_file(self):
        song = self.add_song('one')
        self.quick()
        song.unlink(); song.with_suffix('.lrc').unlink()
        self.quick()
        self.assertEqual(pending_count(self.lib), 1)
        result = self.run_build(mode='fast')
        self.assertEqual(result.metrics['missing'], 1)
        self.assertEqual(pending_count(self.lib), 0)

    def test_post_commit_pending_store_error_is_explicitly_partial(self):
        self.add_song('one')
        with patch('karaoke.quick_catalog._quick_cache', side_effect=OSError('disk full')):
            result = self.quick()
        self.assertTrue(result.metrics['catalog_committed'])
        self.assertEqual(result.metrics['result_status'], 'partial')
        self.assertFalse(result.safe_to_shutdown)
        self.assertEqual(self.lib.count(), 1)
        self.assertTrue(result.metrics['post_commit_errors'])

    def test_quick_copy_and_shutdown_must_use_verified_mode(self):
        self.add_song('one')
        with self.assertRaisesRegex(ValueError, 'คัดลอก'):
            self.quick(copy_external=True)
        with self.assertRaisesRegex(ValueError, 'ปิดเครื่อง'):
            self.quick(strict_shutdown_check=True)

    def test_unsupported_file_disables_success_status(self):
        self.add_song('one')
        (self.songs/'unsupported.xmk').write_bytes(b'bad')
        result = self.quick()
        self.assertEqual(result.metrics['result_status'], 'partial')
        self.assertFalse(result.safe_to_shutdown)


if __name__ == '__main__':
    unittest.main()
