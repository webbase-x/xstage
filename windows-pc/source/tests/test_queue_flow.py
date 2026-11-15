import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock
from karaoke.library import QueueItem, SongQueue
from karaoke.performer import PlaybackApp


class QueueFlowTests(unittest.TestCase):
    def test_medley_batch_survives_restart_and_cancel_preserves_other_occurrences(self):
        with TemporaryDirectory() as folder:
            queue_path = Path(folder) / 'queue.json'
            queue_path.write_text('[{"song_id": 10}]', encoding='utf-8')
            queue = SongQueue(queue_path)
            queue.add_medley([QueueItem(20), QueueItem(21)], play_next=True)
            queue.add_medley([QueueItem(30)])
            queue = SongQueue(queue_path)
            self.assertEqual([item.song_id for item in queue.items], [20, 21, 10, 30])
            first, second, original, last = queue.items
            self.assertTrue(first.medley_session)
            self.assertEqual(first.medley_session, second.medley_session)
            self.assertEqual(original.medley_session, '')
            self.assertNotEqual(last.medley_session, first.medley_session)
            self.assertEqual(queue.cancel_medley(first.medley_session), 2)
            self.assertEqual([item.song_id for item in SongQueue(queue_path).items], [10, 30])

    def test_end_advances_even_if_old_auto_setting_was_off(self):
        app = SimpleNamespace(song_queue=SimpleNamespace(items=[object()]),
                              auto_var=Mock(get=lambda: False), next_song=Mock(), cancel_current_song=Mock())
        PlaybackApp.on_song_ended(app)
        app.next_song.assert_called_once_with()
        app.cancel_current_song.assert_not_called()

    def test_empty_end_releases_song_and_clears_stage(self):
        app = SimpleNamespace(song_queue=SimpleNamespace(items=[]), next_song=Mock(),
                              cancel_current_song=Mock(), now_var=Mock(), status_var=Mock(),
                              hide_queue_browser=Mock(), hide_transport=Mock(), paint_lyrics=Mock())
        PlaybackApp.on_song_ended(app)
        app.cancel_current_song.assert_called_once()
        self.assertTrue(app.finished_empty)
        app.now_var.set.assert_called_once_with('')
        app.hide_transport.assert_called_once_with(force=True)
        app.next_song.assert_not_called()
        app.paint_lyrics.assert_called_once()

    def test_navigation_reveals_selection_and_keeps_query_for_typing(self):
        tree = Mock()
        tree.get_children.return_value = ('one', 'two', 'three')
        tree.selection.return_value = ('one',)
        query = Mock()
        app = SimpleNamespace(search_visible=True, search_pending=False, songs=tree,
                              search_entry=Mock(), search_var=query, update_search_detail=Mock())
        PlaybackApp.navigate_search(app, 1)
        tree.selection_set.assert_called_once_with('two')
        tree.see.assert_called_once_with('two')
        app.search_entry.icursor.assert_called_once_with('end')
        app.search_entry.focus_set.assert_called_once()
        query.set.assert_not_called()

    def test_queue_right_down_left_up(self):
        items = [object(), object(), object()]
        app = SimpleNamespace(song_queue=SimpleNamespace(items=items), queue_browser_visible=True,
            _browsed_item=items[1], hide_search=Mock(), hide_transport=Mock(), update_queue_browser=Mock(),
            layout_overlays=Mock(), queue_browser=Mock(), focus_song_input=Mock())
        app._queue_position = lambda: items.index(app._browsed_item)
        PlaybackApp.browse_queue(app, 1)
        self.assertIs(app._browsed_item, items[2])
        PlaybackApp.browse_queue(app, -1)
        self.assertIs(app._browsed_item, items[1])

    def test_cancel_starts_next_immediately_without_countdown(self):
        from unittest.mock import patch
        old=Mock();items=[object(),object()]
        app=SimpleNamespace(engine=old,current_song={'title':'old'},current_item=object(),song_queue=SimpleNamespace(items=items),next_song=Mock())
        with patch('karaoke.performance_features.history_finish') as history:
            PlaybackApp.cancel_current_song(app)
        old.close.assert_called_once_with()
        history.assert_called_once_with(app,'interrupted')
        app.next_song.assert_called_once_with()
        self.assertIsNone(app.engine)
        self.assertIsNone(app.current_song)
        self.assertEqual(app._queue_countdown_seconds,0)

    def test_internal_cancel_does_not_consume_waiting_queue(self):
        from unittest.mock import patch
        names='key_var speed_var offset_var seek_var seek time_var beat_var now_var status_var show_main_media update_stage_mode paint_lyrics show_transport focus_song_input'
        app=SimpleNamespace(engine=Mock(),current_song={'title':'old'},current_item=object(),song_queue=SimpleNamespace(items=[object()]),next_song=Mock(),search_visible=False,remote=None)
        for name in names.split():setattr(app,name,Mock())
        with patch('karaoke.performance_features.history_finish'):
            PlaybackApp.cancel_current_song(app,advance=False)
        app.next_song.assert_not_called()
        self.assertEqual(len(app.song_queue.items),1)
        app.now_var.set.assert_called_with('')
