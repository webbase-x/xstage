"""Version 0.9.34: fast and safe indexing; no file deletion; guarded power-off."""
import csv
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from karaoke.fast_catalog import build_fast_catalog
from karaoke.auto_shutdown_dialog import shutdown_allowed
from karaoke.library import SongLibrary, SearchCancelled, canonical


class FastCatalog0934Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='xstage-fast-0934-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.songs = self.root/'Songs'
        self.songs.mkdir()
        self.lib = SongLibrary(self.root/'Data'/'songs.sqlite3')

    def add_song(self, name, title='เพลงเดียวกัน', artist='นักร้อง', key='C', payload=b'\0\0', folder=None):
        folder = folder or self.songs
        folder.mkdir(parents=True, exist_ok=True)
        path = folder/(name+'.wav')
        with wave.open(str(path),'wb') as wav:
            wav.setparams((1,2,8000,0,'NONE','not compressed'))
            wav.writeframes(payload*16)
        path.with_suffix('.lrc').write_text(
            f'[ti:{title}]\n[ar:{artist}]\n[key:{key}]\n[00:00.00]ทดสอบ', encoding='utf-8')
        return path

    def run_build(self, mode='fast', duplicate_policy='hide', **kwargs):
        return build_fast_catalog(self.lib, self.songs, self.songs, mode,
                                  duplicate_policy=duplicate_policy, **kwargs)

    def test_content_identity_not_name_and_hash_reused_fast(self):
        same1 = self.add_song('001')
        same2 = self.add_song('002')
        different = self.add_song('003', payload=b'\x01\x01')
        first = self.run_build()
        self.assertEqual(first.metrics['duplicates'],1)
        self.assertEqual(self.lib.count(),3)
        self.assertEqual(first.metrics['hashed'],3)
        self.assertTrue(first.safe_to_shutdown)
        self.assertTrue(all(p.is_file() for p in (same1,same2,different)))
        with self.lib.connect() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM songs ORDER BY path')]
        self.assertEqual(len(rows),3)
        self.assertEqual(sum(bool(r['duplicate_of']) for r in rows),0)
        self.assertEqual(sum(r['duplicate_of']==0 for r in rows),3)
        second = self.run_build()
        self.assertEqual(second.metrics['unchanged'],3)
        self.assertEqual(second.metrics['hashed'],0)
        self.assertEqual(second.metrics['digest_reused'],3)
        self.assertEqual(second.metrics['duplicates'],1)
        self.assertEqual(self.lib.count(),3)
        with Path(second.duplicate_report).open(encoding='utf-8-sig', newline='') as stream:
            data=list(csv.reader(stream))
        self.assertEqual(len(data),2)

    def test_different_versions_show_review_and_hide(self):
        self.add_song('a',payload=b'\0\0')
        self.add_song('b',payload=b'\1\1')
        self.add_song('c',payload=b'\0\0')
        self.assertEqual(self.run_build(duplicate_policy='show').metrics['duplicates'],1)
        self.assertEqual(self.lib.count(),3)
        self.assertEqual(self.run_build(duplicate_policy='review').metrics['duplicates'],1)
        self.assertEqual(self.lib.count(),3)
        self.assertEqual(self.run_build(duplicate_policy='hide').metrics['duplicates'],1)
        self.assertEqual(self.lib.count(),3)
        report=self.root/'Data'/'catalog-possible-versions.csv'
        self.assertGreater(len(report.read_text(encoding='utf-8-sig').splitlines()),1)

    def test_change_metadata_and_sidecar_invalidate(self):
        song=self.add_song('a')
        self.run_build()
        sidecar=song.with_suffix('.lrc')
        sidecar.write_text('[ti:ชื่อใหม่]\n[ar:นักร้อง]\n[key:C]\n[00:00.00]เปลี่ยน',encoding='utf-8')
        changed=self.run_build()
        self.assertEqual(changed.metrics['updated'],1)
        self.assertEqual(self.lib.search('ชื่อใหม่')[0]['title'],'ชื่อใหม่')
        third=self.run_build()
        self.assertEqual(third.metrics['unchanged'],1)
        self.assertEqual(third.metrics['updated'],0)

    def test_rebuild_is_atomic_and_retains_files(self):
        keep=self.add_song('keep')
        stale=self.add_song('stale',payload=b'\x02\x02')
        self.run_build()
        stale.unlink()
        stale.with_suffix('.lrc').unlink()
        failed=self.songs/'bad.mid'
        failed.write_bytes(b'not midi')
        with self.assertRaises(ValueError):
            self.run_build(mode='safe_rebuild')
        self.assertEqual(len(self.lib.search(limit=10)),2)
        failed.unlink()
        result=self.run_build(mode='safe_rebuild')
        self.assertEqual(result[0],1)
        self.assertTrue(keep.exists())
        self.assertEqual(self.lib.count(),1)

    def test_cancel_before_commit_leaves_index_untouched(self):
        song=self.add_song('keep')
        sid=self.lib.add_files([song])[0]
        self.add_song('new')
        stop=threading.Event()
        def events(e):
            if e.get('phase')=='สำรองฐานข้อมูลก่อนบันทึก':stop.set()
        with self.assertRaises(SearchCancelled):
            self.run_build(events=events,cancelled=stop)
        self.assertEqual(self.lib.count(),1)
        self.assertEqual(self.lib.get(sid)['path'],canonical(song))

    def test_protected_keeper_keeps_same_id(self):
        first=self.add_song('a')
        second=self.add_song('b')
        self.run_build()
        with self.lib.connect() as db:
            sid2=db.execute('SELECT id FROM songs WHERE path=?',(canonical(second),)).fetchone()[0]
        self.run_build(protected=[sid2])
        self.assertEqual(self.lib.count(),2)
        with self.lib.connect() as db:
            self.assertEqual(db.execute('SELECT duplicate_of FROM songs WHERE path=?',(canonical(first),)).fetchone()[0],0)

    def test_copy_external_no_deletion_and_managed_kept(self):
        # v0.9.41 never makes a second copy inside Songs.
        external=self.root/'External'
        original=self.add_song('source',folder=external)
        with self.assertRaises(ValueError):
            build_fast_catalog(self.lib,external,self.songs,'fast',copy_external=True)
        result=build_fast_catalog(self.lib,external,self.songs,'fast')
        self.assertEqual(result.metrics['copied'],0)
        self.assertTrue(original.exists())
        self.assertFalse((self.songs/'Audio'/'source.wav').exists())
        self.assertEqual(self.lib.count(),1)

    def test_duplicate_across_other_existing_folder_and_fast_noop(self):
        inside = self.add_song('inside')
        outside = self.add_song('outside', folder=self.root/'Other')
        ids = self.lib.add_files([inside, outside])
        first = self.run_build()
        self.assertEqual(first.metrics['outside_kept'], 1)
        self.assertEqual(first.metrics['duplicates'], 1)
        self.assertEqual(self.lib.count(), 2)
        with patch.object(self.lib, 'backup_before_rebuild', side_effect=AssertionError('unnecessary backup')):
            second = self.run_build()
        self.assertEqual(second.metrics['duplicates'], 1)
        self.assertEqual(second.metrics['updated'], 0)
        self.assertTrue(all(path.is_file() for path in (inside, outside)))

    def test_read_failure_prevents_poweroff_and_keeps_prior_rows(self):
        old = self.add_song('old')
        self.run_build()
        (self.songs/'corrupt.mid').write_bytes(b'not a MIDI file')
        result = self.run_build()
        self.assertEqual(result.metrics['failed'], 1)
        self.assertFalse(result.safe_to_shutdown)
        self.assertIsNotNone(self.lib.get(1))
        self.assertTrue(old.is_file())

    def test_shutdown_eligibility_rejects_bad_result_and_background_jobs(self):
        self.add_song('a')
        success=self.run_build()
        app=SimpleNamespace(scanning=False,_cloud_backup_busy=False,_cleanup_busy=False,engine=None,
                            cancel_scan=threading.Event())
        self.assertTrue(shutdown_allowed(app,success,platform='nt'))
        self.assertFalse(shutdown_allowed(app,success,platform='posix'))
        app.scanning=True
        self.assertFalse(shutdown_allowed(app,success,platform='nt'))
        app.scanning=False
        app.engine=object()
        self.assertFalse(shutdown_allowed(app,success,platform='nt'))
        app.engine=None
        app.cancel_scan.set()
        self.assertFalse(shutdown_allowed(app,success,platform='nt'))


if __name__=='__main__':unittest.main()
