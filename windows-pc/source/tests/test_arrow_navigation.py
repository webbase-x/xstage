import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock
from karaoke.performer import PlaybackApp

class ArrowNavigationTests(unittest.TestCase):
    def app(self):
        app=NS(search_entry=Mock(),stage=None,hide_search=Mock(),
               browse_queue=Mock(return_value='break'),navigate_search=Mock(return_value='break'))
        app.search_entry.winfo_toplevel.return_value=app
        app.search_entry.winfo_class.return_value='TEntry'
        return app
    def press(self,app,key):
        return PlaybackApp.arrow_press(app,NS(widget=app.search_entry,keysym=key,state=0))
    def release(self,app,key):
        PlaybackApp.arrow_release(app,NS(keysym=key))
    def test_right_switches_immediately_while_down_is_held(self):
        app=self.app();self.press(app,'Down');self.press(app,'Down')
        self.press(app,'Right')
        app.hide_search.assert_called_once();app.browse_queue.assert_called_once_with(1)
        count=app.navigate_search.call_count
        for _ in range(10):self.press(app,'Down')
        self.assertEqual(app.navigate_search.call_count,count)
        self.release(app,'Right');self.press(app,'Down')
        self.assertEqual(app.navigate_search.call_count,count)
        self.release(app,'Down');self.press(app,'Down')
        self.assertEqual(app.navigate_search.call_count,count+1)
    def test_left_wins_over_held_up(self):
        app=self.app();self.press(app,'Up');self.press(app,'Left');self.press(app,'Up')
        app.browse_queue.assert_called_once_with(-1)
        app.navigate_search.assert_called_once_with(-1)
    def test_new_vertical_press_switches_back_from_queue(self):
        app=self.app();self.press(app,'Right');self.press(app,'Up');self.press(app,'Right')
        app.browse_queue.assert_called_once_with(1)
        app.navigate_search.assert_called_once_with(-1)
    def test_active_key_repeats_still_move(self):
        app=self.app()
        for _ in range(4):self.press(app,'Right')
        self.assertEqual(app.browse_queue.call_count,4)
    def test_other_input_and_ctrl_keep_native_behavior(self):
        app=self.app();widget=Mock();widget.winfo_toplevel.return_value=app;widget.winfo_class.return_value='TSpinbox'
        self.assertIsNone(PlaybackApp.arrow_press(app,NS(widget=widget,keysym='Left',state=0)))
        self.assertIsNone(PlaybackApp.arrow_press(app,NS(widget=app.search_entry,keysym='Left',state=4)))
        app.browse_queue.assert_not_called()
    def test_losing_focus_clears_held_keys(self):
        app=self.app();self.press(app,'Up');self.press(app,'Right');app.focus_get=Mock(return_value=None)
        PlaybackApp.reset_arrows_if_unfocused(app)
        self.assertEqual(app._arrow_down,set());self.assertEqual(app._arrow_blocked,set())
        self.press(app,'Up');self.assertEqual(app.navigate_search.call_count,2)
    def test_enter_cancels_old_before_selected_queue_play(self):
        order=[]
        app=NS(_queue_position=lambda:2,play_queue_now=lambda i:order.append(('play',i)))
        self.assertEqual(PlaybackApp.play_browsed_queue(app),'break')
        self.assertEqual(order,[('play',2)])
    def test_enter_without_selection_keeps_current_song(self):
        app=NS(_queue_position=lambda:None,cancel_current_song=Mock(),next_song=Mock())
        PlaybackApp.play_browsed_queue(app);app.cancel_current_song.assert_not_called();app.next_song.assert_not_called()
    def test_queue_enter_priority_over_search(self):
        app=NS(queue_browser_visible=True,search_visible=True,play_browsed_queue=Mock(return_value='break'),confirm_search=Mock())
        PlaybackApp.input_enter(app);app.play_browsed_queue.assert_called_once();app.confirm_search.assert_not_called()
    def test_f10_queue_uses_same_cancel_then_play_order(self):
        order=[];app=NS(queue_index=lambda:3,play_queue_now=lambda i:order.append(i))
        PlaybackApp.play_queue_selected(app);self.assertEqual(order,[3])
    def test_enter_autorepeat_does_not_skip_multiple_queue_items(self):
        app=NS(play_queue_selected=Mock())
        for _ in range(5):PlaybackApp.queue_table_enter(app)
        app.play_queue_selected.assert_called_once()
