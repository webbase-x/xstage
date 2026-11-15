import json,sqlite3,tempfile,unittest
from pathlib import Path
from karaoke.cloud_sync import create_snapshot,validate_snapshot
from karaoke.library import SongLibrary,write_json

class CloudSyncTests(unittest.TestCase):
    def test_snapshot_uses_existing_schema_and_is_per_user(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);data=root/'Data';data.mkdir();songs=root/'Songs';songs.mkdir();fx=root/'Fx';fx.mkdir()
            SongLibrary(data/'songs.sqlite3');write_json(data/'settings.json',{'volume':50});write_json(data/'queue.json',[])
            (songs/'one.mid').write_bytes(b'midi');(fx/'room.wav').write_bytes(b'fx')
            snap=create_snapshot(data,root/'Drive','user@example.com',songs,fx)
            self.assertEqual(snap.parent.name,'user@example.com');self.assertTrue((snap/'database/songs.sqlite3').is_file())
            self.assertFalse((snap/'Songs/one.mid').exists());self.assertEqual(validate_snapshot(snap)['songs'],0)

    def test_snapshot_rejects_missing_google_user(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):create_snapshot(Path(d),Path(d),'',None,None)

    def test_snapshot_sanitizes_google_user_folder(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);data=root/'Data';data.mkdir()
            SongLibrary(data/'songs.sqlite3');write_json(data/'settings.json',{});write_json(data/'queue.json',[])
            snap=create_snapshot(data,root/'Drive','user/../unsafe@example.com',None,None)
            self.assertEqual(snap.parent.name,'user_.._unsafe@example.com')

    def test_snapshot_writes_relative_song_path_and_no_temp_remains(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);data=root/'Data';data.mkdir();songs=root/'Library';(songs/'MP3').mkdir(parents=True)
            SongLibrary(data/'songs.sqlite3');write_json(data/'settings.json',{});write_json(data/'queue.json',[])
            (songs/'MP3'/'001.mp3').write_bytes(b'a')
            snap=create_snapshot(data,root/'Drive','user@example.com',songs,None)
            manifest=json.loads((snap/'web-manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(list(manifest['songs']),[])
            self.assertFalse(any('.tmp-' in p.name for p in snap.parent.iterdir()))

    def test_reserved_windows_user_name_rejected(self):
        with self.assertRaises(ValueError):
            create_snapshot(Path(tempfile.mkdtemp()),Path(tempfile.mkdtemp()),'CON',None,None)

    def test_snapshot_copies_multiple_song_roots(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);data=root/'Data';data.mkdir();one=root/'One';two=root/'Two'
            (one/'a').mkdir(parents=True);(two/'b').mkdir(parents=True)
            (one/'a'/'one.mp3').write_bytes(b'1');(two/'b'/'two.mp3').write_bytes(b'2')
            SongLibrary(data/'songs.sqlite3');write_json(data/'settings.json',{});write_json(data/'queue.json',[])
            snap=create_snapshot(data,root/'Drive','user@example.com',[one,two],None)
            self.assertFalse((snap/'Songs/Source01/a/one.mp3').exists())
            self.assertFalse((snap/'Songs/Source02/b/two.mp3').exists())

    def test_nested_song_roots_are_not_copied_twice(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);data=root/'Data';data.mkdir();parent=root/'Library';child=parent/'VIP'
            child.mkdir(parents=True);(parent/'main.mp3').write_bytes(b'1');(child/'vip.mp3').write_bytes(b'2')
            SongLibrary(data/'songs.sqlite3');write_json(data/'settings.json',{});write_json(data/'queue.json',[])
            snap=create_snapshot(data,root/'Drive','user@example.com',[parent,child],None)
            self.assertFalse((snap/'Songs/main.mp3').exists())
            self.assertFalse((snap/'Songs/VIP/vip.mp3').exists())
            self.assertFalse((snap/'Songs/Source01').exists())

    def test_snapshots_created_back_to_back_get_unique_roots(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);data=root/'Data';data.mkdir()
            SongLibrary(data/'songs.sqlite3');write_json(data/'settings.json',{});write_json(data/'queue.json',[])
            first=create_snapshot(data,root/'Drive','user@example.com',None,None)
            second=create_snapshot(data,root/'Drive','user@example.com',None,None)
            self.assertNotEqual(first,second)

    def test_duplicate_song_roots_are_copied_once(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);data=root/'Data';data.mkdir();songs=root/'Library';songs.mkdir()
            (songs/'same.mp3').write_bytes(b'a')
            SongLibrary(data/'songs.sqlite3');write_json(data/'settings.json',{});write_json(data/'queue.json',[])
            snap=create_snapshot(data,root/'Drive','user@example.com',[songs,songs],None)
            self.assertFalse((snap/'Songs/same.mp3').exists())
            self.assertFalse((snap/'Songs/Source01').exists())

if __name__=='__main__':unittest.main()
