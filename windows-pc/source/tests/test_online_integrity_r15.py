"""Streaming-index verification, repair and durable catalog integrity (offline fakes)."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from karaoke.library import SongLibrary
from karaoke.web_drive import (ROOT_NAME, _load_current, sync_web_assets,
                               verify_web_catalog, verify_and_repair_web_catalog)
from tests.test_studio import midi_fixture
from tests.test_v0944_web_sync import FakeWebDrive, StubRenderer


class OnlineIntegrityR15Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.data=self.home/'Data';self.data.mkdir()
        self.cache=self.home/'WebAssets'
        self.song_root=self.home/'Songs';self.song_root.mkdir()
        self.font=self.home/'test.sf2';self.font.write_bytes(b'test-soundfont')
        self.library=SongLibrary(self.data/'songs.sqlite3')
        for n in range(8):
            (self.song_root/f'{99001+n}.mid').write_bytes(midi_fixture())
        self.library.add_files(sorted(self.song_root.glob('*.mid')))
        self.drive=FakeWebDrive()

    def sync(self, **options):
        return sync_web_assets(self.drive,self.library.path,[self.song_root],
                               self.home/'native',{},self.font,self.cache,
                               renderer_factory=StubRenderer,first_batch_size=2,
                               batch_size=4,publish_interval=1000,**options)

    def root(self):
        return self.drive.children('root',ROOT_NAME)[0]['id']

    def test_verified_old_catalog_uses_bucket_listing_not_get_per_song(self):
        self.sync()
        calls={'get':0,'children':0}
        prior_get=self.drive.get_metadata
        prior_children=self.drive.children
        def count_get(fid):
            calls['get']+=1
            return prior_get(fid)
        def count_children(parent,name=None):
            calls['children']+=1
            return prior_children(parent,name)
        self.drive.get_metadata=count_get
        self.drive.children=count_children
        result=self.sync()
        self.assertEqual(result['reused'],8)
        self.assertEqual(result['integrity_checked'],8)
        self.assertEqual(result['integrity_unresolved'],0)
        self.assertLess(calls['get'],12,'Healthy songs must not issue one metadata request per media file')
        self.assertLess(calls['children'],80)

    def test_missing_audio_is_reuploaded_and_catalog_repaired(self):
        self.sync()
        _,pointer,catalog=_load_current(self.drive,self.root())
        before=catalog['songs'][0]
        bad_id=before['audio']['fileId']
        self.drive.files.pop(bad_id)
        self.drive.contents.pop(bad_id)
        self.drive.parent.pop(bad_id)
        result=self.sync()
        self.assertEqual(result['integrity_unresolved'],0)
        self.assertGreaterEqual(result['uploaded_files'],1)
        _,_,catalog=_load_current(self.drive,self.root())
        after=next(r for r in catalog['songs'] if r['webSongId']==before['webSongId'])
        self.assertNotEqual(after['audio']['fileId'],bad_id)
        self.assertEqual(verify_web_catalog(self.drive,self.root())['issues'],[])

    def test_audit_repair_recovers_missing_lyrics_using_existing_source(self):
        self.sync()
        _,_,catalog=_load_current(self.drive,self.root())
        row=catalog['songs'][0]
        bad_id=row['lyrics']['fileId']
        self.drive.files.pop(bad_id)
        self.drive.parent.pop(bad_id)
        self.drive.contents.pop(bad_id)
        before=verify_web_catalog(self.drive,self.root())
        self.assertEqual(len(before['issues']),1)
        repaired=verify_and_repair_web_catalog(self.drive,self.root(),
            self.library.path,[self.song_root],self.home/'native',{},self.font,self.cache,
            renderer_factory=StubRenderer,workers=1)
        self.assertTrue(repaired['complete'])
        self.assertEqual(repaired['repaired'],1)
        self.assertEqual(repaired['checked'],8)

    def test_unrecoverable_foreign_file_is_never_falsely_marked_verified(self):
        self.sync()
        from karaoke.web_drive import _publish
        ptr,current,catalog=_load_current(self.drive,self.root())
        foreign={'webSongId':'foreign','libraryId':'different-machine',
            'sourceId':99999,'sourceSignature':'abc','code':'X999',
            'title':'Foreign','audio':{'fileId':'missing-a','md5':'0'*32},
            'lyrics':{'fileId':'missing-l','md5':'0'*32}}
        _publish(self.drive,self.root(),ptr,current,catalog['songs']+[foreign],self.cache)
        report=verify_and_repair_web_catalog(self.drive,self.root(),
            self.library.path,[self.song_root],self.home/'native',{},self.font,self.cache,
            renderer_factory=StubRenderer,workers=1)
        self.assertFalse(report['complete'])
        self.assertEqual(report['valid'],8)
        self.assertEqual(len(report['issues']),1)

    def test_cancel_audit_keeps_last_current_catalog(self):
        self.sync()
        cancelled=threading.Event()
        before=_load_current(self.drive,self.root())[1]['generation']
        def stop(_msg,*_args): cancelled.set()
        with self.assertRaisesRegex(RuntimeError,'ยกเลิก'):
            verify_web_catalog(self.drive,self.root(),progress=stop,cancel=cancelled)
        self.assertEqual(before,_load_current(self.drive,self.root())[1]['generation'])


if __name__=='__main__':unittest.main()
