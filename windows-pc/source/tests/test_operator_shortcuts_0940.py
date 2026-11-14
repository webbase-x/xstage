"""v0.9.40: indexed exact-code results, next-queue keypad, restrained meter."""
import tempfile
from contextlib import closing
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
from karaoke.library import SongLibrary, QueueItem
from karaoke.performer import PlaybackApp
from karaoke.eq_meter import PeakMeter, METER_VISIBLE_INTERVAL_MS, METER_HIDDEN_INTERVAL_MS

class OperatorSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.library = SongLibrary(Path(self.temp.name)/'songs.sqlite3')
        rows = [('20120','ตัวจริง','ศิลปิน'),('201201','หมายเลขคล้าย','ศิลปิน'),
                ('39001','ชื่อที่มีเลข 20120','20120')]
        self.library.upsert_catalog([dict(path=str(Path(self.temp.name)/(code+'.mid')),
            code=code,title=title,artist=artist,kind='MIDI',playable=1) for code,title,artist in rows])

    def test_numeric_code_uses_existing_sqlite_index_without_ram_snapshot(self):
        with closing(self.library.open_reader()) as reader:
            rows = reader.search('20120', limit=20, playable_only=True)
            self.assertEqual([row['code'] for row in rows], ['20120'])
            indexes = ' '.join(row[3] for row in reader.db.execute(
                'EXPLAIN QUERY PLAN SELECT id FROM songs INDEXED BY songs_code '
                'WHERE code=? AND duplicate_of=0 ORDER BY id LIMIT ?',('20120',10)))
            self.assertIn('songs_code',indexes)
            self.assertEqual([row['code'] for row in reader.search('2012')][:2], ['20120','201201'])
            self.assertTrue(reader.search('ตัวจริง'))

    def test_code_with_zero_prefix_is_not_converted_to_integer(self):
        self.library.upsert_catalog([dict(path=str(Path(self.temp.name)/'zero.mid'),
            code='00120',title='ศูนย์นำหน้า',artist='',kind='MIDI',playable=1)])
        self.assertEqual(self.library.search('00120', limit=1)[0]['code'],'00120')

    def test_unavailable_exact_code_is_not_returned_as_playable(self):
        with self.library.connect() as db:
            db.execute("UPDATE songs SET duplicate_state='missing' WHERE code='20120'")
        self.assertNotIn('20120',[r['code'] for r in self.library.search('20120',playable_only=True)])

class OperatorShortcutTests(unittest.TestCase):
    @staticmethod
    def fake_app():
        song=dict(id=17,title='ทดสอบ',playable=1,path='test.mid')
        queue=[]
        app=NS(search_pending=False,search_revision=2,search_result_revision=2,
            _search_insert_next=True,search_visible=True,song_queue=NS(items=queue,insert=lambda i,x:queue.insert(i,x)),
            library=NS(get=lambda i:song),songs=Mock(),
            search_queue_item=lambda i:QueueItem(i),can_play_search_immediately=Mock(return_value=True),
            start_song=Mock(),status_var=Mock(),refresh_queue=Mock(),remember_search=Mock(),
            consume_search_key=Mock(),hide_search=Mock())
        app.songs.selection.return_value=('17',)
        return app

    def test_asterisk_opens_explicit_insert_mode_without_global_hook(self):
        app=NS(search_visible=False,search_entry=Mock(),search_popup=Mock(),status_var=Mock(),
               _search_insert_next=False)
        widget=app.search_entry
        widget.winfo_toplevel.return_value=app
        widget.winfo_class.return_value='TEntry'
        event=NS(widget=widget,state=0)
        self.assertEqual(PlaybackApp.insert_next_code_shortcut(app,event),'break')
        self.assertTrue(app._search_insert_next)
        app.search_popup.assert_called_once_with(initial='',select_all=False)
        app.search_visible=True
        self.assertIsNone(PlaybackApp.insert_next_code_shortcut(app,event))

    def test_shortcut_does_not_steal_other_text_editors_or_modified_keys(self):
        app=NS(search_visible=False,search_entry=Mock(),search_popup=Mock(),status_var=Mock())
        other=Mock();other.winfo_toplevel.return_value=app;other.winfo_class.return_value='TEntry'
        self.assertIsNone(PlaybackApp.insert_next_code_shortcut(app,NS(widget=other,state=0)))
        app.search_entry.winfo_toplevel.return_value=app
        self.assertIsNone(PlaybackApp.insert_next_code_shortcut(app,NS(widget=app.search_entry,state=4)))
        app.search_popup.assert_not_called()

    def test_enter_in_insert_mode_prepends_without_interrupting_current_song(self):
        app=self.fake_app()
        app.song_queue.items.append(QueueItem(999))
        PlaybackApp.confirm_search(app)
        self.assertEqual([i.song_id for i in app.song_queue.items],[17,999])
        app.start_song.assert_not_called()
        app.refresh_queue.assert_called_once_with(0)
        app.hide_search.assert_called_once()
        app.can_play_search_immediately.assert_not_called()

    def test_empty_selection_does_not_change_queue(self):
        app=self.fake_app();app.songs.selection.return_value=()
        PlaybackApp.confirm_search(app)
        self.assertEqual(app.song_queue.items,[])

    def test_pending_search_defers_action_without_stale_song(self):
        app=self.fake_app();app.search_pending=True;app.defer_search_action=Mock(return_value='break')
        self.assertEqual(PlaybackApp.confirm_search(app),'break')
        app.defer_search_action.assert_called_once_with('confirm')
        self.assertEqual(app.song_queue.items,[])

    def test_search_mode_prompts_for_next_queue(self):
        app=NS(_search_insert_next=True,can_play_search_immediately=Mock())
        self.assertIn('เพลงถัดไป',PlaybackApp.search_action_text(app))
        app.can_play_search_immediately.assert_not_called()

class MeterCadenceTests(unittest.TestCase):
    @staticmethod
    def meter(visible):
        capture=NS(stop_event=Mock(),thread=None,start=Mock(),stop=Mock(),read=Mock(return_value=(.2,.1)),name='')
        return NS(timer=None,winfo_ismapped=lambda:visible,was_visible=False,capture=capture,
                  source=None,holds=[],until=[],clips=[],render=Mock(),after=Mock(),poll=Mock())

    def test_visible_meter_uses_bounded_ui_refresh_rate(self):
        meter=self.meter(True)
        PeakMeter.poll(meter)
        self.assertEqual(meter.after.call_args.args[0],METER_VISIBLE_INTERVAL_MS)
        meter.capture.start.assert_called_once()

    def test_hidden_meter_suspends_capture_and_uses_sparse_checks(self):
        meter=self.meter(False);meter.was_visible=True
        PeakMeter.poll(meter)
        self.assertEqual(meter.after.call_args.args[0],METER_HIDDEN_INTERVAL_MS)
        meter.capture.stop.assert_called_once()
        meter.render.assert_not_called()

if __name__=='__main__': unittest.main()
