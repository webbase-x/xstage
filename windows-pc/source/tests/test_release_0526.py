import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from karaoke.performer import PlaybackApp
from karaoke.classic import ClassicApp
from karaoke.ui import KaraokeApp
from karaoke.library import SongQueue, QueueItem, song_supports_key

class Release526Tests(unittest.TestCase):
    def search_app(self, path='song.mid'):
        app=NS(search_visible=True,search_pending=False,search_revision=1,search_result_revision=1,
            _search_key_offsets={1:2},songs=Mock(),library=Mock(),status_var=Mock(),refresh_queue=Mock(),
            remember_search=Mock(),hide_search=Mock(),update_search_detail=Mock(),engine=None,
            start_song=Mock(return_value=True),song_queue=NS(items=[]))
        app.songs.selection.return_value=('1',)
        app.library.get.return_value={'id':1,'title':'same song','playable':True,'path':path}
        app.song_queue.add=app.song_queue.items.append
        app.search_queue_item=lambda i:PlaybackApp.search_queue_item(app,i)
        app.consume_search_key=lambda i:PlaybackApp.consume_search_key(app,i)
        app.play_search_now=lambda:PlaybackApp.play_search_now(app)
        app.play_selected=lambda:PlaybackApp.play_selected(app)
        app.can_play_search_immediately=lambda:False
        return app
    def test_duplicate_song_queue_entries_have_independent_keys(self):
        app=self.search_app()
        PlaybackApp.add_selected(app)
        app._search_key_offsets[1]=-1
        PlaybackApp.add_selected(app)
        PlaybackApp.add_selected(app)
        self.assertEqual([x.key for x in app.song_queue.items],[2,-1,0])
        self.assertIsNot(app.song_queue.items[0],app.song_queue.items[1])
    def test_enter_consumes_draft_key_only_after_adding(self):
        app=self.search_app()
        PlaybackApp.confirm_search(app)
        self.assertEqual(app.song_queue.items[0].key,2)
        self.assertEqual(app.search_queue_item(1).key,0)
    def test_f5_uses_same_key_as_enter_then_resets_next_request(self):
        app=self.search_app()
        KaraokeApp.play_pause(app)
        self.assertEqual(app.start_song.call_args.args[0].key,2)
        self.assertEqual(app.search_queue_item(1).key,0)
    def test_failed_immediate_play_keeps_draft(self):
        app=self.search_app();app.start_song.return_value=False
        PlaybackApp.play_search_now(app)
        self.assertEqual(app.search_queue_item(1).key,2)
    def test_edit_one_queue_instance_persists_without_changing_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'queue.json';queue=SongQueue(path)
            queue.add(QueueItem(1,key=2));queue.add(QueueItem(1,key=-1))
            app=NS(song_queue=queue,library=Mock(get=lambda i:{'path':'x.mid'}),refresh_queue=Mock(),status_var=Mock())
            PlaybackApp.adjust_queue_key(app,1,-1)
            self.assertEqual([x.key for x in SongQueue(path).items],[2,-2])
    def test_media_cannot_have_search_transposition(self):
        app=self.search_app('song.mp4')
        self.assertEqual(app.search_queue_item(1).key,0)
        app.search_entry=Mock();app.stage=None
        app.search_entry.winfo_toplevel.return_value=app
        PlaybackApp.change_key_shortcut(app,NS(widget=app.search_entry,state=0),1)
        self.assertEqual(app._search_key_offsets,{1:2})
        app.update_search_detail.assert_not_called()
    @patch('karaoke.pcm_player.available',return_value=False)
    def test_media_queue_key_change_is_rejected(self, _available):
        app=NS(song_queue=NS(items=[QueueItem(1)],save=Mock()),library=Mock(get=lambda i:{'path':'x.wav'}),status_var=Mock())
        PlaybackApp.adjust_queue_key(app,0,1)
        self.assertEqual(app.song_queue.items[0].key,0);app.song_queue.save.assert_not_called()
    def test_remote_media_key_is_rejected(self):
        app=NS(engine=None,key_var=Mock())
        with self.assertRaises(ValueError):ClassicApp.apply_remote(app,{'action':'key','value':3})
        app.key_var.set.assert_not_called()
    def test_f10_selects_first_row_and_focuses_table(self):
        app=NS(queue_index=lambda:None,song_queue=NS(items=[object()]),refresh_queue=Mock(),queue_window=Mock(),queues=Mock())
        PlaybackApp.show_queue(app)
        app.refresh_queue.assert_called_once_with(0);app.queues.focus_set.assert_called_once()
    def test_refresh_preserves_selection_and_clamps_removed_tail(self):
        app=NS(queues=Mock(),queue_title=Mock(),library=Mock(get=lambda i:{'title':'song'}),song_queue=NS(items=[QueueItem(1),QueueItem(2)]))
        app.queues.selection.return_value=('4',)
        app.queues.get_children.return_value=()
        KaraokeApp.refresh_queue(app)
        app.queues.selection_set.assert_called_once_with('1');app.queues.focus.assert_called_once_with('1')
    def test_stamp_only_uses_original_playback_instance(self):
        old=NS(position=12);song={'path':'a.mid'};app=NS(engine=old,current_song=song)
        self.assertEqual(ClassicApp.lyric_stamp_position(app,song,old),12)
        app.engine=NS(position=99)
        self.assertIsNone(ClassicApp.lyric_stamp_position(app,song,old))
        app.engine=old;app.current_song={'path':'b.mid'}
        self.assertIsNone(ClassicApp.lyric_stamp_position(app,song,old))
    def test_windows_alt_mask_cannot_become_plain_queue_arrow(self):
        app=NS(browse_queue=Mock())
        with patch('karaoke.keyboard_input.sys.platform','win32'):
            self.assertIsNone(PlaybackApp.arrow_press(app,NS(state=0x20000)))
        app.browse_queue.assert_not_called()
    def test_supported_formats_only(self):
        for name in ['a.MID','a.kar','a.emk','a.midi']:self.assertTrue(song_supports_key({'path':name}))
        with patch('karaoke.pcm_player.available',return_value=False):
            for name in ['a.mp3','a.wav','a.mp4','']:self.assertFalse(song_supports_key({'path':name}))
    def test_backend_setup_failure_keeps_entire_queue(self):
        items=[QueueItem(1),QueueItem(2)]
        app=NS(song_queue=NS(items=items,pop=Mock()),start_song=Mock(side_effect=OSError('soundfont missing')),
            cancel_current_song=Mock(),status_var=Mock(),refresh_queue=Mock())
        with self.assertLogs():KaraokeApp.next_song(app)
        self.assertEqual(len(items),2);app.song_queue.pop.assert_not_called()
        app.start_song.assert_called_once();app.cancel_current_song.assert_called_once()

    def test_jump_removes_only_selected_occurrence_preserving_queue_order(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'queue.json';q=SongQueue(path)
            for item in [QueueItem(1,key=2),QueueItem(2),QueueItem(1,key=-1),QueueItem(3)]:q.add(item)
            chosen=q.items[2];order=[]
            app=NS(song_queue=q,cancel_current_song=lambda **kwargs:order.append('cancel'),
                start_song=lambda item,quiet:order.append(item) or True,refresh_queue=Mock(),status_var=Mock())
            PlaybackApp.play_queue_now(app,2)
            self.assertEqual(order,['cancel',chosen])
            self.assertEqual([(x.song_id,x.key) for x in SongQueue(path).items],[(1,2),(2,0),(3,0)])
            app.next_song=Mock();PlaybackApp.on_song_ended(app)
            app.next_song.assert_called_once_with()

    def test_failed_manual_jump_does_not_skip_or_remove_any_waiting_song(self):
        items=[QueueItem(1),QueueItem(2),QueueItem(3)]
        app=NS(song_queue=NS(items=items,pop=Mock()),cancel_current_song=Mock(),start_song=Mock(return_value=False),
            refresh_queue=Mock(),status_var=Mock())
        PlaybackApp.play_queue_now(app,1)
        app.song_queue.pop.assert_not_called();self.assertEqual(len(items),3)
        app.start_song.assert_called_once_with(items[1],quiet=True)

    def test_consumed_key_refreshes_search_display_for_next_singer(self):
        app=self.search_app();app._search_rows={}
        PlaybackApp.consume_search_key(app,1)
        app.update_search_detail.assert_called_once()
        self.assertEqual(app.search_queue_item(1).key,0)
