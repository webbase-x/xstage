"""NCN uses one song record with all dependent MID/LYR/CUR files."""
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from test_studio import midi_fixture
from karaoke.library import SongLibrary, write_json
from karaoke.duplicate_review import create_review,read_review
from karaoke.duplicate_actions import delete_permanently
from karaoke.visible_sync import visible_song_plan
from karaoke.cloud_sync import create_snapshot

class NCN0941Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.data=self.root/'Data';self.data.mkdir()
        self.lib=SongLibrary(self.data/'songs.sqlite3')
        write_json(self.data/'settings.json',{});write_json(self.data/'queue.json',[])

    def song(self, folder, variant=b'\x00'):
        media=self.root/'Song'/folder/'20120.mid'
        lyrics=self.root/'Lyrics'/folder/'20120.lyr'
        cursor=self.root/'Cursor'/folder/'20120.cur'
        for item in (media,lyrics,cursor):item.parent.mkdir(parents=True,exist_ok=True)
        media.write_bytes(midi_fixture())
        lyrics.write_bytes('รักน้องพร\r\nบาซู\r\nEm\r\n.\r\nกข\r\n'.encode('cp874')+variant)
        cursor.write_bytes(struct.pack('<4H',0,0,24,65535))
        self.lib.add_files([media])
        return media,lyrics,cursor

    def test_ncn_bundle_exact_review_and_delete_full_triplet(self):
        files1=self.song('A');files2=self.song('B')
        # First variation intentionally differs; normalize to exact so one
        # complete trio can safely be removed while the keeper survives.
        files2[1].write_bytes(files1[1].read_bytes())
        review=create_review(self.lib,verify_exact=True)
        _,rows=read_review(review,category='exact')
        self.assertEqual(len(rows),1)
        one=rows[0]
        if os.name != 'nt':
            with self.assertRaises(OSError):
                delete_permanently(self.lib,one['song_id'],one['keeper_id'],confirmation='ลบถาวร')
            self.assertEqual(sum(p.exists() for p in files1+files2),6)
            return
        journal=delete_permanently(self.lib,one['song_id'],one['keeper_id'],confirmation='ลบถาวร')
        self.assertEqual(len(json.loads(journal.read_text(encoding='utf-8'))['deleted']),3)
        self.assertEqual(sum(p.exists() for p in files1+files2),3)
        self.assertEqual(self.lib.count(),1)

    def test_changed_lyr_is_not_exact_and_both_sets_are_visible(self):
        self.song('A');self.song('B',variant=b'different')
        review=create_review(self.lib,verify_exact=True)
        self.assertEqual(read_review(review,category='exact')[0],0)
        self.assertEqual(self.lib.count(),2)

    def test_drive_includes_only_visible_complete_ncn_triple(self):
        files=self.song('A')
        songs,media,skipped=visible_song_plan(self.lib.path,[self.root/'Song'])
        self.assertEqual(len(songs),1)
        self.assertEqual(len(media),3)
        self.assertEqual(set(songs[0]['files']),{'media','lyrics','cursor'})
        self.assertEqual(skipped,[])
        snap=create_snapshot(self.data,self.root/'Drive','user@example.com',[self.root/'Song'])
        self.assertEqual(len([p for p in (snap/'Songs').rglob('*') if p.is_file()]),3)
        manifest=json.loads((snap/'web-manifest.json').read_text(encoding='utf-8'))
        self.assertNotIn(str(self.root),json.dumps(manifest))

    def test_missing_ncn_part_skips_entire_bundle(self):
        media,lyr,cur=self.song('A');cur.unlink()
        songs,files,skipped=visible_song_plan(self.lib.path,[self.root/'Song'])
        self.assertEqual(songs,[]);self.assertEqual(files,{})
        self.assertEqual(len(skipped),1)

if __name__=='__main__':unittest.main()
