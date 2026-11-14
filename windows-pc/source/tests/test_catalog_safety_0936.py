"""v0.9.36 regressions for scoped scanning, imports, cache and shutdown."""
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_fast_catalog_0934 import FastCatalog0934Tests
from karaoke.fast_catalog import build_fast_catalog, regenerate_catalog_reports
from karaoke.library import canonical


class CatalogSafety0936Tests(FastCatalog0934Tests):
    """Inherited tests ensure the new safety fixes do not change old behavior."""

    def test_unselected_drive_disconnected_not_marked_missing(self):
        a = self.add_song('a', payload=b'\x00\x00')
        other = self.root / 'Other'
        b = self.add_song('b', folder=other, payload=b'\x01\x01')
        self.lib.add_files([a, b])
        self.run_build()
        with self.lib.connect() as db:
            original = dict(db.execute('SELECT * FROM songs WHERE path=?', (canonical(b),)).fetchone())
        b.unlink()
        b.with_suffix('.lrc').unlink()
        result = self.run_build()
        with self.lib.connect() as db:
            after = dict(db.execute('SELECT * FROM songs WHERE path=?', (canonical(b),)).fetchone())
        self.assertEqual(original, after)
        self.assertEqual(result.metrics['missing'], 0)
        self.assertEqual(result.metrics['missing_changed'], 0)
        self.assertEqual(result.metrics['outside_kept'], 1)
        self.assertTrue(a.is_file())

    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')

    def test_copy_existing_external_to_managed_commits_show_and_review(self):
        for index, policy in enumerate(('show', 'review', 'hide'), 1):
            with self.subTest(policy=policy):
                external = self.root / 'External' / policy
                original = self.add_song('source', folder=external, payload=bytes([index, index]))
                # First pass indexes the original only.
                first = build_fast_catalog(self.lib, external, self.songs, 'fast',
                                           duplicate_policy=policy)
                self.assertTrue(first.metrics['added'] >= 1)
                second = build_fast_catalog(self.lib, external, self.songs, 'fast',
                                            copy_external=True, duplicate_policy=policy)
                self.assertEqual(second.metrics['copied'], 1)
                self.assertEqual(second.metrics['staged_new_rows'], 1)
                self.assertTrue(second.metrics['catalog_committed'])
                with self.lib.connect() as db:
                    actual = db.execute('SELECT count(*) FROM songs WHERE path LIKE ?',
                                        (str(self.songs / 'Audio') + '%',)).fetchone()[0]
                self.assertGreaterEqual(actual, 1)
                self.assertTrue(original.is_file())

    def test_regenerate_reports_without_accessing_media_files(self):
        song = self.add_song('report')
        self.run_build()
        (self.root/'Data'/'catalog-exact-duplicates.csv').unlink()
        song.unlink()
        song.with_suffix('.lrc').unlink()
        with patch('karaoke.fast_catalog.signature', side_effect=AssertionError('media read')):
            paths = regenerate_catalog_reports(self.lib, duplicate_policy='hide')
        self.assertEqual(len(paths), 4)
        self.assertTrue(all(Path(path).is_file() for path in paths))

    def test_cache_does_not_write_on_noop(self):
        self.add_song('song')
        self.run_build()
        second = self.run_build()
        self.assertEqual(second.metrics['cache_writes'], 0)
        self.assertFalse(second.metrics['catalog_committed'])
        self.assertTrue(second.metrics['reports_reused'])

    def test_disappearance_before_commit_prevents_partial_catalog_write(self):
        song = self.add_song('vanish')
        def remove_on_backup(event):
            if event.get('phase') == 'สำรองฐานข้อมูลก่อนบันทึก':
                song.unlink()
        with self.assertRaisesRegex(ValueError, 'ไฟล์เพลงเปลี่ยนหรือไม่พร้อมใช้งาน'):
            self.run_build(events=remove_on_backup)
        self.assertEqual(self.lib.count(), 0)

    def test_disappearance_before_shutdown_disables_shutdown(self):
        song = self.add_song('vanish')
        def remove_after_commit(event):
            if event.get('phase') == 'ตรวจความพร้อมเพลงก่อนปิดเครื่อง':
                song.unlink()
        result = self.run_build(strict_shutdown_check=True, events=remove_after_commit)
        self.assertTrue(result.metrics['catalog_committed'])
        self.assertEqual(result.metrics['result_status'], 'partial')
        self.assertFalse(result.safe_to_shutdown)
        self.assertTrue(result.metrics['post_commit_errors'])

    def test_report_failure_after_commit_returns_partial_result(self):
        self.add_song('song')
        with patch('karaoke.fast_catalog._write_reports', side_effect=OSError('disk full')):
            result = self.run_build()
        self.assertEqual(self.lib.count(), 1)
        self.assertTrue(result.metrics['catalog_committed'])
        self.assertEqual(result.metrics['result_status'], 'partial')
        self.assertFalse(result.safe_to_shutdown)
        self.assertTrue(any('disk full' in x for x in result.metrics['post_commit_errors']))
        self.assertIn('ฐานเพลงบันทึกแล้ว', result[2][1])

    def test_cache_failure_after_commit_returns_partial_result(self):
        self.add_song('song')
        with patch('karaoke.fast_catalog._persist_cache', side_effect=OSError('cache full')):
            result = self.run_build()
        self.assertEqual(self.lib.count(), 1)
        self.assertEqual(result.metrics['result_status'], 'partial')
        self.assertTrue(result.metrics['catalog_committed'])
        self.assertFalse(result.safe_to_shutdown)

if __name__ == '__main__':
    import unittest
    unittest.main()
