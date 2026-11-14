"""Web asset transactional sync regressions, entirely synthetic; no real Drive."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from karaoke.library import SongLibrary
from karaoke.web_assets import signature, lyrics_document
from karaoke.web_drive import ROOT_NAME, sync_web_assets
from tests.test_studio import midi_fixture


class FakeWebDrive:
    def __init__(self):
        self.files = {'root':{'id':'root','name':'My Drive','mimeType':'application/vnd.google-apps.folder'}}
        self.parent = {}
        self.contents = {}
        self.uploads = []
        self.fail_suffix = None
        self.sequence = 0
    def children(self, parent, name=None):
        return [dict(self.files[k]) for k,p in self.parent.items() if p == parent
                and (name is None or self.files[k]['name'] == name)]
    def folder(self, parent, name):
        existing = self.children(parent, name)
        if existing:
            return existing[0]
        return self.create(parent,name,b'',folder=True)
    def create(self, parent, name, blob, folder=False, existing=None):
        self.sequence += 1
        file_id = existing['id'] if existing else 'file-'+str(self.sequence).zfill(6)
        item = {'id':file_id,'name':name,
                'mimeType':'application/vnd.google-apps.folder' if folder else 'application/json' if name.endswith('.json') else 'audio/mp4',
                'md5Checksum':hashlib.md5(blob).hexdigest(), 'size':str(len(blob))}
        self.files[file_id] = item;self.parent[file_id]=parent;self.contents[file_id]=blob
        if not folder:self.uploads.append(name)
        return dict(item)
    def _upload(self, path, parent, existing=None):
        if self.fail_suffix and str(path).endswith(self.fail_suffix):
            raise OSError('simulated upload interruption')
        return self.create(parent,Path(path).name,Path(path).read_bytes(),existing=existing)
    def get_metadata(self, file_id):
        return self.files.get(file_id,{})
    def download(self, file_id):
        return self.contents[file_id]
    def check_cancelled(self):pass

class StubRenderer:
    builds = 0
    def __init__(self, native, settings, font, cache_dir, ffmpeg='ffmpeg'):
        self.font=font; self.settings=settings; self.cache=Path(cache_dir)
    def __enter__(self):return self
    def __exit__(self,*_):pass
    def build(self, song, parts, cancel=None):
        type(self).builds += 1
        sig=signature(parts,self.font,self.settings)
        dest=self.cache/sig[:2];dest.mkdir(parents=True,exist_ok=True)
        a=dest/(str(song['code'])+'-'+sig[:20]+'.m4a')
        l=dest/(str(song['code'])+'-'+sig[:20]+'.json')
        a.write_bytes(b'FAKE-M4A-TEST-DATA'*60)
        l.write_text(json.dumps({'schemaVersion':1, 'id':str(song['code']),'duration':2,'lines':[]}), encoding='utf-8')
        return sig,a,l,2.

class Web0944Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.data=self.root/'Data';self.data.mkdir()
        self.music=self.root/'Songs';self.music.mkdir()
        self.font=self.root/'quality.sf2';self.font.write_bytes(b'fake-font-content')
        self.library=SongLibrary(self.data/'songs.sqlite3')
        self.drive=FakeWebDrive();self.cache=self.root/'cache'
        StubRenderer.builds=0
    def song(self,name='90001.mid'):
        item=self.music/name
        item.write_bytes(midi_fixture())
        self.library.add_files([item]);return item
    def run_sync(self):
        return sync_web_assets(self.drive,self.library.path,[self.music],
            self.root/'native',{},self.font,self.cache,renderer_factory=StubRenderer)
    def test_new_upload_then_repeat_does_not_render_or_upload(self):
        self.song()
        first=self.run_sync()
        self.assertEqual(first['total'],1)
        self.assertEqual(StubRenderer.builds,1)
        uploads=len(self.drive.uploads)
        second=self.run_sync()
        self.assertEqual(second['reused'],1)
        self.assertEqual(StubRenderer.builds,1)
        # Unchanged Drive catalog needs no re-publication.
        self.assertEqual(len(self.drive.uploads)-uploads,0)
    def test_restart_after_media_uploaded_without_catalog_reuses_files(self):
        self.song()
        self.drive.fail_suffix='current.json'
        with self.assertRaises(OSError):self.run_sync()
        uploaded_media=sum(n.endswith(('.json','.m4a')) and '90001-' in n for n in self.drive.uploads)
        self.assertEqual(uploaded_media,2)
        self.drive.fail_suffix=None
        result=self.run_sync()
        self.assertEqual(result['uploaded_files'],0)
        self.assertEqual(result['total'],1)
    def test_failed_song_does_not_enter_published_catalog(self):
        self.song()
        self.drive.fail_suffix='.m4a'
        with self.assertRaisesRegex(RuntimeError, 'อัปโหลดล้มเหลวทั้งหมด'):
            self.run_sync()
        root=self.drive.children('root',ROOT_NAME)[0]['id']
        self.assertFalse(self.drive.children(root,'current.json'))
    def test_existing_remote_catalog_survives_new_job(self):
        self.song()
        self.run_sync()
        old_pointer=[x for x in self.drive.children(next(x['id'] for x in self.drive.children('root', ROOT_NAME)),'current.json')][0]
        catalog=json.loads(self.drive.download(json.loads(self.drive.download(old_pointer['id']))['catalogFileId']))
        self.assertEqual(catalog['totalSongs'],1)
        self.song('90002.mid')
        result=self.run_sync()
        self.assertEqual(result['total'],2)
        self.assertEqual(result['reused'],1)
    def test_cancellation_preserves_old_pointer(self):
        self.song();self.run_sync()
        root=self.drive.children('root',ROOT_NAME)[0]['id']
        pointer=self.drive.children(root,'current.json')[0]
        before=self.drive.download(pointer['id'])
        import threading
        flag=threading.Event();flag.set()
        with self.assertRaises(RuntimeError):
            sync_web_assets(self.drive,self.library.path,[self.music],self.root/'native',{},
                            self.font,self.cache,cancel=flag,renderer_factory=StubRenderer)
        self.assertEqual(before,self.drive.download(pointer['id']))
    def test_existing_invalid_current_is_not_overwritten(self):
        self.song();root=self.drive.folder('root',ROOT_NAME)['id']
        self.drive.create(root,'current.json',b'{"schemaVersion":99}')
        with self.assertRaisesRegex(ValueError,'current.json'):
            self.run_sync()
    def test_never_upload_sqlite_queue_or_original_midi(self):
        self.song();self.run_sync()
        self.assertFalse(any(name.endswith(('.mid','.sqlite3')) or name=='queue.json'
                             for name in self.drive.uploads))
    def test_lyrics_schema_does_not_invent_syllable_times(self):
        from karaoke.lyrics import Lyrics,LyricLine
        from types import SimpleNamespace
        obj=lyrics_document({'code':'01','title':'ไทย','artist':'ก'},None,
                            Lyrics([LyricLine(1.,'ไทย',[])]),3.)
        self.assertEqual(obj['lines'][0]['syllables'],[])
        self.assertEqual(obj['title'],'ไทย')

    def test_changed_source_replaces_catalog_entry_without_remote_delete(self):
        media=self.song()
        self.run_sync()
        first_m4a=len([x for x in self.drive.uploads if x.endswith('.m4a')])
        media.write_bytes(media.read_bytes()+b'changed')
        result=self.run_sync()
        self.assertEqual(result['total'],1)
        self.assertEqual(len([x for x in self.drive.uploads if x.endswith('.m4a')]),first_m4a+1)
        # Old M4A is intentionally not deleted from Drive.
        self.assertEqual(len([x for x in self.drive.files.values() if x['name'].endswith('.m4a')]),2)

    def test_manual_hidden_removes_only_own_catalog_listing(self):
        self.song();self.run_sync()
        with self.library.connect() as db:
            db.execute("UPDATE songs SET duplicate_state='manual_hidden'")
        result=self.run_sync()
        self.assertEqual(result['total'],0)
        self.assertTrue(any(x['name'].endswith('.m4a') for x in self.drive.files.values()))

    def test_web_sync_closes_every_sqlite_connection_on_success_and_hide(self):
        """Regression: Windows cannot remove a database while any handle is open."""
        import sqlite3
        self.song()
        raw_connect = sqlite3.connect
        opened = []

        class TrackedConnection(sqlite3.Connection):
            closed_explicitly = False
            def close(self):
                self.closed_explicitly = True
                return super().close()

        def tracked_connect(*args, **kwargs):
            kwargs['factory'] = TrackedConnection
            db = raw_connect(*args, **kwargs)
            opened.append(db)
            return db

        with patch('sqlite3.connect', side_effect=tracked_connect):
            self.run_sync()
            with self.library.connect() as db:
                db.execute("UPDATE songs SET duplicate_state='manual_hidden'")
            self.run_sync()
        self.assertGreater(len(opened), 1)
        self.assertTrue(all(db.closed_explicitly for db in opened),
                        'Web Sync left at least one SQLite handle open')

    def test_web_sync_closes_sqlite_connection_on_early_upload_failure(self):
        """An interrupted upload must not retain a library database handle."""
        import sqlite3
        self.song()
        raw_connect = sqlite3.connect
        opened = []

        class TrackedConnection(sqlite3.Connection):
            closed_explicitly = False
            def close(self):
                self.closed_explicitly = True
                return super().close()

        def tracked_connect(*args, **kwargs):
            kwargs['factory'] = TrackedConnection
            db = raw_connect(*args, **kwargs)
            opened.append(db)
            return db

        self.drive.fail_suffix = '.m4a'
        with patch('sqlite3.connect', side_effect=tracked_connect):
            with self.assertRaisesRegex(RuntimeError, 'อัปโหลดล้มเหลวทั้งหมด'):
                self.run_sync()
        self.assertGreater(len(opened), 0)
        self.assertTrue(all(db.closed_explicitly for db in opened),
                        'An aborted Web Sync left SQLite handles open')

    def test_user_oauth_client_secret_filename_is_supported(self):
        from karaoke.google_drive_sync import load_client
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'client_secret_123.apps.googleusercontent.com.json').write_text(
                json.dumps({'installed':{'client_id':'desktop.apps.googleusercontent.com',
                                          'client_secret':'local-only-value'}}),encoding='utf-8')
            self.assertEqual(load_client(root,root)[0],'desktop.apps.googleusercontent.com')
            (root/'google-oauth-client.json').write_text(
                json.dumps({'web':{'client_id':'web.apps.googleusercontent.com'}}),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'Web Client'):
                load_client(root,root)

if __name__=='__main__':unittest.main()

class Web0945WorkflowTests(unittest.TestCase):
    setUp = Web0944Tests.setUp
    song = Web0944Tests.song
    run_sync = Web0944Tests.run_sync
    """Verify actual UI-required upload/render overlap and late catalog publishing."""
    def test_render_next_song_during_previous_audio_upload(self):
        import threading
        self.song('90001.mid'); self.song('90002.mid')
        upload_started = threading.Event()
        second_started = threading.Event()

        class OverlapDrive(FakeWebDrive):
            def _upload(self, path, parent, existing=None):
                if str(path).endswith('.m4a') and not upload_started.is_set():
                    upload_started.set()
                    if not second_started.wait(5):
                        raise RuntimeError('render of song 2 did not overlap song 1 upload')
                return super()._upload(path, parent, existing)
        class OverlapRenderer(StubRenderer):
            def build(self, song, parts, cancel=None):
                if song['code']=='90002':
                    if not upload_started.wait(5):
                        raise RuntimeError('song 2 conversion never saw upload of song 1')
                    second_started.set()
                return super().build(song, parts, cancel=cancel)
        self.drive=OverlapDrive()
        result=sync_web_assets(self.drive,self.library.path,[self.music],
            self.root/'native',{},self.font,self.cache,renderer_factory=OverlapRenderer,workers=1)
        self.assertEqual(result['total'], 2)
        self.assertTrue(upload_started.is_set() and second_started.is_set())
        local=json.loads((self.cache/'database.json').read_text(encoding='utf-8'))
        self.assertEqual(local['totalSongs'],2)
        root=self.drive.children('root',ROOT_NAME)[0]['id']
        pointer=json.loads(self.drive.download(self.drive.children(root,'current.json')[0]['id']))
        published=json.loads(self.drive.download(pointer['catalogFileId']))
        self.assertEqual([s['code'] for s in local['songs']], [s['code'] for s in published['songs']])

    def test_failed_pointer_does_not_replace_local_active_catalog(self):
        self.song()
        self.drive.fail_suffix='current.json'
        with self.assertRaises(OSError):self.run_sync()
        self.assertFalse((self.cache/'current.json').exists())
        self.assertFalse((self.cache/'database.json').exists())
        self.assertTrue(any((self.cache/'catalogs').glob('database-*.json')))
