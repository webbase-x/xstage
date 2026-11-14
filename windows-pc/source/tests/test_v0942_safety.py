"""Safety regressions for v0.9.42; all media operations use temporary fixtures."""
import json
import os
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from karaoke.library import SongLibrary, SearchReader, write_json
from karaoke.quick_catalog import build_quick_catalog
from karaoke.duplicate_actions import (hide_exact, exclude_from_index,
    delete_permanently, action_batch)
from karaoke.cloud_sync import create_snapshot, validate_snapshot, stage_snapshot
from karaoke.duplicate_dialog import DuplicateReviewWindow
from karaoke.duplicate_review import create_review, read_review
from karaoke.visible_sync import visible_song_plan
from karaoke.google_drive_sync import sync_library
from tests.test_google_drive_sync import FakeDrive


class Safety0942(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='xstage-0942-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.data = self.root / 'Data'; self.data.mkdir()
        self.source = self.root / 'External'; self.source.mkdir()
        self.songs = self.root / 'Songs'; self.songs.mkdir()
        self.library = SongLibrary(self.data / 'songs.sqlite3')
        write_json(self.data / 'settings.json', {})
        write_json(self.data / 'queue.json', [])

    def fixture(self, filename, content=b'1234'):
        path = self.source / filename
        with wave.open(str(path), 'wb') as file:
            file.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            file.writeframes(content*30)
        path.with_suffix('.lrc').write_text('[ti:Same]\n[ar:X]\n[00:00.00]Line', encoding='utf8')
        return path

    def two(self):
        a=self.fixture('a.wav');b=self.fixture('b.wav')
        self.library.add_files([a,b])
        with self.library.connect() as db:
            rows=[dict(row) for row in db.execute('SELECT * FROM songs ORDER BY id')]
        return a,b,sorted(rows,key=lambda x:x['id'])

    def test_quick_scan_preserves_manual_hide_after_source_change(self):
        a,b,rows=self.two()
        hide_exact(self.library,rows[1]['id'],rows[0]['id'])
        b.write_bytes(b.read_bytes()+b'abc')
        build_quick_catalog(self.library,self.source,self.songs)
        self.assertEqual(self.library.get(rows[1]['id'])['duplicate_state'],'manual_hidden')
        self.assertEqual(self.library.count(),1)
        reader=SearchReader(self.library.path)
        try:
            self.assertEqual(len(reader.search()),1)
        finally:
            reader.close()

    def test_quick_scan_preserves_manual_hide_even_if_missing_temporarily(self):
        a,b,rows=self.two();hidden=rows[1]['id']
        hide_exact(self.library,hidden,rows[0]['id'])
        original=b.read_bytes();b.unlink()
        build_quick_catalog(self.library,self.source,self.songs)
        self.assertEqual(self.library.get(hidden)['duplicate_state'],'manual_hidden')
        b.write_bytes(original)
        build_quick_catalog(self.library,self.source,self.songs)
        self.assertEqual(self.library.get(hidden)['duplicate_state'],'manual_hidden')

    def test_incomplete_audio_bundle_report_does_not_modify_song(self):
        a=self.fixture('a.wav');self.library.add_files([a]);a.unlink()
        report=create_review(self.library)
        count, rows=read_review(report,category='incomplete')
        self.assertEqual(count,1)
        self.assertEqual(rows[0]['keeper_id'],0)
        self.assertIn('ไม่พบไฟล์',rows[0]['keeper_path'])
        self.assertEqual(self.library.count(),1)  # read-only report does not hide it

    def test_snapshot_web_manifest_tampering_is_detected(self):
        a=self.fixture('a.wav');self.library.add_files([a])
        snap=create_snapshot(self.data,self.root/'Drive','owner@example.com',self.source)
        web=snap/'web-manifest.json'
        web.write_bytes(web.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'SHA-256'):
            validate_snapshot(snap)

    def test_snapshot_missing_media_is_not_restore_ready(self):
        a,b,rows=self.two()
        snap=create_snapshot(self.data,self.root/'Drive','owner@example.com',self.source)
        result=validate_snapshot(snap)
        self.assertTrue(result['media_verified'])
        self.assertEqual(result['media_files'],4)
        next((snap/'Songs').rglob('*.wav')).unlink()
        with self.assertRaises((ValueError,OSError)):
            validate_snapshot(snap)

    def test_snapshot_tampered_media_is_not_restore_ready(self):
        self.fixture('a.wav');self.library.add_files([self.source/'a.wav'])
        snap=create_snapshot(self.data,self.root/'Drive','owner@example.com',self.source)
        target=next((snap/'Songs').rglob('*.wav'))
        target.write_bytes(target.read_bytes()+b'corrupt')
        with self.assertRaisesRegex(ValueError,'SHA-256'):
            validate_snapshot(snap)

    def test_snapshot_api_staging_requires_uploaded_media_before_validation(self):
        self.fixture('a.wav');self.library.add_files([self.source/'a.wav'])
        snap=create_snapshot(self.data,self.root/'Drive','owner@example.com',self.source,stage_media=False)
        self.assertFalse(any((snap/'Songs').rglob('*.wav')))
        with self.assertRaises((ValueError,OSError)):
            validate_snapshot(snap)

    def test_snapshot_with_media_cannot_stage_only_original_absolute_database_paths(self):
        self.fixture('a.wav');self.library.add_files([self.source/'a.wav'])
        snap=create_snapshot(self.data,self.root/'Drive','owner@example.com',self.source)
        with self.assertRaisesRegex(ValueError,'พาธ'):
            stage_snapshot(snap,self.root/'Other')

    def test_empty_media_snapshot_is_valid(self):
        snap=create_snapshot(self.data,self.root/'Drive','owner@example.com',self.source)
        self.assertEqual(validate_snapshot(snap)['media_files'],0)

    def test_all_song_bundles_share_one_inspector_when_sync_plan_is_built(self):
        paths=[self.fixture(f'{n:03d}.wav') for n in range(15)]
        self.library.add_files(paths)
        from karaoke import visible_sync
        observed=[]
        orig=visible_sync.bundle
        def record(path, inspector):
            observed.append(id(inspector))
            return orig(path, inspector)
        with patch.object(visible_sync,'bundle',side_effect=record):
            songs,files,skipped=visible_song_plan(self.library.path,self.source)
        self.assertEqual(len(songs),15)
        self.assertEqual(len(files),30)
        self.assertEqual(len(set(observed)),1)

    def test_action_batch_creates_one_database_backup_for_two_exclusions(self):
        a,b,rows=self.two()
        with patch.object(self.library,'backup_before_rebuild', wraps=self.library.backup_before_rebuild) as backup:
            with action_batch(self.library):
                exclude_from_index(self.library,rows[0]['id'])
                exclude_from_index(self.library,rows[1]['id'])
        self.assertEqual(backup.call_count,1)
        self.assertEqual(self.library.count(),0)

    def test_permanent_delete_fails_closed_on_non_windows(self):
        if os.name=='nt':self.skipTest('Windows-native test separately checks actual handle deletion')
        a,b,rows=self.two()
        with self.assertRaises(OSError):
            delete_permanently(self.library,rows[1]['id'],rows[0]['id'],confirmation='ลบถาวร')
        self.assertTrue(a.exists() and b.exists())
        self.assertEqual(self.library.count(),2)

    def test_ui_action_reports_one_success_and_one_failure(self):
        app=SimpleNamespace(scanning=False, library=self.library)
        recorded=[]
        app.start_index_job=lambda worker,**_:recorded.append(worker())
        dummy=SimpleNamespace(app=app, busy=False, _validate_report_row=lambda row:None)
        def op(row):
            if row['song_id']==2: raise RuntimeError('denied')
            return 'ok'
        DuplicateReviewWindow.run_actions(dummy,op,[{'song_id':1},{'song_id':2}])
        self.assertEqual(recorded[0][:2],(1,1))

    def test_ui_action_rejects_stale_id_or_path_from_report(self):
        a,b,rows=self.two()
        dummy=SimpleNamespace(app=SimpleNamespace(library=self.library))
        item={'song_id':rows[1]['id'],'path':str(b)+'-wrong',
              'keeper_id':rows[0]['id'],'keeper_path':str(a)}
        with self.assertRaisesRegex(ValueError,'ล้าสมัย'):
            DuplicateReviewWindow._validate_report_row(dummy,item)

    def test_drive_metadata_verification_detects_remote_corruption(self):
        class CorruptDrive(FakeDrive):
            def children(self,parent,name=None):
                records=super().children(parent,name)
                for r in records:
                    if r['name']=='a.wav' and r.get('md5Checksum'):
                        r['md5Checksum']='0'*32
                return records
        a=self.fixture('a.wav');self.library.add_files([a])
        with self.assertRaisesRegex(RuntimeError,'MD5'):
            sync_library(CorruptDrive(),self.data,'owner@example.com',[self.source],None,'new')

    def test_drive_source_changed_during_upload_blocks_manifest(self):
        a=self.fixture('a.wav');self.library.add_files([a])
        class MutatingDrive(FakeDrive):
            def _upload(self,path,parent,existing=None):
                item=super()._upload(path,parent,existing)
                # Compare the same on-disk file, not spellings of Windows
                # junction/8.3 paths: the sync planner canonicalizes paths.
                if Path(path).resolve() == a.resolve():
                    with a.open('ab') as fp:fp.write(b'changed')
                return item
        drive=MutatingDrive()
        with self.assertRaisesRegex(RuntimeError,'เปลี่ยน'):
            sync_library(drive,self.data,'owner@example.com',[self.source],None,'new')
        self.assertNotIn('web-manifest.json',drive.uploaded)

    @unittest.skipUnless(os.name=='nt','requires Windows NTFS for a real handle-bound deletion test')
    def test_windows_handle_delete_detects_file_swapped_after_review(self):
        from karaoke.verified_delete import delete_verified
        import hashlib
        path=self.root/'native_delete.tmp';path.write_bytes(b'original')
        stat=path.stat()
        proof=dict(path=str(path),device=stat.st_dev,inode=stat.st_ino,
                   size=stat.st_size,mtime=stat.st_mtime_ns,sha256=hashlib.sha256(b'original').hexdigest())
        path.write_bytes(b'replaced')
        with self.assertRaises(ValueError):delete_verified(proof)
        self.assertEqual(path.read_bytes(),b'replaced')

    @unittest.skipUnless(os.name=='nt','requires Windows NTFS for a real handle-bound deletion test')
    def test_windows_handle_delete_removes_exact_matching_file(self):
        from karaoke.verified_delete import delete_verified
        import hashlib
        path=self.root/'native_delete.tmp';path.write_bytes(b'original')
        stat=path.stat()
        proof=dict(path=str(path),device=stat.st_dev,inode=stat.st_ino,
                   size=stat.st_size,mtime=stat.st_mtime_ns,sha256=hashlib.sha256(b'original').hexdigest())
        delete_verified(proof)
        self.assertFalse(path.exists())

if __name__=='__main__':unittest.main()
