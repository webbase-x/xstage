from contextlib import closing
import json
import struct
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from test_studio import midi_fixture, archive_fixture, dbf_fixture
from tools.make_demo import meta
from karaoke.library import SongLibrary, SongQueue, QueueItem, scan_folder
from karaoke.legacy import import_catalog, ncn_pair

class IngestTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.db=SongLibrary(self.root/'songs.db')
    def tearDown(self):
        self.temp.cleanup()
    def midi(self,name='20120.mid'):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(midi_fixture());return p
    def ncn(self):
        p=self.midi('Song/2/20120.MID');lyr=self.root/'lyrics/2/20120.LYR';cur=self.root/'CURSOR/2/20120.CUR'
        lyr.parent.mkdir(parents=True);cur.parent.mkdir(parents=True)
        lyr.write_bytes('รักน้องพร\r\nบาซู\r\nEm\r\n.\r\nกข\r\n'.encode('cp874'))
        cur.write_bytes(struct.pack('<4H',0,0,24,65535));return p,lyr,cur
    def test_folder_ncn_metadata_and_case_insensitive_sidecars(self):
        p,lyr,cur=self.ncn();count,skipped,errors=scan_folder(self.root,self.db)
        self.assertEqual((count,skipped),(1,0));s=self.db.search('รักน้องพร')[0]
        self.assertEqual((s['code'],s['artist'],s['format'],s['key_signature']),('20120','บาซู','NCN24','Em'))
        self.assertEqual(self.db.search('กข')[0]['id'],s['id']);self.assertEqual(ncn_pair(p),(lyr,cur))
    def test_flat_ncn_missing_cursor(self):
        p=self.midi('Song/A001.mid');lyr=self.root/'Lyrics/A001.lyr';lyr.parent.mkdir()
        lyr.write_text('เพลง\nคน\nC\n.\nเนื้อร้อง',encoding='utf-8-sig')
        errors=[];ids=self.db.add_files([p],errors=errors)
        self.assertEqual(self.db.get(ids[0])['title'],'เพลง');self.assertTrue(any('ไม่มี CUR' in e for e in errors))
    def test_emk_embedded_metadata(self):
        p=self.root/'E001.emk';p.write_bytes(archive_fixture());s=self.db.get(self.db.add_files([p])[0])
        self.assertEqual((s['title'],s['artist'],s['format']),('เพลง','คน','EMK'))
    def test_corrupt_wrong_extension_and_unsupported(self):
        for name,raw in [('bad.mid',b'RIFF1234WAVE'),('bad.wav',midi_fixture()),('truncated.wav',b'RIFF'+(100).to_bytes(4,'little')+b'WAVE'),('bad.emk',b'.SFDS'),('bad.mp3',b'ID3'),('bad.kar',midi_fixture()[:-5]),('font.sf2',b'RIFF')]:
            p=self.root/name;p.write_bytes(raw);errors=[]
            self.assertEqual(self.db.add_files([p],errors=errors),[],name);self.assertTrue(errors,name)
        self.assertEqual(self.db.count(),0)
    def test_rebuild_repairs_filename_preserves_id_favorites_queue_search_cache(self):
        p,_,_=self.ncn();self.db.upsert_catalog([dict(path=str(p),code='',title='20120',artist='',kind='MIDI',playable=1)])
        old=self.db.search('20120')[0];self.db.favorite(old['id']);q=SongQueue(self.root/'q.json');q.add(QueueItem(old['id']))
        with closing(self.db.open_reader()) as reader:
            self.assertEqual(reader.search('รักน้องพร'),[])
            self.assertEqual(self.db.rebuild()[0],1);s=reader.search('รักน้องพร')[0]
        self.assertEqual((s['id'],s['favorite'],s['code']),(old['id'],1,'20120'))
        self.assertEqual(SongQueue(self.root/'q.json').items[0].song_id,old['id']);self.assertEqual(self.db.count(),1)
    def test_user_and_catalog_metadata_survive(self):
        p,_,_=self.ncn();sid=self.db.add_files([p])[0];self.db.edit(sid,'CUSTOM','ชื่อแก้เอง','คนแก้เอง');self.db.rebuild()
        self.assertEqual(self.db.get(sid)['title'],'ชื่อแก้เอง');self.assertEqual(self.db.get(sid)['code'],'CUSTOM')
        p=self.midi('B01.mid');self.db.upsert_catalog([dict(path=str(p),code='B01',title='ชื่อจากดัชนี',artist='คนจากดัชนี',kind='MIDI',playable=1,source_catalog='catalog')]);self.db.rebuild()
        self.assertEqual(self.db.search('ชื่อจากดัชนี')[0]['artist'],'คนจากดัชนี')
    def test_missing_file_retained_disabled_and_recovers(self):
        p=self.midi();sid=self.db.add_files([p])[0];p.unlink();count,_,errors=self.db.rebuild()
        self.assertEqual(count,0);self.assertTrue(errors);self.assertEqual(self.db.get(sid)['playable'],0)
        self.midi();self.db.rebuild();self.assertEqual(self.db.get(sid)['playable'],1)
    def test_cancel_does_not_disable_unprocessed(self):
        p=self.midi();sid=self.db.add_files([p])[0];cancelled=threading.Event();cancelled.set()
        self.assertEqual(self.db.rebuild(cancelled=cancelled)[0],0);self.assertEqual(self.db.get(sid)['playable'],1)
        self.assertEqual(scan_folder(self.root,self.db,cancelled=cancelled)[0],0)
    def test_playlist_shared_validation(self):
        p,_,_=self.ncn();bad=self.root/'bad.mid';bad.write_bytes(b'not midi');playlist=self.root/'list.json'
        playlist.write_text(json.dumps({'format':'xstage.playlist','tracks':[{'path':str(p),'song_id':100} for p in (p,bad)]}))
        q=SongQueue(self.root/'q.json');errors=[];self.assertEqual(q.import_file(playlist,self.db,errors),(1,1))
        self.assertEqual(self.db.get(q.items[0].song_id)['title'],'รักน้องพร');self.assertTrue(errors)
    def test_catalog_missing_file_flag_and_recovery(self):
        (self.root/'Data').mkdir();(self.root/'Data/SONG.DBF').write_bytes(dbf_fixture());errors=[]
        self.assertEqual(import_catalog(self.root,self.db,errors=errors),(1,1,1));self.assertTrue(errors)
        self.assertEqual(self.db.search('ทดสอบ')[0]['playable'],0);self.midi('Songs/MIDI/NCN/Song/A/A1.mid')
        self.assertEqual(import_catalog(self.root,self.db),(1,0,0))
    def test_lrc_metadata_real_wav(self):
        p=self.root/'77.wav'
        with wave.open(str(p),'wb') as a:
            a.setparams((1,2,8000,0,'NONE','not compressed'));a.writeframes(b'\0\0'*80)
        p.with_suffix('.lrc').write_text('[ti:ชื่อเพลงเสียง]\n[ar:คนร้อง]\n[00:00.00]เนื้อร้องทดสอบ',encoding='utf-8')
        s=self.db.get(self.db.add_files([p])[0]);self.assertEqual((s['code'],s['title'],s['artist']),('77','ชื่อเพลงเสียง','คนร้อง'))
    def test_kar_title_artist_headers(self):
        track=b'\0'+meta(1,b'@KMIDI KARAOKE FILE')+b'\0'+meta(1,'@Tเพลงคาราโอเกะ'.encode('cp874'))+b'\0'+meta(1,'@Tศิลปิน'.encode('cp874'))+b'\0'+meta(0x2f,b'')
        p=self.root/'88.kar';p.write_bytes(b'MThd'+struct.pack('>IHHH',6,0,1,480)+b'MTrk'+struct.pack('>I',len(track))+track)
        s=self.db.get(self.db.add_files([p])[0]);self.assertEqual((s['title'],s['artist']),('เพลงคาราโอเกะ','ศิลปิน'))
    def test_id3_text_and_truncated_tag(self):
        text=b'\x03'+'ทดสอบ MP3'.encode();frame=b'TIT2'+len(text).to_bytes(4,'big')+b'\0\0'+text
        p=self.root/'12.mp3';p.write_bytes(b'ID3\x03\0\0'+bytes([0,0,0,len(frame)])+frame+b'\xff\xfb\x90\0'+b'\0'*500)
        self.assertEqual(self.db.get(self.db.add_files([p])[0])['title'],'ทดสอบ MP3')
        p.write_bytes(p.read_bytes()[:15]);self.assertEqual(self.db.add_files([p]),[])
    def test_sidecar_added_later_reimports(self):
        p=self.midi();sid=self.db.add_files([p])[0];p.with_suffix('.lyr').write_text('ชื่อใหม่\nศิลปิน\nG\n.\nร้อง',encoding='utf-8')
        self.assertEqual(self.db.add_files([p]),[sid]);self.assertEqual(self.db.get(sid)['title'],'ชื่อใหม่')
    def test_bad_sidecar_does_not_discard_midi(self):
        p=self.midi();p.with_suffix('.lyr').write_text('broken');errors=[];ids=self.db.add_files([p],errors=errors)
        self.assertEqual(len(ids),1);self.assertTrue(errors);self.assertEqual(self.db.get(ids[0])['code'],'20120')

    def test_folder_uses_dbf_when_no_lyr_exists(self):
        (self.root/'Data').mkdir();(self.root/'Data/SONG.DBF').write_bytes(dbf_fixture())
        self.midi('Songs/MIDI/NCN/Song/A/A1.mid')
        self.assertEqual(scan_folder(self.root,self.db)[0],1)
        self.assertEqual(self.db.search('ทดสอบภาษาไทย')[0]['artist'],'คนร้อง')

    def test_bad_compressed_emk_is_per_file_error(self):
        p=self.root/'corrupt.emk';raw=bytearray(archive_fixture(masked=False));raw[64]=0;raw[65]=0;p.write_bytes(raw)
        good=self.midi();errors=[]
        self.assertEqual(len(self.db.add_files([p,good],errors=errors)),1)
        self.assertTrue(any('EMK' in e for e in errors))

    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')

    def test_rebuild_crosses_batch_boundary_and_creates_backup(self):
        paths=[self.midi(f'{i}.mid') for i in range(105)]
        self.db.add_files(paths)
        self.assertEqual(self.db.rebuild()[0],105)
        self.assertTrue((self.root/'songs-before-reindex.sqlite3').is_file())
        self.assertEqual(self.db.count(),1)
        with self.db.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM songs').fetchone()[0],105)


    def test_catalog_path_alias_and_direct_path_keep_one_id(self):
        from karaoke.library import canonical
        p,_,_=self.ncn()
        detour=self.root/'path-alias';detour.mkdir()
        alias=detour/'..'/p.relative_to(self.root)
        record=dict(path=str(alias),code='',title='20120',artist='',kind='MIDI',playable=1)
        self.db.upsert_catalog([record])
        old=self.db.search('20120')[0]
        self.assertEqual(old['path'],canonical(p))
        self.db.favorite(old['id'])
        self.db.upsert_catalog([{**record,'path':str(p)}])
        self.assertEqual(self.db.count(),1)
        self.assertEqual(self.db.rebuild()[0],1)
        row=self.db.search('รักน้องพร')[0]
        self.assertEqual((row['id'],row['favorite']),(old['id'],1))

    def test_catalog_resolves_windows_short_path_before_storage(self):
        from unittest.mock import patch
        from karaoke.library import canonical
        p,_,_=self.ncn()
        short=self.root/'SHORT~1'/'20120.MID'
        original=Path.resolve
        def resolve(path,*args,**kwargs):
            return original(p if path==short else path,*args,**kwargs)
        with patch.object(Path,'resolve',resolve):
            self.db.upsert_catalog([dict(path=str(short),code='',title='20120',artist='',kind='MIDI',playable=1)])
            old=self.db.search('20120')[0]
            self.assertEqual(old['path'],canonical(p))
            self.assertEqual(self.db.rebuild()[0],1)
            self.assertEqual(self.db.search('รักน้องพร')[0]['id'],old['id'])
