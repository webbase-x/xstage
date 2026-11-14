import csv,json,os,sqlite3,struct,tempfile,threading,unittest,wave
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
from karaoke.library import SongLibrary,SongQueue,QueueItem,canonical
from karaoke.managed_import import ImportSession,run_plan,PolicyRejected
from karaoke.index_plan import SongPlan
from karaoke.name_duplicates import identity,musical_key,NameIndex
from karaoke.song_policy import assess
from karaoke import library_hygiene as h
from karaoke.settings_schema import validate_settings
from karaoke.lister import build_list
from test_studio import midi_fixture

class QualityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.db=SongLibrary(self.root/'Data/songs.db')
    def tearDown(self):self.temp.cleanup()
    def song(self,name='incoming/a.mid',title='Song',artist='Singer',key='C',extra=b''):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(midi_fixture()+extra)
        path.with_suffix('.lrc').write_text('[ti:'+title+']\n[ar:'+artist+']\n[key:'+key+']\n[00:00]first\n[00:01]last',encoding='utf-8');return path
    def add(self,path):return self.db.add_files([path])[0]
    def import_song(self,path,**options):
        with ImportSession(self.db,self.root/'Songs',**options) as session:session.prepare();return session.import_one(path)
    def plan(self,**options):
        folder=h.scan(self.db.path,self.root/'reports',**options);summary=json.loads((folder/'summary.json').read_text(encoding='utf-8'));return folder,summary
    def apply(self,folder,summary,ids,**options):return h.apply(self.db,folder,ids,summary['plan_sha256'],**options)
    def test_key_normalization_preserves_mode(self):
        self.assertEqual(musical_key('C#'),musical_key('Db major'));self.assertEqual(musical_key('DB'),musical_key('Db'));self.assertEqual(musical_key('BB'),musical_key('Bb'));self.assertNotEqual(musical_key('C'),musical_key('Cm'));self.assertEqual(musical_key('A minor'),musical_key('Am'));self.assertIsNone(musical_key('?'))
    def test_unknown_midi_and_emk_profiles_are_review_not_invalid(self):
        path=self.song()
        raw=path.read_bytes()
        for header in (b'Lock',b'Good',b'RIFF'):
            path.write_bytes(header+raw[4:]);self.assertEqual(assess(path)['status'],'review')
        emk=self.root/'unknown.emk';emk.write_bytes(b'unknown-profile'*8)
        self.assertEqual(assess(emk)['status'],'review')
        path.write_bytes(b'broken');self.assertEqual(assess(path)['status'],'invalid')
    def test_identity_requires_all_three_fields(self):
        self.assertIsNone(identity('Song','Singer',''));self.assertNotEqual(identity('Song','Singer','C'),identity('Song','Singer','D'));self.assertEqual(identity(' Song  ','SINGER','C#'),identity('song','singer','Db'))
    def test_valid_midi_with_lrc_is_accepted(self):
        path=self.song();self.assertEqual(assess(path)['status'],'valid');row,_=self.import_song(path);self.assertEqual(row['key_signature'],'C')
    def test_midi_without_timed_lyrics_is_rejected_before_copy(self):
        path=self.song();path.with_suffix('.lrc').unlink()
        with self.assertRaises(PolicyRejected):self.import_song(path,copy_files=True)
        self.assertEqual(self.db.count(),0);self.assertFalse((self.root/'Songs').exists());self.assertTrue(path.exists())
    def test_unknown_key_is_review_not_deletable_invalid(self):
        path=self.song(key='');self.assertEqual(assess(path)['status'],'review')
        with self.assertRaises(PolicyRejected):self.import_song(path)
    def test_audio_requires_timed_lrc(self):
        path=self.root/'001 - Audio - Singer.wav'
        with wave.open(str(path),'wb') as stream:stream.setparams((1,2,8000,0,'NONE','not compressed'));stream.writeframes(b'\0\0'*8000)
        self.assertEqual(assess(path,dict(key_signature='C'))['status'],'invalid')
        path.with_suffix('.lrc').write_text('[key:C]\n[00:00]hello');self.assertEqual(assess(path)['status'],'valid')
    def test_truncated_wav_is_invalid(self):
        path=self.root/'001 - Audio - Singer.wav'
        with wave.open(str(path),'wb') as stream:stream.setparams((1,2,8000,0,'NONE','not compressed'));stream.writeframes(b'\0\0'*8000)
        path.write_bytes(path.read_bytes()[:-500]);self.assertEqual(assess(path)['status'],'invalid')
    def test_video_does_not_require_external_lyrics(self):
        path=self.root/'001 - Video - Singer.mp4';path.write_bytes(b'\0\0\0\x18ftypisom'+b'\0'*32)
        self.assertEqual(assess(path,dict(key_signature='C'),probe=lambda *args:dict(status='valid',duration=10))['status'],'valid')
    def test_codec_unknown_goes_to_review(self):
        path=self.root/'001 - Video - Singer.mp4';path.write_bytes(b'\0\0\0\x18ftypisom'+b'\0'*32)
        self.assertEqual(assess(path,dict(key_signature='C'),probe=lambda *args:dict(status='review',reason='codec'))['status'],'review')
    def test_partial_ncn_is_invalid(self):
        path=self.song();path.with_suffix('.lyr').write_text('Song\nSinger\nC\n.\nab');self.assertEqual(assess(path)['status'],'invalid')
    def test_ncn_short_cursor_is_invalid(self):
        path=self.song();path.with_suffix('.lyr').write_text('Song\nSinger\nC\n.\nabcdef');path.with_suffix('.cur').write_bytes(b'\0\0')
        self.assertEqual(assess(path)['status'],'invalid')
    def test_different_keys_are_different_songs(self):
        a=self.song('a/a.mid',key='C');b=self.song('b/b.mid',key='D',extra=b'\0');self.import_song(a);self.import_song(b);self.assertEqual(self.db.count(),2)
    @unittest.skip('v0.9.41 retired automatic-copy/hide/old cleanup; covered by test_v0941_*')
    def test_same_triple_different_content_is_blocked(self):
        a=self.song('a/a.mid');b=self.song('b/b.mid',extra=b'\0');old,_=self.import_song(a);row,status=self.import_song(b,copy_files=True)
        self.assertEqual(row['id'],old['id']);self.assertTrue(status.startswith('ซ้ำ'));self.assertFalse((self.root/'Songs').exists())
    def test_keep_both_cannot_bypass_strict_triple_policy(self):
        a=self.song('a/a.mid');b=self.song('b/b.mid',extra=b'\0');self.import_song(a)
        with ImportSession(self.db,self.root/'Songs',decide=lambda *args:'both') as session:session.prepare();row,status=session.import_one(b,True)
        self.assertEqual(self.db.count(),1);self.assertTrue(status.startswith('ซ้ำ'))
    def test_exact_flag_matches_the_actual_displayed_keeper(self):
        a=self.song('a/a.mid',title='Target');b=self.song('b/b.mid',title='Other',extra=b'\0');ids=self.db.add_files([a,b])
        new=self.song('new/new.mid',title='Other',extra=b'\0');seen=[]
        with ImportSession(self.db,self.root/'Songs',decide=lambda r,k,e:(seen.append((k['id'],e)) or 'existing')) as session:
            session.prepare();row,status=session.import_one(new,True,dict(title='Target'))
        self.assertEqual(seen,[(ids[0],False)]);self.assertNotIn('ไฟล์/ชุดเนื้อร้อง',status)
    def test_catalog_refresh_updates_unedited_fields(self):
        path=self.song()
        for title in ('Old catalog','New catalog'):
            with ImportSession(self.db,self.root/'Songs') as session:session.prepare();row,_=session.import_one(path,hint=dict(title=title,artist='Singer',key_signature='C',source_catalog='catalog.dbf'))
        self.assertEqual(row['title'],'New catalog');self.assertEqual(row['user_edited'],0)
    def test_single_refresh_same_size_lrc_updates_metadata(self):
        path=self.song(title='Old title');self.import_song(path)
        path.with_suffix('.lrc').write_text(path.with_suffix('.lrc').read_text().replace('Old title','New title'))
        with ImportSession(self.db,self.root/'Songs') as session:session.prepare();row,_=session.import_one(path,True)
        self.assertEqual(row['title'],'New title');self.assertEqual(self.db.count(),1)
    def test_build_has_one_backup_owner(self):
        path=self.song()
        with patch.object(self.db,'backup_before_rebuild',wraps=self.db.backup_before_rebuild) as backup:build_list(self.db,[{'path':str(path.parent),'type':'ทุกประเภท'}],import_options=dict(songs_root=self.root/'Songs'))
        self.assertEqual(backup.call_count,1)
    def test_invalid_existing_keeper_does_not_block_complete_incoming(self):
        a=self.song('a/a.mid');sid=self.add(a);a.with_suffix('.lrc').unlink();b=self.song('b/b.mid',extra=b'\0')
        row,_=self.import_song(b);self.assertNotEqual(row['id'],sid);self.assertTrue(a.exists())
    def test_scan_is_read_only_and_selects_complete_keeper(self):
        a=self.song('a/a.mid');b=self.song('b/b.mid',extra=b'\0');ids=self.db.add_files([a,b]);before=[self.db.get(i) for i in ids]
        folder,summary=self.plan();self.assertTrue(summary['complete']);self.assertEqual(summary['counts']['duplicate'],1);self.assertEqual(before,[self.db.get(i) for i in ids]);self.assertTrue(a.exists() and b.exists())
    def test_only_confirmed_token_can_delete(self):
        a=self.song('a/a.mid');b=self.song('b/b.mid',extra=b'\0');ids=self.db.add_files([a,b]);folder,summary=self.plan()
        with self.assertRaises(ValueError):h.apply(self.db,folder,[ids[1]],'wrong token')
        self.assertTrue(a.exists() and b.exists())
    @unittest.skip('v0.9.41 retired automatic-copy/hide/old cleanup; covered by test_v0941_*')
    def test_delete_and_restore_has_verified_backup_and_tombstone(self):
        a=self.song('a/a.mid');b=self.song('b/b.mid',extra=b'\0');ids=self.db.add_files([a,b]);raw=b.read_bytes();folder,summary=self.plan()
        result=self.apply(folder,summary,[ids[1]]);self.assertEqual(result['applied'],1);self.assertFalse(b.exists());self.assertTrue(a.exists());self.assertEqual(self.db.count(),1);self.assertEqual(self.db.get(ids[1])['duplicate_state'],'deleted')
        self.assertTrue(h.restore_action(self.db,folder,ids[1]));self.assertEqual(b.read_bytes(),raw);self.assertEqual(self.db.count(),2)
    def test_file_change_after_report_aborts_delete(self):
        a=self.song('a/a.mid');b=self.song('b/b.mid',extra=b'\0');ids=self.db.add_files([a,b]);folder,summary=self.plan();b.write_bytes(b.read_bytes()+b'\0')
        result=self.apply(folder,summary,[ids[1]]);self.assertEqual(result['applied'],0);self.assertTrue(b.exists());self.assertEqual(self.db.count(),2)
    def test_keeper_change_after_report_aborts_delete(self):
        a=self.song('a/a.mid');b=self.song('b/b.mid',extra=b'\0');ids=self.db.add_files([a,b]);folder,summary=self.plan();a.write_bytes(a.read_bytes()+b'\0')
        self.assertEqual(self.apply(folder,summary,[ids[1]])['applied'],0);self.assertTrue(b.exists())
    def test_new_sidecar_after_report_aborts_delete(self):
        a=self.song('a/a.mid');b=self.song('b/b.mid',extra=b'\0');ids=self.db.add_files([a,b]);folder,summary=self.plan();b.with_suffix('.snf').write_bytes(b'new data')
        self.assertEqual(self.apply(folder,summary,[ids[1]])['applied'],0);self.assertTrue(b.exists())
    @unittest.skip('v0.9.41 retired automatic-copy/hide/old cleanup; covered by test_v0941_*')
    def test_shared_lyrics_are_retained_for_keeper(self):
        a=self.song('same/song.mid');b=self.root/'same/song.kar';b.write_bytes(midi_fixture()+b'\0');ids=self.db.add_files([a,b]);folder,summary=self.plan()
        result=self.apply(folder,summary,[ids[1]]);self.assertEqual(result['applied'],1);self.assertTrue(a.with_suffix('.lrc').exists());self.assertTrue(a.exists());self.assertFalse(b.exists())
    def test_queue_and_favorite_candidates_are_blocked(self):
        a=self.song('a/a.mid');b=self.song('b/b.mid',extra=b'\0');ids=self.db.add_files([a,b]);self.db.favorite(ids[1]);folder,summary=self.plan(protected={ids[1]})
        self.assertEqual(summary['counts']['blocked'],1)
        with self.assertRaises(ValueError):self.apply(folder,summary,[ids[1]])
        self.assertTrue(b.exists())
    def test_queue_added_after_review_prevents_apply(self):
        a=self.song('a/a.mid');b=self.song('b/b.mid',extra=b'\0');ids=self.db.add_files([a,b]);folder,summary=self.plan()
        self.assertEqual(self.apply(folder,summary,[ids[1]],protected=lambda:{ids[1]})['applied'],0);self.assertTrue(b.exists())
    def test_cancelled_scan_cannot_authorize_delete(self):
        self.add(self.song());cancel=threading.Event();cancel.set();folder,summary=self.plan(cancelled=cancel)
        self.assertFalse(summary['complete'])
        with self.assertRaises(ValueError):h.validate_plan(folder,summary['plan_sha256'])
    def test_missing_file_is_only_removed_from_index(self):
        a=self.song();sid=self.add(a);a.unlink();a.with_suffix('.lrc').unlink();folder,summary=self.plan()
        self.assertEqual(summary['counts']['invalid'],1);self.assertEqual(self.apply(folder,summary,[sid])['applied'],1);self.assertEqual(self.db.count(),0)
    @unittest.skip('v0.9.41 retired automatic-copy/hide/old cleanup; covered by test_v0941_*')
    def test_partial_file_delete_is_recoverable(self):
        a=self.song('a/a.mid');b=self.song('b/b.mid',extra=b'\0');ids=self.db.add_files([a,b]);folder,summary=self.plan();original=h.delete_verified;raw=b.read_bytes()
        def fail(part):
            if part['role']=='lrc':raise OSError('simulated failure')
            return original(part)
        with patch.object(h,'delete_verified',side_effect=fail):result=self.apply(folder,summary,[ids[1]])
        self.assertEqual(result['blocked'],1);self.assertFalse(b.exists());self.assertEqual(self.db.get(ids[1])['duplicate_state'],'')
        h.restore_action(self.db,folder,ids[1]);self.assertEqual(b.read_bytes(),raw)
    def test_plan_tamper_prevents_deletion(self):
        self.add(self.song());folder,summary=self.plan()
        with (folder/'plan.sqlite3').open('ab') as stream:stream.write(b'tampered')
        with self.assertRaises(ValueError):h.validate_plan(folder,summary['plan_sha256'])
    def test_settings_schema_rejects_bad_song_folders_and_marker(self):
        for value in (None,42,{},'wrong',[{'path':'x','type':[]}],[{'path':''}]):
            with self.subTest(value=value),self.assertRaises(ValueError):validate_settings({'song_folders':value})
        with self.assertRaises(ValueError):validate_settings({'song_locations_migrated':'yes'})
    def test_key_edit_validates_before_writing(self):
        sid=self.add(self.song());old=self.db.get(sid)
        with self.assertRaises(ValueError):self.db.edit(sid,'x','new','new','invalid key')
        self.assertEqual(self.db.get(sid),old)
        self.db.edit(sid,'x','new','new','Am');self.assertEqual(self.db.get(sid)['key_signature'],'Am')
    def test_selected_review_id_aborts_before_any_deletion(self):
        a=self.song('a/a.mid');b=self.song('b/b.mid',extra=b'\0');review=self.song('c/c.mid',key='');ids=self.db.add_files([a,b,review]);folder,summary=self.plan()
        with self.assertRaises(ValueError):self.apply(folder,summary,[ids[1],ids[2]])
        self.assertTrue(b.exists())
    def test_failed_backup_never_deletes_and_cleans_own_partial_backup(self):
        a=self.song('a/a.mid');b=self.song('b/b.mid',extra=b'\0');ids=self.db.add_files([a,b]);folder,summary=self.plan()
        with patch('karaoke.library_hygiene.shutil.copyfileobj',side_effect=OSError('simulated full disk')):result=self.apply(folder,summary,[ids[1]])
        self.assertEqual(result['applied'],0);self.assertTrue(b.exists());self.assertEqual(list((folder/'deletion-backup'/str(ids[1])).glob('*')),[])
    def test_restore_does_not_overwrite_existing_other_file(self):
        a=self.song('a/a.mid');b=self.song('b/b.mid',extra=b'\0');ids=self.db.add_files([a,b]);folder,summary=self.plan();self.apply(folder,summary,[ids[1]]);b.write_bytes(b'new external content')
        with self.assertRaises(ValueError):h.restore_action(self.db,folder,ids[1])
        self.assertEqual(b.read_bytes(),b'new external content')
    def test_journal_tamper_cannot_restore_outside_approved_paths(self):
        a=self.song('a/a.mid');b=self.song('b/b.mid',extra=b'\0');ids=self.db.add_files([a,b]);folder,summary=self.plan();self.apply(folder,summary,[ids[1]])
        with closing(sqlite3.connect(folder/'execution.sqlite3')) as db:
            action=json.loads(db.execute('SELECT data FROM actions WHERE id=?',(ids[1],)).fetchone()[0]);action['backups'][0]['source']=str(self.root/'unapproved.mid')
            db.execute('UPDATE actions SET data=? WHERE id=?',(json.dumps(action),ids[1]));db.commit()
        with self.assertRaises(ValueError):h.restore_action(self.db,folder,ids[1])
        self.assertFalse((self.root/'unapproved.mid').exists())
    @unittest.skip('v0.9.41 retired automatic-copy/hide/old cleanup; covered by test_v0941_*')
    def test_database_commit_failure_leaves_recoverable_backups(self):
        from contextlib import contextmanager
        a=self.song('a/a.mid');b=self.song('b/b.mid',extra=b'\0');ids=self.db.add_files([a,b]);folder,summary=self.plan();original=self.db.connect
        @contextmanager
        def fail_commit():
            with original() as db:
                yield db
                raise OSError('simulated commit failure')
        with patch.object(self.db,'backup_before_rebuild'),patch.object(self.db,'connect',fail_commit),self.assertRaises(OSError):self.apply(folder,summary,[ids[1]])
        self.assertFalse(b.exists());self.assertEqual(self.db.get(ids[1])['duplicate_state'],'')
        h.restore_action(self.db,folder,ids[1]);self.assertTrue(b.exists())
    def test_new_sidecar_on_keeper_after_report_blocks_delete(self):
        a=self.song('a/a.mid');b=self.song('b/b.mid',extra=b'\0');ids=self.db.add_files([a,b]);folder,summary=self.plan();a.with_suffix('.snf').write_bytes(b'changed')
        self.assertEqual(self.apply(folder,summary,[ids[1]])['applied'],0);self.assertTrue(b.exists())
    def test_incomplete_existing_file_is_excluded_until_fixed(self):
        path=self.song();sid=self.add(path);path.with_suffix('.lrc').unlink()
        with ImportSession(self.db,self.root/'Songs') as session:
            session.prepare()
            with self.assertRaises(PolicyRejected):session.import_one(path)
        self.assertEqual(self.db.count(),0);self.assertEqual(self.db.get(sid)['duplicate_state'],'invalid');self.assertTrue(path.exists())
    def test_existing_metadata_change_does_not_create_a_visible_duplicate(self):
        a=self.song('a/a.mid',title='One');b=self.song('b/b.mid',title='Two',extra=b'\0');ids=self.db.add_files([a,b]);b.with_suffix('.lrc').write_text(b.with_suffix('.lrc').read_text().replace('Two','One'))
        with ImportSession(self.db,self.root/'Songs') as session:session.prepare();row,_=session.import_one(b,True)
        self.assertEqual(row['duplicate_of'],0);self.assertEqual(self.db.count(),2)
    @unittest.skipUnless(os.name=='nt','Windows file sharing check')
    def test_open_file_denying_delete_is_not_deleted(self):
        import ctypes as c
        from ctypes import wintypes as w
        a=self.song('a/a.mid');b=self.song('b/b.mid',extra=b'\0');ids=self.db.add_files([a,b]);folder,summary=self.plan()
        kernel=c.WinDLL('kernel32',use_last_error=True);kernel.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,c.c_void_p,w.DWORD,w.DWORD,w.HANDLE];kernel.CreateFileW.restype=w.HANDLE;kernel.CloseHandle.argtypes=[w.HANDLE]
        handle=kernel.CreateFileW(str(b),0x80000000,1,None,3,0,None)
        try:
            self.assertNotEqual(handle,c.c_void_p(-1).value);result=self.apply(folder,summary,[ids[1]]);self.assertEqual(result['applied'],0);self.assertTrue(b.exists())
        finally:kernel.CloseHandle(handle)
    def test_parallel_scan_matches_single_worker(self):
        a=self.song('a/a.mid');b=self.song('b/b.mid',extra=b'\0');self.db.add_files([a,b]);single=self.plan()[1];parallel=self.plan(workers=2)[1]
        self.assertEqual(single['counts'],parallel['counts']);self.assertTrue(parallel['complete'])
    def test_file_catalog_key_conflict_is_review_not_deletion(self):
        path=self.song(key='D');sid=self.add(path)
        with self.db.connect() as db:db.execute("UPDATE songs SET key_signature='C' WHERE id=?",(sid,))
        folder,summary=self.plan();self.assertEqual(summary['counts']['review'],1)
        with self.assertRaises(ValueError):self.apply(folder,summary,[sid])
        self.assertTrue(path.exists())
    def test_manual_metadata_override_is_explicitly_preserved(self):
        path=self.song(key='D');sid=self.add(path);self.db.edit(sid,'CUSTOM','Manual title','Singer','C')
        self.assertEqual(assess(path,self.db.get(sid),crosscheck_metadata=True)['status'],'valid')
    def test_structural_reader_matches_playback_timing_and_metadata(self):
        from karaoke.midi_structure import parse_structure
        from karaoke.smf import parse_midi
        from tools.make_demo import meta,vlq
        import random
        for seed in range(12):
            rng=random.Random(seed);track=b'\0'+meta(3,b'Test title')+b'\0'+meta(0x59,bytes((seed%8,seed%2)))
            for n in range(30):
                track+=vlq(rng.randrange(1,240))+bytes((0x90,rng.randrange(40,80),50))
                if n%5==0:track+=b'\0'+meta(0x51,rng.randrange(300000,900000).to_bytes(3,'big'))
                if n%3==0:track+=b'\0'+meta(5,b'word ')
            track+=vlq(480)+meta(0x2f,b'')
            raw=b'MThd'+struct.pack('>IHHH',6,0,1,480)+b'MTrk'+len(track).to_bytes(4,'big')+track
            full=parse_midi(raw);fast=parse_structure(raw)
            self.assertAlmostEqual(full.duration,fast.duration);self.assertEqual(full.title,fast.title);self.assertEqual(full.key_signature,fast.key_signature)
            self.assertEqual([line.text for line in full.lyrics.lines],[line.text for line in fast.lyrics.lines]);self.assertTrue(fast.has_notes)
    def test_structural_reader_requires_complete_end_marker(self):
        from karaoke.midi_structure import parse_structure
        raw=midi_fixture();track=raw[22:-4];raw=raw[:18]+len(track).to_bytes(4,'big')+track
        with self.assertRaises(ValueError):parse_structure(raw)
    def test_legacy_archive_vector_transform_preserves_assets(self):
        from karaoke.emk import unpack_emk
        from test_studio import archive_fixture
        self.assertEqual(unpack_emk(archive_fixture(masked=True)),unpack_emk(archive_fixture(masked=False)))
    def test_persistent_queue_is_protected_without_explicit_callback(self):
        a=self.song('a/a.mid');b=self.song('b/b.mid',extra=b'\0');ids=self.db.add_files([a,b]);folder,summary=self.plan();queue=SongQueue(self.root/'Data/queue.json');queue.add(QueueItem(ids[1]))
        self.assertEqual(self.apply(folder,summary,[ids[1]])['applied'],0);self.assertTrue(b.exists())
    def test_data_lock_prevents_another_application_deleting(self):
        from karaoke.instance_lock import DataDirectoryLock
        a=self.song('a/a.mid');b=self.song('b/b.mid',extra=b'\0');ids=self.db.add_files([a,b]);folder,summary=self.plan();lock=DataDirectoryLock(self.root/'Data').acquire()
        try:
            with self.assertRaises(RuntimeError):self.apply(folder,summary,[ids[1]])
            self.assertTrue(b.exists())
        finally:lock.close()
    @unittest.skip('v0.9.41 retired automatic-copy/hide/old cleanup; covered by test_v0941_*')
    def test_incomplete_parent_removal_keeps_valid_alias_visible(self):
        bad=self.song('a/a.mid');good=self.song('b/b.mid',extra=b'\0');ids=self.db.add_files([bad,good]);bad.write_bytes(b'broken')
        with self.db.connect() as db:db.execute("UPDATE songs SET duplicate_of=?,duplicate_state='kept' WHERE id=?",(ids[0],ids[1]))
        folder,summary=self.plan();self.assertEqual(self.apply(folder,summary,[ids[0]])['applied'],1)
        self.assertTrue(good.exists());self.assertEqual(self.db.get(ids[1])['duplicate_of'],0);self.assertEqual(self.db.count(),1)
    @unittest.skip('v0.9.41 retired automatic-copy/hide/old cleanup; covered by test_v0941_*')
    def test_same_plan_can_delete_child_after_parent_promotion(self):
        bad=self.song('a/a.mid');good=self.song('b/b.mid',extra=b'\0');extra=self.song('c/c.mid',extra=b'\0\0');ids=self.db.add_files([bad,good,extra]);bad.write_bytes(b'broken')
        with self.db.connect() as db:db.executemany("UPDATE songs SET duplicate_of=?,duplicate_state='kept' WHERE id=?",[(ids[0],sid) for sid in ids[1:]])
        folder,summary=self.plan();result=self.apply(folder,summary,[ids[0],ids[2]])
        self.assertEqual(result['applied'],2);self.assertEqual(result['blocked'],0);self.assertTrue(good.exists());self.assertEqual(self.db.count(),1)
    @unittest.skip('v0.9.41 retired automatic-copy/hide/old cleanup; covered by test_v0941_*')
    def test_hardlinked_keeper_remains_when_duplicate_name_deleted(self):
        a=self.song('a/a.mid');b=self.root/'b/b.mid';b.parent.mkdir();os.link(a,b);b.with_suffix('.lrc').write_bytes(a.with_suffix('.lrc').read_bytes());raw=a.read_bytes();ids=self.db.add_files([a,b]);folder,summary=self.plan()
        self.assertEqual(self.apply(folder,summary,[ids[1]])['applied'],1);self.assertTrue(a.exists());self.assertEqual(a.read_bytes(),raw);self.assertFalse(b.exists())
    def test_playlist_preparation_does_not_commit_live_queue(self):
        path=self.song();playlist=self.root/'playlist.json';playlist.write_text(json.dumps({'format':'xstage.playlist','tracks':[{'path':str(path)}]}))
        queue=SongQueue(self.root/'queue.json');pending,missing=queue.import_file(playlist,self.db,enforce_policy=True,prepare_only=True)
        self.assertEqual(len(pending),1);self.assertEqual(missing,0);self.assertEqual(queue.items,[]);self.assertFalse(queue.path.exists());self.assertEqual(self.db.count(),1)
    def test_playlist_ui_appends_to_latest_queue(self):
        from karaoke.playlist_ui import handle_message
        queue=SongQueue(self.root/'queue.json');queue.add(QueueItem(10))
        app=NS(song_queue=queue,write_import_report=Mock(),refresh_library=Mock(),refresh_queue=Mock(),status_var=Mock(),show_error=Mock())
        handle_message(app,'playlist_ready',([QueueItem(20)],0,[]));self.assertEqual([item.song_id for item in queue.items],[10,20]);app.show_error.assert_not_called()
    def test_playlist_queue_commit_survives_report_failure(self):
        from karaoke.playlist_ui import handle_message
        queue=SongQueue(self.root/'queue.json');app=NS(song_queue=queue,write_import_report=Mock(side_effect=OSError('report full')),refresh_library=Mock(),refresh_queue=Mock(),status_var=Mock(),show_error=Mock())
        with self.assertLogs(level='ERROR'):handle_message(app,'playlist_ready',([QueueItem(20)],0,[]))
        self.assertEqual([item.song_id for item in queue.items],[20]);app.refresh_queue.assert_called_once();self.assertIn('นำเข้าคิว 1 เพลงแล้ว',str(app.show_error.call_args.args[0]))
    def test_large_supported_file_is_review_not_corrupt(self):
        path=self.root/'large.mid'
        with path.open('wb') as stream:stream.truncate(64*1024*1024+1)
        self.assertEqual(assess(path)['status'],'review')
    def test_large_emk_asset_limit_requires_review(self):
        from karaoke.emk import unpack_emk
        from karaoke.inspection_errors import ReviewRequired
        from test_studio import archive_fixture
        raw=archive_fixture(masked=False)
        with patch('karaoke.emk.MAX_ASSET',1),self.assertRaises(ReviewRequired):unpack_emk(raw)
    def test_lrc_offset_outside_song_is_invalid(self):
        path=self.song();path.with_suffix('.lrc').write_text('[key:C]\n[ar:Singer]\n[offset:999999999]\n[00:00]hello')
        self.assertEqual(assess(path)['status'],'invalid')
    def test_source_change_during_quality_check_is_rejected(self):
        from karaoke.song_policy import assess as original
        path=self.song()
        def changing(*args,**kwargs):
            result=original(*args,**kwargs);path.with_suffix('.lrc').write_text('broken');return result
        with patch('karaoke.song_policy.assess',side_effect=changing),self.assertRaises(PolicyRejected):self.import_song(path,copy_files=True)
        self.assertEqual(self.db.count(),0);self.assertFalse((self.root/'Songs').exists())
    def test_small_lrc_offset_is_valid(self):
        path=self.song();path.with_suffix('.lrc').write_text('[key:C]\n[ar:Singer]\n[offset:100]\n[00:00]hello')
        self.assertEqual(assess(path)['status'],'valid')
    def test_enhanced_word_times_outside_song_are_invalid(self):
        path=self.song();path.with_suffix('.lrc').write_text('[key:C]\n[ar:Singer]\n[00:00]<99:00>hello')
        self.assertEqual(assess(path)['status'],'invalid')
    @unittest.skip('v0.9.41 retired automatic-copy/hide/old cleanup; covered by test_v0941_*')
    def test_complete_hidden_keeper_is_promoted_before_duplicate_removed(self):
        a=self.song('a/a.mid');b=self.song('b/b.mid',extra=b'\0');ids=self.db.add_files([a,b])
        with self.db.connect() as db:db.execute("UPDATE songs SET duplicate_state='invalid',playable=0 WHERE id=?",(ids[0],))
        folder,summary=self.plan();self.assertEqual(self.apply(folder,summary,[ids[1]])['applied'],1)
        self.assertEqual(self.db.get(ids[0])['playable'],1);self.assertEqual(self.db.get(ids[0])['duplicate_state'],'');self.assertEqual(self.db.count(),1)
    def test_queue_mutation_is_locked_during_deletion(self):
        queue=SongQueue(self.root/'queue.json');queue._maintenance_locked=True
        with self.assertRaises(OSError):queue.add(QueueItem(1))
        self.assertEqual(queue.items,[])


