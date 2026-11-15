import copy
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
from karaoke.library import (SongQueue,SongLibrary,QueueItem,JsonRecoveryError,JsonConflictError,PlaylistImportError,
    parse_json,read_json,write_json,read_json_snapshot,file_revision)
from karaoke.json_recovery import preflight,inspect_candidate
from karaoke.restore import validate_backup
from karaoke.ui import KaraokeApp
from karaoke.classic import ClassicApp
from karaoke.performer import PlaybackApp
from karaoke.performance_features import PlayHistory,history_for_window
from karaoke.shutdown import ShutdownError
from karaoke.font_metadata import MetadataLoader
from karaoke.audio_dialog import AudioSettings
from test_studio import midi_fixture

class Validation073Tests(unittest.TestCase):
    def test_bad_setting_types_ranges_and_overflow_do_not_pass_preflight(self):
        for payload in (b'{"volume":"bad"}',b'{"volume":101}',b'{"stage_monitor":[]}',b'{"lyric_layout_version":"1"}',b'{"probe":1e400}'):
            with self.subTest(payload=payload),tempfile.TemporaryDirectory() as d:
                p=Path(d)/'settings.json';p.write_bytes(payload)
                with self.assertLogs(level='ERROR'):self.assertFalse(preflight(d,prompt=lambda e:False))
                self.assertEqual(p.read_bytes(),payload);self.assertEqual(next(Path(d).glob('*.bak')).read_bytes(),payload)
    def test_overflow_rejected_at_any_depth(self):
        for text in ('1e400','-1e400','{"x":[1e400]}'):
            with self.subTest(text=text),self.assertRaises(ValueError):parse_json(text)
        self.assertEqual(parse_json('{"x":1.25}'),{'x':1.25})
    def test_invalid_settings_candidate_and_new_save_leave_target_intact(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'settings.json';p.write_bytes(b'{}');source=Path(d)/'backup.json';source.write_bytes(b'{"volume":"bad"}')
            with self.assertRaises(ValueError):inspect_candidate(p,source)
            with self.assertRaises(ValueError):write_json(p,{'volume':float('inf')})
            self.assertEqual(p.read_bytes(),b'{}')
    def test_valid_legacy_numeric_settings_are_not_mutated(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'settings.json';value={'volume':'75','font_size':'84','stage_monitor':1,'custom':{'x':2}}
            write_json(p,value);self.assertEqual(read_json(p,{}),value)
    def backup(self,root,settings,queue=b'[]'):
        SongLibrary(root/'songs.sqlite3');(root/'settings.json').write_bytes(settings);(root/'queue.json').write_bytes(queue)
    def test_full_backup_rejects_duplicate_settings_and_queue_keys(self):
        for settings,queue in ((b'{"volume":10,"volume":90}',b'[]'),(b'{}',b'[{"song_id":1,"song_id":2}]')):
            with self.subTest(settings=settings),tempfile.TemporaryDirectory() as d:
                root=Path(d);self.backup(root,settings,queue)
                with self.assertRaisesRegex(ValueError,'คีย์ซ้ำ'):validate_backup(root)
    def test_full_backup_uses_same_setting_validator_and_accepts_bom(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.backup(root,b'{"volume":"bad"}')
            with self.assertRaises(ValueError):validate_backup(root)
            (root/'settings.json').write_bytes(b'\xef\xbb\xbf{"volume":50}')
            (root/'queue.json').write_bytes(b'\xef\xbb\xbf[]')
            self.assertEqual(validate_backup(root)['settings']['volume'],50)

class Revision073Tests(unittest.TestCase):
    def test_external_valid_queue_changes_are_kept_and_memory_rolls_back(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'queue.json';q=SongQueue(p);q.add(QueueItem(1));write_json(p,[{'song_id':1},{'song_id':2}])
            with self.assertRaises(JsonConflictError):q.add(QueueItem(3))
            self.assertEqual([x['song_id'] for x in read_json(p,[])],[1,2]);self.assertEqual(q.items,[QueueItem(1)])
            fresh=SongQueue(p);fresh.add(QueueItem(3));self.assertEqual([x['song_id'] for x in read_json(p,[])],[1,2,3])
    def test_external_creation_before_first_save_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'queue.json';q=SongQueue(p);write_json(p,[{'song_id':2}])
            with self.assertRaises(JsonConflictError):q.add(QueueItem(1))
            self.assertEqual(read_json(p,[]),[{'song_id':2}]);self.assertFalse(list(Path(d).glob('*.tmp')))
    def test_settings_cached_save_rejects_new_external_values(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'settings.json';write_json(p,{'volume':10});settings,revision=read_json_snapshot(p,{})
            write_json(p,{'volume':20,'external':True})
            fake=NS(settings=settings,settings_path=p,_settings_revision=revision,volume_var=NS(get=lambda:30),auto_var=NS(get=lambda:True))
            with self.assertRaises(JsonConflictError):KaraokeApp.save_settings(fake)
            self.assertEqual(read_json(p,{}),{'volume':20,'external':True})
    def test_history_conflict_preserves_disk_and_manual_window_reload_gets_latest(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'history.json';h=PlayHistory(p);h.start(QueueItem(1),{'path':'one.mid'})
            rows=read_json(p,[]);rows.append(dict(time='now',title='two',path='two.mid',status='completed',item={'song_id':2}));write_json(p,rows)
            with self.assertRaises(JsonConflictError):h.start(QueueItem(3),{'path':'three.mid'})
            self.assertEqual(len(read_json(p,[])),2);self.assertEqual(len(h.rows),1)
            app=NS(data_dir=Path(d),_play_history=h);self.assertEqual(len(history_for_window(app).rows),2)
    def test_change_just_before_replace_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'data.json';write_json(p,{'x':1});revision=file_revision(p)
            def change(path):p.write_bytes(b'{"external":true}');return file_revision(path)
            with patch('karaoke.library.file_revision',side_effect=change):
                with self.assertRaises(JsonConflictError):write_json(p,{'x':2},expected_revision=revision)
            self.assertEqual(p.read_bytes(),b'{"external":true}');self.assertFalse(list(Path(d).glob('*.tmp')))
    def test_sequential_owner_saves_keep_revision_and_thai_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'settings.json';revision=write_json(p,{'volume':25,'name':'เพลง'})
            revision=write_json(p,{'volume':30,'name':'เพลง'},expected_revision=revision)
            self.assertEqual(revision,file_revision(p));self.assertEqual(read_json(p,{})['name'],'เพลง')

class Shutdown073Tests(unittest.TestCase):
    def obj(self,cls=NS):
        obj=cls() if cls is NS else cls.__new__(cls)
        obj.cancel_scan=threading.Event();obj.tick_after=None;obj.search_after=None;obj.save_settings=Mock();obj.song_queue=NS(save=Mock());obj.engine=NS(close=Mock());obj.destroy=Mock();obj.show_error=Mock()
        return obj
    def test_save_failure_does_not_skip_queue_engine_or_window(self):
        obj=self.obj();obj.save_settings.side_effect=OSError('disk full')
        with self.assertLogs(level='ERROR'),self.assertRaises(ShutdownError):KaraokeApp.close_app(obj)
        obj.song_queue.save.assert_called_once();obj.engine.close.assert_called_once();obj.destroy.assert_called_once();obj.show_error.assert_called_once()
    def test_queue_and_engine_failures_still_close_window(self):
        obj=self.obj();obj.song_queue.save.side_effect=OSError('queue');obj.engine.close.side_effect=OSError('engine')
        with self.assertLogs(level='ERROR'),self.assertRaises(ShutdownError):KaraokeApp.close_app(obj)
        obj.destroy.assert_called_once();self.assertEqual(len(obj._shutdown_errors),2)
    def test_classic_remote_and_recorder_failures_do_not_stop_base_cleanup(self):
        obj=self.obj(ClassicApp);obj.remote=Mock();obj.remote.close.side_effect=OSError('remote');obj.recorder=Mock();obj.recorder.stop.side_effect=OSError('recorder')
        recorder=obj.recorder
        with self.assertLogs(level='ERROR'),self.assertRaises(ShutdownError):ClassicApp.close_app(obj)
        recorder.stop.assert_called_once();obj.engine.close.assert_called_once();obj.destroy.assert_called_once()
    def test_performer_failures_continue_through_all_layers(self):
        obj=self.obj(PlaybackApp);obj.remote=None;obj.recorder=None;obj._search_condition=threading.Condition();obj._keyboard_voice=Mock();obj._keyboard_voice.close.side_effect=OSError('voice');obj._fx_rack=Mock();obj._fx_rack.close.side_effect=OSError('fx');obj.system_volume=Mock()
        with patch('karaoke.medley_decks.cleanup',side_effect=OSError('medley')),self.assertLogs(level='ERROR'),self.assertRaises(ShutdownError):PlaybackApp.close_app(obj)
        obj.system_volume.close.assert_called_once();obj.engine.close.assert_called_once();obj.destroy.assert_called_once();self.assertTrue(obj._search_stopping)
    def test_destroy_error_is_reported(self):
        obj=self.obj();obj.destroy.side_effect=OSError('destroy')
        with self.assertLogs(level='ERROR'),self.assertRaises(ShutdownError):KaraokeApp.close_app(obj)
        obj.engine.close.assert_called_once()

class PartialImport073Tests(unittest.TestCase):
    def test_index_success_queue_failure_is_explicit_and_queue_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);song=root/'one.mid';song.write_bytes(midi_fixture());library=SongLibrary(root/'songs.sqlite3');q=SongQueue(root/'queue.json');playlist=root/'playlist.json';playlist.write_text(json.dumps({'format':'xstage.playlist','tracks':[{'path':str(song)}]}))
            with patch.object(q,'save',side_effect=OSError('queue failure')),self.assertRaises(PlaylistImportError) as caught:q.import_file(playlist,library)
            self.assertEqual(caught.exception.indexed_count,1);self.assertFalse(caught.exception.queue_saved);self.assertEqual(q.items,[]);self.assertEqual(library.count(),1)
            self.assertIn('คิวเดิมคงอยู่',str(caught.exception))
    def test_ui_refreshes_index_and_shows_partial_result(self):
        from karaoke.playlist_ui import handle_message
        app=NS(song_queue=NS(items=[],_commit=Mock(side_effect=OSError('simulated'))),library=Mock(),write_import_report=Mock(),refresh_library=Mock(),refresh_queue=Mock(),show_error=Mock(),status_var=Mock())
        with self.assertLogs(level='ERROR'):handle_message(app,'playlist_ready',([QueueItem(1),QueueItem(2)],0,[]))
        app.refresh_library.assert_called_once();app.refresh_queue.assert_called_once()
        error=app.show_error.call_args.args[0];self.assertIsInstance(error,PlaylistImportError);self.assertEqual(error.indexed_count,2);self.assertFalse(error.queue_saved)

class Detail073Tests(unittest.TestCase):
    def test_selected_returns_while_metadata_is_blocked_on_worker(self):
        entered=threading.Event();release=threading.Event();threads=[]
        def inspect(path):entered.set();threads.append(threading.get_ident());release.wait(3);return {'summary':'loaded','size':1024,'presets':[]}
        obj=AudioSettings.__new__(AudioSettings);row={'path':'slow.sf2','gain_db':-6};obj.fonts=[row];obj._gain_row=row;obj.index=lambda:0;obj.detail=Mock();obj._detail_loader=MetadataLoader(inspect);obj._detail_poll=None;obj._detail_token=0;obj.after=Mock(return_value='timer');obj.after_cancel=Mock();obj.winfo_exists=lambda:True
        try:
            AudioSettings.selected(obj);self.assertTrue(entered.wait(1));self.assertFalse(release.is_set());self.assertNotEqual(threads[0],threading.get_ident())
            token=obj._detail_token;release.set()
            with obj._detail_loader.condition:self.assertTrue(obj._detail_loader.condition.wait_for(lambda:obj._detail_loader.result is not None,timeout=2))
            obj.poll_detail(token);self.assertIn('loaded',obj.detail.set.call_args.args[0])
        finally:release.set();obj._detail_loader.close();obj._detail_loader.thread.join(2)
    def test_stale_detail_callback_does_not_consume_latest_result(self):
        obj=AudioSettings.__new__(AudioSettings);obj._detail_token=3;obj._detail_loader=Mock();obj.winfo_exists=lambda:True
        obj.poll_detail(2);obj._detail_loader.take.assert_not_called()


@unittest.skipUnless(os.environ.get('DISPLAY'),'requires explicit GUI test display')
class DetailGui073Tests(unittest.TestCase):
    def test_slow_detail_selection_keeps_gui_responsive_latest_wins_and_close_cleans(self):
        import tkinter as tk
        import time
        from karaoke.soundfont import inspect_font
        from soundfont_fixture import make_font
        root=tk.Tk();errors=[];root.report_callback_exception=lambda *args:errors.append(args)
        release=threading.Event();entered=threading.Event();win=None;workers=[]
        try:
            with tempfile.TemporaryDirectory() as d:
                first=make_font(Path(d)/'first.sf2');second=make_font(Path(d)/'second.sf2')
                info=inspect_font(first)
                def slow(path):
                    if Path(path)==first:entered.set();release.wait(3)
                    return dict(info,summary=Path(path).name)
                root.home=Path(__file__).resolve().parents[1];root.settings={'soundfont_audio':{'fonts':[{'path':str(first),'gain_db':-6},{'path':str(second),'gain_db':-6}]}};root.engine=None;root.status_var=tk.StringVar(root);root.save_settings=Mock();KaraokeApp._setup_style(root)
                with patch('karaoke.font_metadata.inspect_font',side_effect=slow):
                    win=AudioSettings(root);root.update();self.assertTrue(entered.wait(1))
                    pulse=[];root.after(0,lambda:pulse.append(True));root.update();self.assertEqual(pulse,[True])
                    win.tree.selection_set('1');root.update();release.set()
                    deadline=time.monotonic()+3
                    while str(second) not in win.detail.get() and time.monotonic()<deadline:root.update();time.sleep(.01)
                    self.assertIn(str(second),win.detail.get());self.assertNotIn(str(first),win.detail.get())
                    workers=[win._detail_loader,win.browser.loader];win.destroy();root.update()
                    self.assertTrue(all(worker.closed for worker in workers));self.assertFalse(errors,errors)
        finally:
            release.set()
            if win is not None:
                try:
                    if win.winfo_exists():win.destroy()
                except tk.TclError:pass
            for worker in workers:
                worker.close()
                if worker.thread:worker.thread.join(2)
            root.destroy()
