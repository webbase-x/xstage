import os
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
from karaoke.library import SongLibrary,canonical,SearchCancelled
from karaoke.index_plan import SongPlan
from karaoke.managed_import import ImportSession as ActualImportSession,run_plan as actual_run_plan,copy_song,category

def ImportSession(*args,**kwargs):
    return ActualImportSession(*args,strict=False,**kwargs)

def run_plan(*args,**kwargs):
    return actual_run_plan(*args,strict=False,**kwargs)
from karaoke.name_duplicates import NameIndex,identity
from karaoke import import_ui
from test_studio import midi_fixture,dbf_fixture

class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.library=SongLibrary(self.root/'Data/songs.db');self.songs=self.root/'Songs'
    def tearDown(self):self.temp.cleanup()
    def file(self,name='incoming/001 - เพลง - นักร้อง.mid',extra=b''):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(midi_fixture()+extra);return p
    def run_import(self,paths,copy_files=False,single=False,choice=None,hints=None,events=None):
        with SongPlan() as plan:
            for path in paths:
                if hints:plan.add_hint(path,hints)
                else:plan.add(path)
            return run_plan(self.library,plan,songs_root=self.songs,copy_files=copy_files,single=single,decide=choice,events=events)
    def test_no_copy_default_and_backup(self):
        p=self.file();before=p.read_bytes();result=self.run_import([p])
        self.assertEqual(result[0],1);self.assertEqual(self.library.search()[0]['path'],canonical(p))
        self.assertFalse(self.songs.exists());self.assertEqual(p.read_bytes(),before)
        self.assertTrue(self.library.path.with_name('songs-before-reindex.sqlite3').exists())
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_copy_midi_and_lrc_original_unchanged(self):
        p=self.file();p.with_suffix('.lrc').write_text('[00:00]ร้อง',encoding='utf-8')
        before={f.name:f.read_bytes() for f in p.parent.iterdir()}
        self.assertEqual(self.run_import([p],True)[0],1)
        row=self.library.search()[0];target=Path(row['path'])
        self.assertEqual(canonical(target.parent),canonical(self.songs/'MIDI'));self.assertEqual(target.read_bytes(),p.read_bytes())
        self.assertEqual(target.with_suffix('.lrc').read_bytes(),p.with_suffix('.lrc').read_bytes())
        self.assertEqual(before,{f.name:f.read_bytes() for f in p.parent.iterdir()})
    def test_category_audio_video(self):
        self.assertEqual(category('a.mp3'),'Audio');self.assertEqual(category('a.MKV'),'Video');self.assertEqual(category('a.emk'),'MIDI')
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_content_duplicate_other_filename_no_copy(self):
        a=self.file();self.run_import([a],True);old=self.library.search()[0]
        b=self.file('incoming/new-name.mid');result=self.run_import([b],True)
        self.assertEqual((result[0],result[1]),(0,1));self.assertEqual(self.library.count(),1)
        self.assertEqual(len(list((self.songs/'MIDI').glob('*.mid'))),1)
        self.assertEqual(self.library.search()[0]['id'],old['id']);self.assertTrue(b.exists())
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_name_duplicate_batch_skips_different_bytes(self):
        a=self.file();b=self.file('other/002 - เพลง - นักร้อง.mid',b'\0')
        result=self.run_import([a,b],True)
        self.assertEqual((result[0],result[1]),(1,1));self.assertEqual(self.library.count(),1)
        self.assertTrue(any('ชื่อเพลง + นักร้อง' in note for note in result[2]))
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_single_existing_default(self):
        a=self.file();self.run_import([a]);b=self.file('other/002 - เพลง - นักร้อง.mid',b'\0')
        decide=Mock(return_value='existing');self.run_import([b],True,True,decide)
        self.assertEqual(self.library.count(),1);self.assertFalse(self.songs.exists());self.assertFalse(decide.call_args.args[2])
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_single_keep_both_name_duplicates(self):
        a=self.file();self.run_import([a]);b=self.file('other/002 - เพลง - นักร้อง.mid',b'\0')
        self.run_import([b],True,True,lambda *args:'both');self.assertEqual(self.library.count(),2)
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_replace_preserves_id_favorite_edited_metadata_and_files(self):
        a=self.file();self.run_import([a]);old=self.library.search()[0];sid=old['id']
        self.library.favorite(sid);self.library.edit(sid,'CUSTOM','แก้ชื่อ','แก้นักร้อง')
        b=self.file('other/new.mid',b'\0');original=a.read_bytes();calls=[]
        with ImportSession(self.library,self.songs,True,decide=lambda *args:'new',replaced=lambda *args:calls.append(args)) as session:
            session.prepare();row,result=session.import_one(b,True,dict(title='แก้ชื่อ',artist='แก้นักร้อง'))
        row=self.library.get(sid)
        self.assertEqual((row['id'],row['favorite'],row['code'],row['title'],row['artist']),(sid,1,'CUSTOM','แก้ชื่อ','แก้นักร้อง'))
        self.assertNotEqual(row['path'],canonical(a));self.assertEqual(a.read_bytes(),original);self.assertTrue(b.exists());self.assertEqual(len(calls),1)
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_exact_single_cannot_force_second_copy(self):
        a=self.file();self.run_import([a],True);b=self.file('other/x.mid')
        decide=Mock(return_value='both');self.run_import([b],True,True,decide)
        self.assertTrue(decide.call_args.args[2]);self.assertEqual(self.library.count(),1)
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_lyric_difference_preserved_when_keep_both(self):
        a=self.file();a.with_suffix('.lrc').write_text('[00:00]one');self.run_import([a],True)
        b=self.file('other/002 - เพลง - นักร้อง.mid');b.with_suffix('.lrc').write_text('[00:00]two')
        decide=Mock(return_value='both');self.run_import([b],True,True,decide)
        self.assertFalse(decide.call_args.args[2]);self.assertEqual(self.library.count(),2)
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_unindexed_managed_content_reused_without_extra_copy(self):
        a=self.file();existing,_=copy_song(a,self.songs)
        b=self.file('other/new-name.mid');self.run_import([b],True)
        self.assertEqual(self.library.search()[0]['path'],canonical(existing));self.assertEqual(len(list((self.songs/'MIDI').glob('*.mid'))),1)
    def test_collision_different_content_never_overwritten(self):
        a=self.file();target=self.songs/'MIDI'/a.name;target.parent.mkdir(parents=True);target.write_bytes(b'existing')
        dest,copied=copy_song(a,self.songs)
        self.assertTrue(copied);self.assertNotEqual(dest,target);self.assertEqual(target.read_bytes(),b'existing')
    def test_orphan_companion_reserves_stem(self):
        a=self.file();folder=self.songs/'MIDI';folder.mkdir(parents=True)
        orphan=folder/a.with_suffix('.lyr').name;orphan.write_bytes(b'original')
        target,_=copy_song(a,self.songs)
        self.assertNotEqual(target.name,a.name);self.assertEqual(orphan.read_bytes(),b'original')
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_ncn_copy_preserves_pair(self):
        a=self.file('ncn/Song/1/100.mid')
        for folder,ext,data in [('Lyrics','.lyr','เพลง\nนักร้อง\nC\n.\nร้อง'.encode('utf-8')),('Cursor','.cur',b'\0\0\0\0\x18\0\xff\xff')]:
            p=self.root/'ncn'/folder/'1'/('100'+ext);p.parent.mkdir(parents=True);p.write_bytes(data)
        self.assertEqual(self.run_import([a],True)[0],1);dest=Path(self.library.search()[0]['path'])
        self.assertTrue(dest.with_suffix('.lyr').is_file());self.assertTrue(dest.with_suffix('.cur').is_file())
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_incomplete_ncn_reported_without_modifying_source(self):
        a=self.file();a.with_suffix('.lyr').write_text('เพลง\nนักร้อง\nC\n.\nร้อง',encoding='utf-8')
        result=self.run_import([a],True)
        self.assertEqual(result[0],0);self.assertTrue(any('NCN' in n for n in result[2]));self.assertTrue(a.exists());self.assertFalse(self.songs.exists())
    def test_cancellation_before_copy_keeps_originals(self):
        a=self.file();cancel=threading.Event();cancel.set()
        with self.assertRaises(SearchCancelled):copy_song(a,self.songs,cancel)
        self.assertTrue(a.is_file());self.assertFalse(self.songs.exists())
    def test_publish_failure_removes_only_own_verified_files(self):
        a=self.file();a.with_suffix('.lrc').write_text('[00:00]one');original=os.link;calls=[]
        def link(src,dst):
            calls.append(dst)
            if len(calls)==2:raise OSError('simulated full disk')
            return original(src,dst)
        with patch('karaoke.managed_import.os.link',side_effect=link):
            with self.assertRaises(OSError):copy_song(a,self.songs)
        self.assertEqual(list((self.songs/'MIDI').iterdir()),[]);self.assertTrue(a.is_file())
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_rebuild_existing_keeps_id_and_manual_edits(self):
        a=self.file();self.run_import([a]);sid=self.library.search()[0]['id'];self.library.edit(sid,'edited','manual','singer')
        a.write_bytes(midi_fixture()+b'\0');self.run_import([a],True)
        row=self.library.get(sid);self.assertEqual(row['title'],'manual');self.assertEqual(row['path'],canonical(a));self.assertFalse(self.songs.exists())
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_batch_earliest_existing_id_selected(self):
        a=self.file();b=self.file('other/002 - เพลง - นักร้อง.mid',b'\0');ids=self.library.add_files([a,b])
        c=self.file('third/003 - เพลง - นักร้อง.mid',b'\0\0')
        with ImportSession(self.library,self.songs) as session:
            session.prepare();row,result=session.import_one(c)
        self.assertEqual(row['id'],ids[0]);self.assertTrue(result.startswith('ซ้ำ'))
    def test_name_index_normalization_blanks_and_annotations(self):
        self.assertEqual(identity('  SONG  name ','Singer'),identity('song name',' singer '));self.assertIsNone(identity('song',' '))
        self.assertNotEqual(identity('กา','คน'),identity('ก่า','คน'))
        a=self.file();b=self.file('other/002 - เพลง - นักร้อง.mid',b'\0');ids=self.library.add_files([a,b])
        index=NameIndex(include_key=False)
        try:
            with self.library.connect() as db:index.refresh(db)
            rows=index.annotate(self.library.search());self.assertEqual({r['name_keeper_id'] for r in rows},{ids[0]});self.assertTrue(all(r['name_duplicate_count']==2 for r in rows))
        finally:index.close()
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_catalog_hints_preserved_before_copy_and_duplicate_decision(self):
        from karaoke.lister import build_list
        base=self.root/'legacy';(base/'Data').mkdir(parents=True);(base/'Data/SONG.DBF').write_bytes(dbf_fixture())
        a=self.file('legacy/Songs/MIDI/NCN/Song/A/A1.mid')
        result=build_list(self.library,[{'path':str(base),'type':'ทุกประเภท'}],import_options=dict(songs_root=self.songs,copy_files=True,strict=False))
        self.assertEqual(result[0],1);row=self.library.search()[0]
        self.assertEqual((row['title'],row['artist']),('ทดสอบภาษาไทย','คนร้อง'));self.assertTrue(row['source_catalog']);self.assertTrue(row['path'].startswith(canonical(self.songs)))
    def test_existing_changed_keeper_releases_old_aliases(self):
        from karaoke.duplicates import scan
        a=self.file();b=self.file('other/002 - เพลง - นักร้อง.mid');ids=self.library.add_files([a,b]);scan(self.library)
        self.run_import([a]);a.write_bytes(midi_fixture()+b'\0')
        self.run_import([a]);self.assertEqual(self.library.get(ids[1])['duplicate_of'],0);self.assertEqual(self.library.count(),2)
    def test_current_name_index_sees_new_library_commits(self):
        a=self.file();sid=self.library.add_files([a])[0];reader=self.library.open_reader();names=NameIndex(include_key=False)
        try:
            names.refresh(reader.db);self.library.edit(sid,'1','New Title','New Singer');names.refresh(reader.db)
            self.assertEqual(names.lookup('New Title','New Singer'),(sid,1));self.assertEqual(names.lookup('เพลง','นักร้อง'),(None,0))
        finally:reader.close();names.close()
    def test_new_import_keeps_catalog_metadata_fields(self):
        a=self.file();self.run_import([a],hints={'rhythm':'ลูกทุ่ง','source_catalog':'catalog.dbf'})
        row=self.library.search()[0];self.assertEqual(row['rhythm'],'ลูกทุ่ง');self.assertEqual(row['source_catalog'],'catalog.dbf')
    def test_unchanged_existing_path_keeps_incremental_fast_path(self):
        a=self.file();self.run_import([a])
        with patch('karaoke.incremental.content_key',side_effect=AssertionError('must not hash unchanged')),patch('karaoke.managed_import.content_key',side_effect=AssertionError('must not hash unchanged')):
            self.assertEqual(self.run_import([a])[0],1)
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_audio_and_video_copy_go_to_correct_folders(self):
        import wave
        audio=self.root/'incoming/audio.wav';audio.parent.mkdir()
        with wave.open(str(audio),'wb') as stream:
            stream.setparams((1,2,8000,0,'NONE','not compressed'));stream.writeframes(b'\0\0'*80)
        video=self.root/'incoming/video.mp4';video.write_bytes(b'\0\0\0\x18ftypisom'+b'\0'*32)
        self.assertEqual(self.run_import([audio,video],True)[0],2)
        self.assertTrue((self.songs/'Audio/audio.wav').is_file());self.assertTrue((self.songs/'Video/video.mp4').is_file())
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_cancel_single_choice_does_not_add(self):
        a=self.file();self.run_import([a]);b=self.file('other/002 - เพลง - นักร้อง.mid',b'\0')
        self.run_import([b],True,True,lambda *args:'cancel');self.assertEqual(self.library.count(),1);self.assertFalse(self.songs.exists())

