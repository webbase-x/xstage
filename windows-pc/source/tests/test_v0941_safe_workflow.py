"""v0.9.41: no copy, read-only duplicate review, bundle-safe deletion, visible-only Drive."""
import json
import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from karaoke.library import SongLibrary,write_json
from karaoke.fast_catalog import build_fast_catalog
from karaoke.duplicate_review import create_review, read_review
from karaoke.duplicate_actions import (hide_exact,show_song,exclude_from_index,
                                      restore_to_index,delete_permanently)
from karaoke.cloud_sync import create_snapshot
from karaoke.google_drive_sync import sync_library
from karaoke.managed_import import ImportSession, PolicyRejected


class Workflow0941Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='xstage-0941-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.source=self.root/'External';self.source.mkdir()
        self.songs=self.root/'Songs';self.songs.mkdir()
        self.data=self.root/'Data';self.data.mkdir()
        self.library=SongLibrary(self.data/'songs.sqlite3')
        write_json(self.data/'settings.json',{});write_json(self.data/'queue.json',[])

    def song(self,name,other=None,artist='X',content=b'\0\0'):
        path=self.source/name
        with wave.open(str(path),'wb') as stream:
            stream.setparams((1,2,8000,0,'NONE','not compressed'))
            stream.writeframes(content*80)
        path.with_suffix('.lrc').write_text(f'[ti:{other or "Same"}]\n[ar:{artist}]\n[00:00.00]test',encoding='utf8')
        return path

    def index_two(self):
        a=self.song('first.wav');b=self.song('second.wav')
        result=build_fast_catalog(self.library,self.source,self.songs,'fast')
        self.assertEqual(self.library.count(),2)
        with self.library.connect() as db:
            rows=[dict(r) for r in db.execute('SELECT * FROM songs ORDER BY id')]
        return a,b,rows,result

    def test_no_automatic_copy_or_hide_even_when_legacy_request_hide(self):
        a,b,rows,result=self.index_two()
        self.assertEqual(result.metrics['duplicates'],1)
        self.assertTrue(all(r['duplicate_of']==0 for r in rows))
        self.assertFalse(any(self.songs.rglob('*')))
        with self.assertRaises(ValueError):
            build_fast_catalog(self.library,self.source,self.songs,'fast',copy_external=True)
        with self.assertRaises(PolicyRejected):
            ImportSession(self.library,self.songs,copy_files=True)
        result2=build_fast_catalog(self.library,self.source,self.songs,'fast',duplicate_policy='hide')
        self.assertEqual(self.library.count(),2)
        self.assertEqual(result2.metrics['duplicates'],1)

    def test_report_then_manual_hide_reindex_and_restore(self):
        a,b,rows,_=self.index_two()
        path=create_review(self.library,verify_exact=False)
        summary=json.loads((path/'summary.json').read_text(encoding='utf-8'))
        self.assertFalse(summary['exact_verified'])
        self.assertEqual(self.library.count(),2)
        report=create_review(self.library,verify_exact=True)
        _,exact=read_review(report,category='exact')
        self.assertEqual(len(exact),1)
        item=exact[0]
        hide_exact(self.library,item['song_id'],item['keeper_id'])
        self.assertEqual(self.library.count(),1)
        build_fast_catalog(self.library,self.source,self.songs,'fast')
        self.assertEqual(self.library.count(),1)
        self.assertEqual(self.library.get(item['song_id'])['duplicate_state'],'manual_hidden')
        show_song(self.library,item['song_id'])
        self.assertEqual(self.library.count(),2)

    def test_remove_from_index_tombstone_no_file_deletion(self):
        a,b,rows,_=self.index_two()
        sid=rows[-1]['id']
        exclude_from_index(self.library,sid)
        self.assertEqual(self.library.count(),1)
        build_fast_catalog(self.library,self.source,self.songs,'fast')
        self.assertEqual(self.library.get(sid)['duplicate_state'],'excluded')
        self.assertTrue(b.exists())
        restore_to_index(self.library,sid)
        self.assertEqual(self.library.count(),2)

    def test_permanent_delete_requires_literal_confirm_and_preserves_keeper(self):
        a,b,rows,_=self.index_two()
        report=create_review(self.library,verify_exact=True)
        _,items=read_review(report,category='exact')
        one=items[0]
        with self.assertRaises(ValueError):
            delete_permanently(self.library,one['song_id'],one['keeper_id'])
        target=Path(self.library.get(one['song_id'])['path'])
        keeper=Path(self.library.get(one['keeper_id'])['path'])
        if os.name != 'nt':
            with self.assertRaises(OSError):
                delete_permanently(self.library,one['song_id'],one['keeper_id'],confirmation='ลบถาวร')
            self.assertTrue(target.exists());self.assertTrue(target.with_suffix('.lrc').exists())
            return
        journal=delete_permanently(self.library,one['song_id'],one['keeper_id'],confirmation='ลบถาวร')
        self.assertFalse(target.exists());self.assertFalse(target.with_suffix('.lrc').exists())
        self.assertTrue(keeper.exists());self.assertTrue(keeper.with_suffix('.lrc').exists())
        self.assertEqual(self.library.get(one['song_id'])['duplicate_state'],'deleted')
        audit=json.loads(journal.read_text(encoding='utf-8'))
        self.assertEqual(audit['status'],'deleted');self.assertEqual(len(audit['deleted']),2)
        self.assertTrue(audit['no_media_backup'])

    def test_reject_deleting_favorite_or_active(self):
        _,_,rows,_=self.index_two()
        selected=rows[-1]['id']; keeper=rows[0]['id']
        with self.assertRaises(ValueError if os.name=='nt' else OSError):
            delete_permanently(self.library,selected,keeper,protected={selected},confirmation='ลบถาวร')
        self.library.favorite(selected)
        with self.assertRaises(ValueError):
            hide_exact(self.library,selected,keeper)

    def test_report_code_only_cannot_be_called_exact(self):
        a=self.song('20120.wav','Title one',content=b'\0\0')
        b=self.song('20120 - other.wav','Title two',content=b'\1\1')
        self.library.upsert_catalog([dict(path=str(a),code='20120',title='Title one',artist='A',kind='Audio',playable=1),
                                    dict(path=str(b),code='20120',title='Title two',artist='B',kind='Audio',playable=1)])
        report=create_review(self.library,verify_exact=True)
        self.assertEqual(read_review(report,category='exact')[0],0)
        self.assertEqual(read_review(report,category='code')[0],1)

    def test_drive_only_visible_bundle_and_song_sidecars(self):
        a,b,rows,_=self.index_two()
        hide_exact(self.library,rows[-1]['id'],rows[0]['id'])
        extraneous=self.source/'orphan.wav';extraneous.write_bytes(b'not indexed')
        mapping={}
        snap=create_snapshot(self.data,self.root/'Drive','owner@example.com',self.source,
                             stage_media=False,media_files_out=mapping)
        manifest=json.loads((snap/'web-manifest.json').read_text(encoding='utf8'))
        self.assertEqual(len(manifest['songs']),1)
        self.assertEqual(len(mapping),2)  # media + LRC, excludes hidden/orphan.
        self.assertFalse(any((snap/'Songs').rglob('*.wav')))
        self.assertTrue(all('External' not in Path(p).name for p in mapping))
        self.assertNotIn(str(self.source),json.dumps(manifest))
        self.assertEqual(json.loads((snap/'manifest.json').read_text(encoding='utf-8'))['song_scope'],'visible')

    def test_drive_snapshot_stages_visible_only_by_default(self):
        a,b,rows,_=self.index_two()
        hide_exact(self.library,rows[-1]['id'],rows[0]['id'])
        snap=create_snapshot(self.data,self.root/'Drive','owner@example.com',self.source)
        self.assertTrue((snap/'Songs'/a.name).is_file())
        self.assertFalse((snap/'Songs'/b.name).exists())
        self.assertTrue((snap/'Songs'/a.with_suffix('.lrc').name).is_file())


if __name__ == '__main__':unittest.main()

class GoogleDriveVisible0941Tests(Workflow0941Tests):
    def test_real_drive_fake_transport_uploads_only_visible_media(self):
        from tests.test_google_drive_sync import FakeDrive
        a,b,rows,_=self.index_two()
        hide_exact(self.library,rows[-1]['id'],rows[0]['id'])
        (self.source/'orphan.mp3').write_bytes(b'unindexed')
        fake=FakeDrive()
        first=sync_library(fake,self.data,'owner@example.com',[self.source],None,'new')
        self.assertIn(a.name,fake.uploaded)
        self.assertIn(a.with_suffix('.lrc').name,fake.uploaded)
        self.assertNotIn(b.name,fake.uploaded)
        self.assertNotIn('orphan.mp3',fake.uploaded)
        self.assertEqual(fake.uploaded[-1],'web-manifest.json')
        fake.uploaded.clear()
        current=fake.inspect('owner@example.com')['latest']
        sync_library(fake,self.data,'owner@example.com',[self.source],None,'update',current)
        self.assertNotIn(a.name,fake.uploaded)
        self.assertEqual(fake.uploaded[-1],'web-manifest.json')
