from contextlib import closing
import os
import shutil
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from karaoke.library import SongLibrary,canonical
from karaoke.lister import build_list
from karaoke.incremental import READER_REVISION
from karaoke.ingest import Inspector
from test_studio import midi_fixture,dbf_fixture

class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.db=SongLibrary(self.root/'data/songs.db')
    def tearDown(self):self.temp.cleanup()
    def song(self,name='songs/001 - เพลงหลัก - นักร้อง.mid',padding=0):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(midi_fixture()+b'\0'*padding);return path
    def run_roots(self,*folders,force=False,cancelled=None,protected=(),callback=None):
        events=[]
        def emit(event):
            events.append(dict(event))
            if callback:callback(event)
        result=build_list(self.db,[{'path':str(f),'type':'ทุกประเภท'} for f in folders],
            force=force,events=emit,cancelled=cancelled,protected=protected)
        return result,events
    def record(self,path):
        with self.db.connect() as db:return dict(db.execute('SELECT * FROM songs WHERE path=?',(canonical(path),)).fetchone())
    def items(self,events):return [e for e in events if e.get('type')=='item']
    def test_second_import_skips_metadata_and_hash_reads(self):
        path=self.song();self.run_roots(path.parent)
        with patch('karaoke.incremental.content_key',side_effect=AssertionError('must not hash unchanged file')), \
             patch.object(Inspector,'inspect',side_effect=AssertionError('must not parse unchanged file')):
            result,events=self.run_roots(path.parent)
        self.assertEqual(result[0],1);self.assertEqual(self.items(events)[0]['result'],'เดิมไม่เปลี่ยน')
        self.assertEqual(events[-1]['unchanged'],1)
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_new_duplicate_reuses_old_metadata_before_parsing(self):
        old=self.song();self.run_roots(old.parent);sid=self.record(old)['id']
        new=self.song('new/999 - ชื่อสำเนา - คนอื่น.mid')
        with patch.object(Inspector,'inspect',side_effect=AssertionError('duplicate must reuse cached metadata')):
            _,events=self.run_roots(new.parent)
        self.assertEqual(self.db.count(),1);self.assertEqual(self.record(new)['duplicate_of'],sid)
        self.assertEqual(self.db.get(sid)['title'],'เพลงหลัก')
        self.assertEqual(self.items(events)[0]['result'],'ซ้ำกับรายการเดิม')
        self.assertTrue(old.exists() and new.exists())
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_duplicates_inside_one_new_batch_use_one_visible_song(self):
        a=self.song();b=self.song('songs/002 - สำเนา - นักร้อง.mid')
        _,events=self.run_roots(a.parent)
        self.assertEqual(self.db.count(),1)
        self.assertEqual([e['result'] for e in self.items(events)],['เพิ่มใหม่','ซ้ำกับรายการเดิม'])
        self.assertEqual(self.record(b)['duplicate_of'],self.record(a)['id'])
    def test_changed_file_preserves_id_favorite_and_manual_edits(self):
        path=self.song();self.run_roots(path.parent);sid=self.record(path)['id']
        self.db.favorite(sid);self.db.edit(sid,'CUSTOM','ชื่อที่แก้','ผู้ร้องแก้')
        path.write_bytes(midi_fixture()+b'\0')
        _,events=self.run_roots(path.parent)
        row=self.record(path)
        self.assertEqual((row['id'],row['favorite'],row['title'],row['code']),(sid,1,'ชื่อที่แก้','CUSTOM'))
        self.assertEqual(self.items(events)[0]['result'],'อัปเดต')
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_changed_primary_rehomes_the_old_identical_copies(self):
        a=self.song();b=self.song('songs/002 - เพลง - คน.mid');c=self.song('songs/003 - เพลง - คน.mid')
        self.run_roots(a.parent);a.write_bytes(midi_fixture()+b'\0')
        self.run_roots(a.parent)
        self.assertEqual(self.db.count(),2)
        self.assertEqual(self.record(b)['duplicate_of'],0)
        self.assertEqual(self.record(c)['duplicate_of'],self.record(b)['id'])
        self.assertEqual(self.record(a)['duplicate_of'],0)
    def test_ncn_sidecar_change_updates_details_and_retains_id(self):
        path=self.song('ncn/Song/1/100.mid')
        lyr=self.root/'ncn/Lyrics/1/100.lyr';cur=self.root/'ncn/Cursor/1/100.cur'
        lyr.parent.mkdir(parents=True);cur.parent.mkdir(parents=True)
        lyr.write_text('เพลงเดิม\nศิลปิน\nC\n.\nเนื้อร้อง',encoding='utf-8')
        cur.write_bytes(b'\0\0\0\0\x18\0\xff\xff')
        self.run_roots(self.root/'ncn');sid=self.record(path)['id']
        lyr.write_text('เพลงใหม่\nศิลปิน\nC\n.\nเนื้อร้อง',encoding='utf-8')
        _,events=self.run_roots(self.root/'ncn')
        self.assertEqual(self.db.get(sid)['title'],'เพลงใหม่');self.assertEqual(self.record(path)['id'],sid)
        self.assertEqual(self.items(events)[0]['result'],'อัปเดต')
    def test_incomplete_metadata_is_reread_even_without_file_change(self):
        path=self.song('songs/100.mid');self.run_roots(path.parent)
        original=Inspector.inspect;seen=[]
        def inspect(instance,item):seen.append(str(item));return original(instance,item)
        with patch.object(Inspector,'inspect',autospec=True,side_effect=inspect):
            _,events=self.run_roots(path.parent)
        self.assertIn(canonical(path),[canonical(Path(item)) for item in seen]);self.assertNotEqual(self.items(events)[0]['result'],'เดิมไม่เปลี่ยน')
    def test_parser_revision_invalidates_metadata_cache(self):
        path=self.song();self.run_roots(path.parent)
        original=Inspector.inspect;seen=[]
        def inspect(instance,item):seen.append(str(item));return original(instance,item)
        with patch('karaoke.incremental.READER_REVISION',READER_REVISION+'-next'), \
             patch.object(Inspector,'inspect',autospec=True,side_effect=inspect):
            _,events=self.run_roots(path.parent)
        self.assertTrue(seen);self.assertEqual(self.items(events)[0]['result'],'อัปเดต')
    def test_timestamp_change_with_identical_content_skips_metadata_after_hash(self):
        path=self.song();self.run_roots(path.parent)
        stat=path.stat();os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns+1000000000))
        with patch.object(Inspector,'inspect',side_effect=AssertionError('same content needs no metadata reparse')):
            _,events=self.run_roots(path.parent)
        self.assertEqual(self.items(events)[0]['result'],'เดิมไม่เปลี่ยน')
        self.assertIn('ตรวจเนื้อหาแล้ว',self.items(events)[0]['note'])
    def test_same_code_but_different_content_is_a_separate_version(self):
        a=self.song('one/001 - เพลง - คน.mid');b=self.song('two/001 - เพลง - คน.mid',padding=1)
        self.run_roots(a.parent,b.parent)
        self.assertEqual(self.db.count(),2)
        self.assertEqual(self.record(a)['duplicate_of'],self.record(b)['duplicate_of'])
    def test_cancel_preserves_completed_rows_and_cache(self):
        for i in range(5):self.song(f'songs/{i} - เพลง - คน.mid',padding=i)
        stop=threading.Event()
        def callback(event):
            if event.get('type')=='item':stop.set()
        result,events=self.run_roots(self.root/'songs',cancelled=stop,callback=callback)
        self.assertEqual(result[0],1);self.assertEqual(len(self.items(events)),1)
        self.assertEqual(events[-1]['done'],1);self.assertEqual(events[-1]['total'],5)
        result,_=self.run_roots(self.root/'songs');self.assertEqual(result[0],5);self.assertEqual(self.db.count(),5)
    def test_full_mode_rehashes_and_reparses_unchanged_file(self):
        path=self.song();self.run_roots(path.parent)
        original=Inspector.inspect;seen=[]
        def inspect(instance,item):seen.append(str(item));return original(instance,item)
        with patch.object(Inspector,'inspect',autospec=True,side_effect=inspect):
            _,events=self.run_roots(path.parent,force=True)
        self.assertTrue(seen);self.assertEqual(self.items(events)[0]['result'],'อัปเดต')
    def test_full_mode_includes_old_records_outside_selected_folders(self):
        a=self.song();b=self.song('other/002 - เพลงอื่น - คน.mid',padding=1)
        self.run_roots(a.parent,b.parent);b.write_bytes(midi_fixture()+b'\0\0')
        _,events=self.run_roots(a.parent,force=True)
        self.assertEqual(len(self.items(events)),2);self.assertEqual(events[-1]['total'],2)
    def test_unchanged_catalog_is_not_reimported(self):
        (self.root/'legacy/Data').mkdir(parents=True)
        (self.root/'legacy/Data/SONG.DBF').write_bytes(dbf_fixture())
        path=self.song('legacy/Songs/MIDI/NCN/Song/A/A1.mid')
        self.run_roots(self.root/'legacy')
        with patch('karaoke.legacy.import_catalog',side_effect=AssertionError('unchanged DBF must be skipped')):
            _,events=self.run_roots(self.root/'legacy')
        self.assertEqual(self.items(events)[0]['result'],'เดิมไม่เปลี่ยน')
        self.assertEqual(self.record(path)['title'],'ทดสอบภาษาไทย')
    def test_cache_rebuild_does_not_change_song_identity(self):
        path=self.song();self.run_roots(path.parent);sid=self.record(path)['id'];self.db.favorite(sid)
        cache=self.db.path.with_name('songs-index-cache.sqlite3')
        for file in (cache,Path(str(cache)+'-wal'),Path(str(cache)+'-shm')):file.unlink(missing_ok=True)
        self.run_roots(path.parent)
        self.assertEqual(self.record(path)['id'],sid);self.assertEqual(self.record(path)['favorite'],1)
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_richer_duplicate_can_fill_missing_old_metadata_without_replacing_id(self):
        old=self.song('old/001.mid');self.run_roots(old.parent);sid=self.record(old)['id']
        new=self.song('new/001 - ชื่อจริง - ผู้ร้อง.mid');self.run_roots(new.parent)
        self.assertEqual(self.db.count(),1);self.assertEqual(self.db.get(sid)['title'],'ชื่อจริง')
        self.assertEqual(self.db.get(sid)['artist'],'ผู้ร้อง');self.assertEqual(self.record(new)['duplicate_of'],sid)
    def test_new_copy_does_not_reuse_a_stale_changed_old_hash(self):
        old=self.song();self.run_roots(old.parent);old.write_bytes(midi_fixture()+b'\0')
        new=self.song('new/002 - อีกเวอร์ชัน - คน.mid')
        self.run_roots(new.parent)
        self.assertEqual(self.record(new)['duplicate_of'],0);self.assertEqual(self.db.count(),2)
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_queued_existing_record_can_remain_primary_after_content_match(self):
        a=self.song();b=self.song('songs/002 - เพลงใหม่ - คน.mid',padding=1)
        self.run_roots(a.parent);sid=self.record(b)['id']
        b.write_bytes(a.read_bytes());self.run_roots(a.parent,protected=[sid])
        self.assertEqual(self.db.search()[0]['id'],sid)
        self.assertIsNotNone(self.db.get(self.record(a)['id']))
    def test_file_changed_with_preserved_mtime_is_detected_by_signature(self):
        path=self.song();self.run_roots(path.parent);stat=path.stat()
        if os.name=='nt':
            import time
            time.sleep(.03)
        data=bytearray(path.read_bytes());position=data.index(b'\x90\x3c\x40');data[position+1]=0x3d
        path.write_bytes(data);os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        _,events=self.run_roots(path.parent)
        self.assertEqual(self.items(events)[0]['result'],'อัปเดต')

    def test_untrusted_change_stamp_rehashes_instead_of_blind_skip(self):
        import karaoke.incremental as incremental
        path=self.song()
        with patch('karaoke.incremental.change_time',return_value=None):
            self.run_roots(path.parent)
            real=incremental.content_key
            with patch('karaoke.incremental.content_key',wraps=real) as hashed:
                self.run_roots(path.parent)
            self.assertTrue(hashed.called)
    def test_new_copy_after_keeper_disappears_stays_available(self):
        old=self.song();self.run_roots(old.parent);old.unlink()
        new=self.song('new/002 - สำเนาที่ยังอยู่ - คน.mid')
        self.run_roots(new.parent)
        self.assertEqual(self.record(new)['duplicate_of'],0)
        self.assertEqual(self.record(new)['playable'],1)
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_changed_existing_duplicate_can_join_another_group_without_losing_edits(self):
        a=self.song();b=self.song('songs/002 - เพลงบี - คน.mid',padding=1)
        self.run_roots(a.parent);bid=self.record(b)['id']
        self.db.edit(bid,'CUSTOM','ชื่อเฉพาะ','ผู้ร้องเฉพาะ');b.write_bytes(a.read_bytes())
        self.run_roots(a.parent)
        self.assertEqual(self.db.get(bid)['title'],'ชื่อเฉพาะ');self.assertEqual(self.db.get(bid)['code'],'CUSTOM')
        self.assertEqual(self.db.count(),1)

    def test_cancel_before_metadata_is_not_reported_as_a_failed_song(self):
        import karaoke.incremental as incremental
        path=self.song();stop=threading.Event();real=incremental.content_key
        def hashed(*args,**kwargs):
            value=real(*args,**kwargs);stop.set();return value
        with patch('karaoke.incremental.content_key',side_effect=hashed):
            result,events=self.run_roots(path.parent,cancelled=stop)
        self.assertEqual(result[0],0);self.assertEqual(self.items(events),[])
        self.assertEqual(events[-1]['failed'],0)

    def test_file_changed_during_hash_is_not_linked_using_stale_content(self):
        import karaoke.incremental as incremental
        path=self.song();real=incremental.content_key
        def changed(*args,**kwargs):
            value=real(*args,**kwargs)
            path.write_bytes(path.read_bytes()+b'\0')
            return value
        with patch('karaoke.incremental.content_key',side_effect=changed):
            _,events=self.run_roots(path.parent)
        item=self.items(events)[0]
        self.assertIn('ไม่เก็บผลแคช',item['note']);self.assertEqual(self.record(path)['duplicate_of'],0)
        cache=self.db.path.with_name('songs-index-cache.sqlite3')
        with closing(sqlite3.connect(cache)) as db, db:
            self.assertIsNone(db.execute('SELECT path FROM files WHERE path=?',(canonical(path),)).fetchone())
