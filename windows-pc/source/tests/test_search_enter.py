import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock
from karaoke.performer import PlaybackApp

class SearchEnterTests(unittest.TestCase):
    def app(self):
        app=NS(search_revision=4,search_result_revision=3,search_pending=True,search_visible=True,
               search_after=None,status_var=Mock(),songs=Mock(),song_count=Mock(),
               update_search_detail=Mock(),confirm_search=Mock(),play_search_now=Mock())
        app.songs.get_children.return_value=('12',)
        app.defer_search_action=lambda action:PlaybackApp.defer_search_action(app,action)
        return app
    def test_enter_waits_once_then_confirms_without_second_press(self):
        app=self.app()
        PlaybackApp.confirm_search(app);PlaybackApp.confirm_search(app)
        PlaybackApp.search_results_ready(app)
        app.confirm_search.assert_called_once_with()
        PlaybackApp.search_results_ready(app)
        app.confirm_search.assert_called_once_with()
    def test_control_enter_preserves_immediate_play_intent(self):
        app=self.app();PlaybackApp.play_search_now(app)
        PlaybackApp.search_results_ready(app)
        app.play_search_now.assert_called_once_with();app.confirm_search.assert_not_called()
    def test_changed_query_or_closed_overlay_never_plays(self):
        for changed in ('query','closed'):
            app=self.app();PlaybackApp.confirm_search(app)
            if changed=='query':app.search_revision+=1
            else:app.search_visible=False
            PlaybackApp.search_results_ready(app)
            app.confirm_search.assert_not_called();app.play_search_now.assert_not_called()
    def test_empty_results_discard_pending_enter(self):
        app=self.app();PlaybackApp.confirm_search(app);app.songs.get_children.return_value=()
        PlaybackApp.search_results_ready(app)
        app.confirm_search.assert_not_called()
        self.assertIsNone(app.__dict__.get('_pending_search_action'))
    def test_enter_flushes_idle_search_without_waiting_or_duplicate_worker(self):
        app=self.app();app.search_after='idle-4';app.after_cancel=Mock()
        def refresh():app.search_revision+=1;app.search_after=None
        app.refresh_library=Mock(side_effect=refresh)
        PlaybackApp.confirm_search(app)
        app.after_cancel.assert_called_once_with('idle-4')
        self.assertEqual(app._pending_search_action,(5,'confirm'))
        PlaybackApp.confirm_search(app)
        app.refresh_library.assert_called_once_with()
