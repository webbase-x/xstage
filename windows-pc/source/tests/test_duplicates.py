from contextlib import closing
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from karaoke.library import SongLibrary, scan_folder
from karaoke.duplicates import scan, groups, move_duplicate, restore_move, recycle_duplicate, recycle_files, fingerprint
from test_studio import midi_fixture

class DuplicateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.db=SongLibrary(self.root/'data'/'songs.db')
    def tearDown(self): self.temp.cleanup()
    def midi(self,name,raw=None):
        file=self.root/name;file.parent.mkdir(parents=True,exist_ok=True)
        file.write_bytes(raw if raw is not None else midi_fixture());return file
    def pair(self):
        a=self.midi('one/1.mid');b=self.midi('two/2.mid')
        ids=self.db.add_files([a,b]);return a,b,ids
    def ncn(self,base,lyric='เพลง\nศิลปิน\nC\n.\nเนื้อร้อง'):
        p=self.midi(base+'/Song/1/100.mid')
        for folder,ext,data in [('Lyrics','.lyr',lyric.encode('utf-8')),('Cursor','.cur',b'\0\0\0\0\x18\0\xff\xff')]:
            file=self.root/base/folder/'1'/('100'+ext);file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(data)
        return p
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_exact_copies_hidden_and_originals_untouched(self):
        a,b,ids=self.pair();found,errors=scan(self.db)
        self.assertEqual(len(found),1);self.assertEqual(self.db.count(),1)
        self.assertEqual(len(self.db.search()),1);self.assertTrue(a.exists() and b.exists())
        self.assertEqual(self.db.get(ids[1])['duplicate_of'],ids[0]);self.assertTrue(self.db.get(ids[1])['playable'])
        self.assertTrue(self.db.path.with_name('songs-before-reindex.sqlite3').exists())
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_queue_priority_preserves_id_and_metadata(self):
        _,_,ids=self.pair();scan(self.db,protected=[ids[1]])
        self.assertEqual(self.db.search()[0]['id'],ids[1]);self.assertIsNotNone(self.db.get(ids[0]))
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_edited_and_favorite_priority(self):
        _,_,ids=self.pair();self.db.edit(ids[1],'x','แก้แล้ว','คน');scan(self.db)
        self.assertEqual(self.db.search()[0]['id'],ids[1]);self.assertEqual(self.db.get(ids[1])['title'],'แก้แล้ว')
        self.db.favorite(ids[0]);scan(self.db,protected=[ids[0]])
        self.assertEqual(self.db.search()[0]['id'],ids[0])
    def test_different_content_same_name_is_retained(self):
        a=self.midi('one/same.mid');b=self.midi('two/same.mid',midi_fixture()+b'\0')
        self.db.add_files([a,b]);scan(self.db);self.assertEqual(self.db.count(),2)
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_ncn_compares_complete_triplet(self):
        a=self.ncn('one');b=self.ncn('two');self.db.add_files([a,b]);scan(self.db)
        self.assertEqual(self.db.count(),1)
        (self.root/'two/Lyrics/1/100.lyr').write_text('ต่างกัน\nศิลปิน\nC\n.\nเนื้อร้อง',encoding='utf-8')
        scan(self.db);self.assertEqual(self.db.count(),2)
    def test_incomplete_ncn_never_becomes_duplicate_keeper(self):
        a=self.ncn('one');b=self.ncn('two');self.db.add_files([a,b])
        (self.root/'two/Cursor/1/100.cur').unlink()
        found,errors=scan(self.db);self.assertEqual(found,[]);self.assertTrue(errors);self.assertEqual(self.db.count(),2)
    def test_lrc_differences_are_not_merged(self):
        a,b,_=self.pair();a.with_suffix('.lrc').write_text('[00:00]one');b.with_suffix('.lrc').write_text('[00:00]two')
        scan(self.db);self.assertEqual(self.db.count(),2)
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_cancel_preserves_previous_visibility(self):
        a,b,ids=self.pair();scan(self.db)
        cancel=threading.Event();cancel.set();found,_=scan(self.db,cancelled=cancel)
        self.assertIsNone(found);self.assertEqual(self.db.get(ids[1])['duplicate_of'],ids[0])
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_search_reader_invalidation_and_favorite_search(self):
        _,_,ids=self.pair();reader=self.db.open_reader();self.assertEqual(len(reader.search()),2)
        self.db.favorite(ids[1]);scan(self.db)
        self.assertEqual(len(reader.search()),1);self.assertEqual(reader.search(favorite=True)[0]['id'],ids[1]);reader.close()
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_move_and_restore_whole_ncn_bundle(self):
        a=self.ncn('one');b=self.ncn('two');ids=self.db.add_files([a,b]);scan(self.db)
        manifest=move_duplicate(self.db,ids[1],self.root/'เพลงซ้ำ')
        data=json.loads(manifest.read_text(encoding='utf-8'));self.assertEqual(len(data['files']),3)
        self.assertTrue(a.exists());self.assertFalse(b.exists());self.assertEqual(self.db.get(ids[1])['duplicate_state'],'moved')
        self.assertEqual(restore_move(self.db,manifest),3);self.assertTrue(b.exists())
        self.assertEqual(fingerprint(a)[0],fingerprint(b)[0]);self.assertEqual(self.db.get(ids[1])['duplicate_state'],'kept')
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_restore_does_not_overwrite_existing_source(self):
        a,b,ids=self.pair();scan(self.db);manifest=move_duplicate(self.db,ids[1],self.root/'dups')
        b.write_bytes(b'existing')
        with self.assertRaises(ValueError):restore_move(self.db,manifest)
        self.assertEqual(b.read_bytes(),b'existing');self.assertTrue(a.exists())
    def test_move_rechecks_content_and_keeper_presence(self):
        a,b,ids=self.pair();scan(self.db);b.write_bytes(midi_fixture()+b'\0')
        with self.assertRaises(ValueError):move_duplicate(self.db,ids[1],self.root/'dups')
        self.assertTrue(b.exists());b.write_bytes(a.read_bytes());a.unlink()
        with self.assertRaises((ValueError,OSError)):move_duplicate(self.db,ids[1],self.root/'dups')
        self.assertTrue(b.exists())
    def test_protected_duplicates_cannot_be_moved_or_recycled(self):
        a,b,ids=self.pair();scan(self.db)
        with self.assertRaises(ValueError):move_duplicate(self.db,ids[1],self.root/'dups',protected=[ids[1]])
        self.db.favorite(ids[1])
        with self.assertRaises(ValueError):recycle_duplicate(self.db,ids[1])
        self.assertTrue(a.exists() and b.exists())
    def test_shared_hardlinked_media_is_not_moved(self):
        a=self.midi('one/1.mid');b=self.root/'two/2.mid';b.parent.mkdir();os.link(a,b)
        ids=self.db.add_files([a,b]);scan(self.db)
        with self.assertRaises(ValueError):move_duplicate(self.db,ids[1],self.root/'dups')
        self.assertTrue(a.exists() and b.exists())
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_move_failure_rolls_back_triplet(self):
        a=self.ncn('one');b=self.ncn('two');ids=self.db.add_files([a,b]);scan(self.db)
        original=shutil.move;count=0
        def failing(source,target):
            nonlocal count
            count+=1
            if count==2:raise OSError('fixture failure')
            return original(source,target)
        with patch('karaoke.duplicates.shutil.move',side_effect=failing):
            with self.assertRaises(OSError):move_duplicate(self.db,ids[1],self.root/'dups')
        self.assertEqual(fingerprint(a)[0],fingerprint(b)[0]);self.assertEqual(self.db.get(ids[1])['duplicate_state'],'kept')
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_quarantine_is_not_reimported(self):
        _,_,ids=self.pair();scan(self.db);move_duplicate(self.db,ids[1],self.root/'dups')
        scan_folder(self.root,self.db)
        with self.db.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM songs').fetchone()[0],2)
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_recycle_routes_entire_bundle_and_keeps_keeper(self):
        a=self.ncn('one');b=self.ncn('two');ids=self.db.add_files([a,b]);scan(self.db)
        # Simulate only the OS boundary; production never uses unlink.
        def fake_recycle(paths):
            for path in paths:path.unlink()
        with patch('karaoke.duplicates.recycle_files',side_effect=fake_recycle) as recycle:
            report=recycle_duplicate(self.db,ids[1])
        self.assertEqual(len(recycle.call_args.args[0]),3);self.assertTrue(a.exists());self.assertFalse(b.exists())
        self.assertEqual(json.loads(report.read_text(encoding='utf-8'))['state'],'recycled')
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_failed_recycle_preserves_media_and_records_failure(self):
        a,b,ids=self.pair();scan(self.db)
        with patch('karaoke.duplicates.recycle_files',side_effect=OSError('unavailable')):
            with self.assertRaises(OSError):recycle_duplicate(self.db,ids[1])
        self.assertTrue(a.exists() and b.exists())
        report=next(self.db.path.parent.glob('recycle-*.json'))
        self.assertEqual(json.loads(report.read_text(encoding='utf-8'))['state'],'incomplete')
    @unittest.skipIf(os.name=='nt','Non-Windows boundary check')
    def test_non_windows_recycle_has_no_permanent_delete_fallback(self):
        a=self.midi('one/1.mid')
        with self.assertRaises(OSError):recycle_files([a])
        self.assertTrue(a.exists())
    def test_existing_schema_migrates(self):
        path=self.root/'old.db'
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE songs(id INTEGER PRIMARY KEY,path TEXT UNIQUE NOT NULL,code TEXT NOT NULL,title TEXT NOT NULL,artist TEXT NOT NULL,kind TEXT NOT NULL,search TEXT NOT NULL,favorite INTEGER NOT NULL DEFAULT 0)')
        migrated=SongLibrary(path)
        with migrated.connect() as db:
            fields={row[1] for row in db.execute('PRAGMA table_info(songs)')}
        self.assertTrue({'duplicate_of','duplicate_state'}<=fields)

    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')

    def test_select_keeper_preserves_both_ids_and_queue_references(self):
        from karaoke.duplicates import choose_keeper
        a,b,ids=self.pair();scan(self.db);choose_keeper(self.db,ids[1])
        self.assertEqual(self.db.search()[0]['id'],ids[1]);self.assertEqual(self.db.get(ids[0])['duplicate_of'],ids[1])
        scan(self.db);self.assertEqual(self.db.search()[0]['id'],ids[1])
        self.assertTrue(a.exists() and b.exists())
        manifest=move_duplicate(self.db,ids[0],self.root/'dups')
        self.assertTrue(b.exists());restore_move(self.db,manifest);self.assertTrue(a.exists())

    @unittest.skipUnless(os.name=='nt' and os.environ.get('XSTAGE_TEST_RECYCLE')=='1', 'Opt-in Windows native IFileOperation Recycle Bin')
    def test_native_recycle_of_disposable_fixture(self):
        file=self.midi('native/test.mid')
        recycle_files([file])
        self.assertFalse(file.exists())

    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')

    def test_interrupted_move_can_restore_remaining_components(self):
        a=self.ncn('one');b=self.ncn('two');ids=self.db.add_files([a,b]);scan(self.db)
        manifest=move_duplicate(self.db,ids[1],self.root/'dups');data=json.loads(manifest.read_text(encoding='utf-8'))
        item=data['files'][1]
        shutil.move(item['target'],item['source'])  # simulate one component never moved
        data['state']='moving';manifest.write_text(json.dumps(data),encoding='utf-8')
        self.assertEqual(restore_move(self.db,manifest),2)
        self.assertEqual(fingerprint(a)[0],fingerprint(b)[0])

    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')

    def test_hidden_favorite_remains_visible_on_queued_keeper(self):
        _,_,ids=self.pair();self.db.favorite(ids[1]);scan(self.db,protected=[ids[0]])
        row=self.db.search(favorite=True)[0]
        self.assertEqual(row['id'],ids[0]);self.assertEqual(row['favorite'],1)
        self.assertEqual(self.db.get(ids[1])['favorite'],1)
        self.db.favorite(ids[0]);self.assertEqual(self.db.search(favorite=True),[])

    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')

    def test_dialog_cancel_prevents_move_and_recycle(self):
        from types import SimpleNamespace
        from contextlib import ExitStack
        from unittest.mock import MagicMock,Mock
        from karaoke.duplicate_dialog import open_exact_duplicates as open_duplicates
        _,_,ids=self.pair();scan(self.db)
        app=SimpleNamespace(duplicate_window=None,library=self.db,scanning=False,after=Mock(),after_cancel=Mock(),
            status_var=Mock(),show_import_report=Mock(),song_queue=SimpleNamespace(items=[]),current_song=None,
            start_index_job=Mock())
        controls={}
        def make_button(*args,**kwargs):
            controls[kwargs['text']]=kwargs['command'];return MagicMock()
        with ExitStack() as stack:
            for name in ['DialogWindow','tk.StringVar','ttk.Frame','ttk.Label','ttk.Scrollbar']:
                stack.enter_context(patch('karaoke.duplicate_dialog.'+name))
            tree=stack.enter_context(patch('karaoke.duplicate_dialog.ttk.Treeview')).return_value
            tree.selection.return_value=(str(ids[1]),)
            stack.enter_context(patch('karaoke.duplicate_dialog.ttk.Button',side_effect=make_button))
            stack.enter_context(patch('karaoke.duplicate_dialog.filedialog.askdirectory',return_value=str(self.root)))
            stack.enter_context(patch('karaoke.duplicate_dialog.messagebox.askyesno',return_value=False))
            open_duplicates(app)
            controls['ย้ายชุดที่เลือก…']();controls['ส่งชุดที่เลือกเข้าถังรีไซเคิล…']()
            app.start_index_job.assert_not_called()
            controls['ตรวจซ้ำ / เก็บไฟล์และซ่อนรายการซ้ำ']()
            self.assertEqual(app.start_index_job.call_args.kwargs,{'deduplicate':False})

    def test_snf_companion_difference_is_retained(self):
        a,b,_=self.pair();a.with_suffix('.snf').write_text('one');b.with_suffix('.snf').write_text('two')
        scan(self.db);self.assertEqual(self.db.count(),2)

    def test_identical_corrupt_media_is_not_hidden_as_valid_keeper(self):
        a,b,_=self.pair();a.write_bytes(b'corrupt midi');b.write_bytes(b'corrupt midi')
        found,errors=scan(self.db)
        self.assertEqual(found,[]);self.assertTrue(errors);self.assertEqual(self.db.count(),2)
