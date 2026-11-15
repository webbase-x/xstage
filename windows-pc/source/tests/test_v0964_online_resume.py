"""Crash recovery and verified media reuse for X-Stage Windows Online.

These tests use a local fake Drive and do not upload any user's songs.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from karaoke.web_resume import OnlineSyncRecovery, FILE_NAME
from tests.test_v0944_web_sync import FakeWebDrive, StubRenderer
from karaoke.web_drive import sync_web_assets
from karaoke.library import SongLibrary
from tests.test_studio import midi_fixture


class RecoveryStateTests(unittest.TestCase):
    def test_restart_remembers_progress_and_choices_without_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = OnlineSyncRecovery(root)
            work.begin(song_types={'MIDI'}, font='C:/SoundFonts/quality.sf2', total=35)
            work.phase(4, 'กำลังอัปโหลดไฟล์')
            work.progress('อัปโหลดครบแล้ว 12 เพลง', 12, 35)
            checkpoint = root / FILE_NAME
            text = checkpoint.read_text(encoding='utf-8')
            self.assertNotIn('refresh_token', text)
            self.assertNotIn('access_token', text)
            reopened = OnlineSyncRecovery(root)
            self.assertTrue(reopened.interrupted())
            self.assertEqual(reopened.state['step'], 4)
            self.assertEqual(reopened.state['song_types'], ['MIDI'])
            self.assertEqual(reopened.state['font'], 'C:/SoundFonts/quality.sf2')
            self.assertIn('ซิงค์ต่อจากครั้งก่อน', reopened.describe())
            self.assertEqual(reopened.state['total'], 35)

    def test_cancel_is_resumable_but_complete_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=OnlineSyncRecovery(tmp)
            state.begin(song_types={'MIDI','NCN'}, total=8)
            state.finish('cancelled', 'หยุด')
            self.assertTrue(OnlineSyncRecovery(tmp).interrupted())
            state.begin(song_types={'NCN'},total=8)
            state.finish('completed','เสร็จ')
            self.assertFalse(OnlineSyncRecovery(tmp).interrupted())

    def test_corrupt_saved_marker_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/FILE_NAME
            path.write_bytes(b'{"schema":999,"status":"running"}')
            self.assertIsNone(OnlineSyncRecovery(tmp).state)
            self.assertEqual(path.read_bytes(),b'{"schema":999,"status":"running"}')

    def test_rescanning_does_not_erase_interrupted_upload_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=OnlineSyncRecovery(tmp)
            state.begin(song_types={'NCN'},total=999)
            state.progress('completed 450',450,999)
            state.scanning(done=1,total=999)
            self.assertEqual(OnlineSyncRecovery(tmp).state['done'],450)


class JournalResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.songs=self.root/'Songs';self.songs.mkdir()
        self.data=self.root/'Data';self.data.mkdir()
        self.font=self.root/'quality.sf2';self.font.write_bytes(b'quality')
        self.catalog=SongLibrary(self.data/'songs.sqlite3')
        self.drive=FakeWebDrive()
        self.cache=self.root/'cache'
        StubRenderer.builds=0
        music=self.songs/'91001.mid'
        music.write_bytes(midi_fixture())
        self.catalog.add_files([music])

    def sync(self):
        return sync_web_assets(self.drive,self.catalog.path,[self.songs],
                self.root/'native',{},self.font,self.cache,renderer_factory=StubRenderer)

    def test_crash_after_verified_media_before_publish_skips_rerender(self):
        self.drive.fail_suffix='current.json'
        with self.assertRaises(OSError):self.sync()
        self.assertEqual(StubRenderer.builds,1)
        self.drive.fail_suffix=None
        r=self.sync()
        self.assertEqual(r['uploaded_files'],0)
        self.assertEqual(r['reused'],1)
        self.assertEqual(StubRenderer.builds,1, 'Interrupted upload must not reconvert completed song')
        self.assertEqual(r['total'],1)

    def test_missing_remote_media_forces_safe_reconversion(self):
        self.drive.fail_suffix='current.json'
        with self.assertRaises(OSError):self.sync()
        self.drive.fail_suffix=None
        remote=[id for id,item in self.drive.files.items() if item['name'].endswith('.m4a')]
        self.assertEqual(len(remote),1)
        self.drive.files[remote[0]]['md5Checksum']='incorrect-remote-md5'
        r=self.sync()
        self.assertEqual(StubRenderer.builds,2, 'Must re-render when verified remote data is missing/corrupt')
        self.assertEqual(r['total'],1)

    def test_source_change_never_uses_stale_journal_entry(self):
        self.drive.fail_suffix='current.json'
        with self.assertRaises(OSError):self.sync()
        self.drive.fail_suffix=None
        song=self.songs/'91001.mid'
        song.write_bytes(song.read_bytes()+b'changed')
        r=self.sync()
        self.assertEqual(StubRenderer.builds,2)
        self.assertEqual(r['total'],1)

class ScalableJournalTests(unittest.TestCase):
    def test_many_records_are_incremental_and_survive_restart(self):
        from karaoke.web_resume import VerifiedUploadJournal
        with tempfile.TemporaryDirectory() as tmp:
            with VerifiedUploadJournal(tmp,'private-root-one') as journal:
                for i in range(600):
                    journal[str(i)] = {'state':'uploaded','signature':'s'+str(i),
                                       'row':{'webSongId':str(i),'audio':{'fileId':'audio'+str(i)}}}
            with VerifiedUploadJournal(tmp,'private-root-one') as journal:
                self.assertEqual(journal.get('599')['row']['audio']['fileId'],'audio599')
                self.assertEqual(journal.get('0')['signature'],'s0')
                self.assertIsNone(journal.get('600'))
                self.assertTrue(journal.path.name.endswith('.sqlite3'))
            with VerifiedUploadJournal(tmp,'another-account-root') as different:
                self.assertIsNone(different.get('599'))

    def test_legacy_json_recovery_is_imported_once(self):
        from karaoke.web_resume import VerifiedUploadJournal
        with tempfile.TemporaryDirectory() as tmp:
            client=VerifiedUploadJournal(tmp,'old-root')
            client.legacy_path.parent.mkdir(parents=True,exist_ok=True)
            client.legacy_path.write_text(json.dumps({
                'song':{'state':'uploaded','signature':'hash','row':{'webSongId':'song'}},
                'old-song':{'state':'uploaded','signature':'oldhash'}
            }),encoding='utf-8')
            with VerifiedUploadJournal(tmp,'old-root') as recovered:
                self.assertEqual(recovered.get('song')['signature'],'hash')
                self.assertIsNone(recovered.get('old-song'))
            with VerifiedUploadJournal(tmp,'old-root') as again:
                self.assertIsNotNone(again.get('song'))


class LocalQueueDurabilityTests(unittest.TestCase):
    def test_song_catalog_and_queue_survive_recreation(self):
        from karaoke.library import SongQueue, QueueItem
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)
            media=data/'a.mid';media.write_bytes(midi_fixture())
            lib=SongLibrary(data/'songs.sqlite3')
            lib.add_files([media])
            song=lib.search('a')[0]
            queue=SongQueue(data/'queue.json')
            queue.add(QueueItem(int(song['id'])))
            self.assertEqual(SongQueue(data/'queue.json').items[0].song_id,song['id'])
            self.assertTrue(SongLibrary(data/'songs.sqlite3').has_songs())

    def test_atomic_checkpoint_failure_preserves_last_committed_marker(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            first=OnlineSyncRecovery(tmp)
            first.begin(song_types={'MIDI'},total=100)
            old=Path(tmp,FILE_NAME).read_bytes()
            with patch('karaoke.web_resume.os.replace',side_effect=OSError('power failed')):
                with self.assertRaisesRegex(OSError,'power failed'):
                    first.finish('completed','end')
            self.assertEqual(Path(tmp,FILE_NAME).read_bytes(),old)

if __name__=='__main__':unittest.main()