class BridgeTests(unittest.TestCase):
    def test_worker_choice_is_handled_on_main_thread(self):
        app=NS(messages=queue.Queue(),cancel_scan=threading.Event(),closing=False);result=[]
        worker=threading.Thread(target=lambda:result.append(import_ui.request_choice(app,{}, {},False)));worker.start()
        kind,data=app.messages.get(timeout=2)
        with patch('karaoke.import_ui.duplicate_choice',return_value='new') as dialog:import_ui.handle_message(app,kind,data)
        worker.join(2);self.assertFalse(worker.is_alive());self.assertEqual(result,['new']);dialog.assert_called_once()
    def test_cancel_does_not_wait_for_ui_forever(self):
        app=NS(messages=queue.Queue(),cancel_scan=threading.Event(),closing=False);app.cancel_scan.set()
        with self.assertRaises(SearchCancelled):import_ui.request_choice(app,{}, {},False)
    def test_replace_copies_eq_keeps_old_setting(self):
        from karaoke.song_eq import key
        old=key({'path':'old.mid'});new=key({'path':'new.mid'})
        app=NS(settings={'song_eq':{old:{'state':'original'}}},save_settings=Mock())
        self.assertTrue(import_ui.handle_message(app,'song_replaced',('old.mid','new.mid')))
        self.assertEqual(app.settings['song_eq'][old],app.settings['song_eq'][new]);self.assertIsNot(app.settings['song_eq'][old],app.settings['song_eq'][new]);app.save_settings.assert_called_once()

@unittest.skipUnless(os.environ.get('DISPLAY'),'requires graphical display')
class ImportGuiTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.app=tk.Tk();self.app.withdraw();self.app.data_dir=Path(tempfile.gettempdir())/'xstage-test/Data'
    def tearDown(self):self.app.destroy()
    def click(self,text):
        def walk(w):
            for child in w.winfo_children():
                if child.winfo_class()=='TButton' and child.cget('text')==text:child.invoke();return True
                if walk(child):return True
            return False
        self.app.after(100,lambda:walk(self.app))
    def test_copy_dialog_defaults_to_reference(self):
        self.click('เริ่มนำเข้า');self.assertIs(import_ui.choose_copy(self.app),False)
    def test_duplicate_dialog_defaults_existing(self):
        self.click('ยืนยัน');row=dict(id=1,title='เพลง',artist='นักร้อง',path='original.mid')
        self.assertEqual(import_ui.duplicate_choice(self.app,dict(row,path='new.mid'),row,False),'existing')
    def test_duplicate_dialog_cancel(self):
        self.click('ยกเลิก');row=dict(id=1,title='เพลง',artist='นักร้อง',path='original.mid')
        self.assertEqual(import_ui.duplicate_choice(self.app,row,row,True),'cancel')
