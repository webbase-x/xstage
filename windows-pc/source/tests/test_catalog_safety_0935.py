"""v0.9.35 regressions: safe missing media, cache migration, scoped rebuild, backups."""
import sqlite3
from contextlib import closing
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_fast_catalog_0934 import FastCatalog0934Tests
from karaoke.fast_catalog import build_fast_catalog
from karaoke.library import canonical


class CatalogSafety0935Tests(FastCatalog0934Tests):
    # Inherit the original release cases as well: these tests also exercise
    # the same code paths with new v0.9.35 semantics.

    def test_removed_song_is_reversible_and_disables_shutdown(self):
        song = self.add_song('missing')
        self.run_build()
        with self.lib.connect() as db:
            sid = db.execute('SELECT id FROM songs WHERE path=?', (canonical(song),)).fetchone()[0]
        song.unlink()
        song.with_suffix('.lrc').unlink()
        partial = self.run_build()
        self.assertEqual(self.lib.count(), 0)
        self.assertEqual(partial.metrics['missing'], 1)
        self.assertEqual(partial.metrics['result_status'], 'partial')
        self.assertFalse(partial.safe_to_shutdown)
        self.assertEqual(self.lib.get(sid)['duplicate_state'], 'missing')
        self.assertEqual(self.lib.get(sid)['id'], sid)
        self.assertEqual(list(self.lib.search()), [])
        self.assertTrue((self.root/'Data'/'catalog-missing-files.csv').is_file())
        restored = self.add_song('missing', title='กู้คืน')
        self.assertTrue(restored.is_file())
        complete = self.run_build()
        self.assertEqual(self.lib.count(), 1)
        self.assertEqual(complete.metrics['missing'], 0)
        self.assertTrue(complete.safe_to_shutdown)
        self.assertEqual(self.lib.get(sid)['id'], sid)
        self.assertEqual(self.lib.get(sid)['title'], 'กู้คืน')

    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')

    def test_missing_duplicate_keeper_promotes_copy_and_resolves_old_id(self):
        first = self.add_song('a')
        second = self.add_song('b')
        self.run_build()
        with self.lib.connect() as db:
            keeper = dict(db.execute("SELECT * FROM songs WHERE duplicate_of=0").fetchone())
            original_id = keeper['id']
            copy = dict(db.execute('SELECT * FROM songs WHERE duplicate_of<>0').fetchone())
            db.execute('UPDATE songs SET favorite=1,user_edited=1,title=? WHERE id=?', ('กำหนดชื่อเอง',original_id))
        Path(keeper['path']).unlink()
        Path(keeper['path']).with_suffix('.lrc').unlink()
        result = self.run_build()
        self.assertEqual(result.metrics['missing'], 1)
        self.assertFalse(result.safe_to_shutdown)
        self.assertEqual(self.lib.count(), 1)
        new = self.lib.get(copy['id'])
        self.assertEqual(new['id'], copy['id'])
        self.assertEqual(new['duplicate_of'], 0)
        self.assertEqual(new['favorite'], 1)
        self.assertEqual(new['title'], 'กำหนดชื่อเอง')
        self.assertEqual(self.lib.get(original_id)['id'], copy['id'])
        # Queue/UI code using the original ID can still toggle favorite and
        # edit the promoted song, preserving those values on the tombstone too.
        self.lib.favorite(original_id)
        self.assertEqual(self.lib.get(copy['id'])['favorite'], 0)
        self.lib.favorite(original_id)
        self.assertEqual(self.lib.get(copy['id'])['favorite'], 1)
        self.lib.edit(original_id, 'NEW', 'แก้ใหม่', 'นักร้อง', 'C')
        self.assertEqual(self.lib.get(copy['id'])['title'], 'แก้ใหม่')
        with self.lib.connect() as db:
            raw = db.execute('SELECT duplicate_state FROM songs WHERE id=?',(original_id,)).fetchone()
            self.assertEqual(raw[0], 'missing')
        with patch.object(self.lib, 'backup_before_rebuild', side_effect=AssertionError('no data changed')):
            repeated = self.run_build()
        self.assertTrue(repeated.metrics['reports_reused'])
        self.assertEqual(self.lib.count(), 1)
        # The previously missing file returns and its stable original ID works again.
        self.add_song('a')
        self.run_build()
        self.assertEqual(self.lib.get(original_id)['id'], original_id)

    def test_first_fast_scan_does_not_trust_unverified_catalog_metadata(self):
        song = self.add_song('old', title='ชื่อเก่า')
        self.lib.add_files([song])
        song.with_suffix('.lrc').write_text('[ti:ชื่อใหม่]\n[ar:นักร้อง]\n[key:C]\n[00:00.00]คำใหม่', encoding='utf8')
        result = self.run_build()
        self.assertEqual(result.metrics['updated'], 1)
        self.assertEqual(self.lib.search('ชื่อใหม่')[0]['title'], 'ชื่อใหม่')
        self.assertEqual(self.run_build().metrics['unchanged'], 1)

    def test_rebuild_scoped_to_folder_without_removing_other_folder(self):
        first_folder = self.songs/'First'
        second_folder = self.songs/'Second'
        song1 = self.add_song('a', folder=first_folder)
        song2 = self.add_song('b', folder=second_folder, payload=b'\2\2')
        self.run_build()
        result = build_fast_catalog(self.lib, first_folder, self.songs, 'safe_rebuild')
        self.assertEqual(result.metrics['missing'], 0)
        self.assertTrue(song2.is_file())
        self.assertEqual(self.lib.count(), 2)
        song1.unlink(); song1.with_suffix('.lrc').unlink()
        # An empty rebuild cannot destructively clear the database.
        try:
            build_fast_catalog(self.lib, first_folder, self.songs, 'safe_rebuild')
        except ValueError:
            pass
        self.assertTrue(song2.is_file())
        self.assertIsNotNone(self.lib.get(2))

    def test_unsupported_input_is_partial_and_disables_poweroff(self):
        self.add_song('a')
        (self.songs/'unsupported.xmk').write_bytes(b'not-supported')
        result = self.run_build()
        self.assertEqual(result.metrics['unsupported'], 1)
        self.assertFalse(result.safe_to_shutdown)
        self.assertEqual(result.metrics['result_status'], 'partial')

    def test_rotating_verified_backup_and_offline_restore(self):
        self.add_song('a')
        self.run_build()
        original = self.lib.count()
        self.lib.backup_before_rebuild(keep=3)
        self.lib.backup_before_rebuild(keep=3)
        self.lib.backup_before_rebuild(keep=3)
        copies = self.lib.list_reindex_backups()
        self.assertEqual(len(copies), 3)
        self.assertEqual(len(set(copies)), 3)
        with closing(sqlite3.connect(copies[0])) as db:
            self.assertEqual(db.execute('PRAGMA quick_check').fetchone()[0], 'ok')
        self.add_song('b', payload=b'\1\1')
        self.run_build()
        self.assertEqual(self.lib.count(), original + 1)
        self.lib.restore_reindex_backup(copies[0])
        self.assertEqual(self.lib.count(), original)
        with self.assertRaises(ValueError):
            self.lib.restore_reindex_backup(self.root/'unknown.sqlite3')


if __name__ == '__main__':
    import unittest
    unittest.main()