@unittest.skipUnless(os.environ.get('DISPLAY'),'requires graphical display')
class QualityGuiTests(unittest.TestCase):
    def setUp(self):
        import gc;gc.collect()
        from karaoke.performer import PlaybackApp
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        with patch('karaoke.library.SongLibrary.has_songs',return_value=True):self.app=PlaybackApp(Path(__file__).resolve().parents[1],self.root/'Data',auto_catalog=False)
        self.errors=[];self.app.show_error=lambda error:self.errors.append(str(error));self.app.report_callback_exception=lambda *error:self.errors.append(str(error))
    def tearDown(self):
        import gc
        import time
        app=self.app;app.close_app();until=time.monotonic()+10
        while not app.__dict__.get('_shutdown_done') and time.monotonic()<until:app.update();time.sleep(.01)
        self.assertTrue(app.__dict__.get('_shutdown_done'));self.app=None;del app;gc.collect();self.temp.cleanup()
    def song(self,name,extra=b''):
        path=self.root/name;path.write_bytes(midi_fixture()+extra);path.with_suffix('.lrc').write_text('[ti:Song]\n[ar:Singer]\n[key:C]\n[00:00]first\n[00:01]last');return path
    def pump(self,predicate=lambda:False,timeout=20):
        import time
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            self.app.update()
            if predicate():return
            time.sleep(.01)
        raise AssertionError('GUI operation timeout')
    @unittest.skip('v0.9.41 retired automatic-copy/hide/old cleanup; covered by test_v0941_*')
    def test_scan_review_cancel_delete_and_restore(self):
        from karaoke.hygiene_ui import open_hygiene
        a=self.song('a.mid');b=self.song('b.mid',b'\0');ids=self.app.library.add_files([a,b]);manager=open_hygiene(self.app)
        # Use a single scanner in this lifecycle test; process workers are tested independently.
        original=h.scan
        with patch('karaoke.hygiene_ui.hygiene.scan',side_effect=lambda *args,**kw:original(*args,**dict(kw,workers=1))):
            manager.scan();self.pump(lambda:manager.folder is not None and not self.app.scanning)
        self.assertTrue(a.exists() and b.exists());self.assertEqual(len(manager.tree.get_children()),1)
        manager.tree.selection_set(str(ids[1]));manager.select()
        with patch('karaoke.hygiene_ui.simpledialog.askstring',return_value=None),patch('karaoke.hygiene_ui.hygiene.apply') as apply:manager.delete();apply.assert_not_called()
        with patch('karaoke.hygiene_ui.simpledialog.askstring',return_value='ลบ'):
            manager.delete();self.pump(lambda:not self.app.scanning and not getattr(self.app,'_cleanup_busy',False))
        self.assertTrue(a.exists());self.assertFalse(b.exists());self.assertFalse(self.app.song_queue._maintenance_locked)
        with patch('karaoke.hygiene_ui.simpledialog.askinteger',return_value=ids[1]),patch('karaoke.hygiene_ui.messagebox.askyesno',return_value=True):manager.restore();self.pump(lambda:not self.app.scanning)
        self.assertTrue(b.exists());self.assertFalse(self.errors,self.errors)
    def test_eq_save_failure_keeps_scheduled_tick(self):
        from karaoke.song_eq import key
        from karaoke.graphic_eq import flat
        self.app.settings['song_eq']={key({'path':'old.mid'}):flat()}
        self.app.messages.put(('song_replaced',('old.mid','new.mid')))
        if self.app.tick_after:self.app.after_cancel(self.app.tick_after);self.app.tick_after=None
        with patch.object(self.app,'save_settings',side_effect=OSError('simulated disk full')),self.assertLogs(level='ERROR'):self.app.tick()
        self.assertTrue(self.errors);self.assertIsNotNone(self.app.tick_after)
        self.assertTrue(self.app.tk.call('after','info',self.app.tick_after))
    def test_playing_is_refused_during_permanent_delete(self):
        self.app._cleanup_busy=True
        self.assertFalse(self.app.start_song(QueueItem(999)))
        self.app._cleanup_busy=False

    def test_close_cancels_all_owned_after_callbacks(self):
        self.app.after(20000,lambda:None)
        app=self.app;app.close_app()
        self.assertFalse(app.tk.call('after','info'))
        self.assertTrue(app._shutdown_done)
    def test_close_waits_for_owned_file_worker(self):
        import time
        entered=threading.Event();release=threading.Event()
        def worker():entered.set();release.wait(3)
        thread=threading.Thread(target=worker);self.app._index_thread=thread;thread.start();self.assertTrue(entered.wait(1))
        self.app.close_app();self.assertFalse(self.app.__dict__.get('_shutdown_done',False));self.assertTrue(self.app.cancel_scan.is_set())
        release.set();thread.join(1);self.pump(lambda:self.app.__dict__.get('_shutdown_done',False))

    def test_close_waits_for_final_queue_commit_message(self):
        path=self.song('queued.mid');sid=self.app.library.add_files([path])[0]
        thread=threading.Thread(target=lambda:None);thread.start();thread.join();self.app._index_thread=thread;self.app.scanning=True
        self.app.messages.put(('scan_done',(1,0,[])));self.app.messages.put(('playlist_ready',([QueueItem(sid)],0,[])))
        self.app.close_app();self.assertFalse(self.app.__dict__.get('_shutdown_done',False))
        self.pump(lambda:self.app.__dict__.get('_shutdown_done',False))
        saved=json.loads((self.root/'Data/queue.json').read_text());self.assertEqual(saved[0]['song_id'],sid)
