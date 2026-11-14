import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from karaoke.keyboard_input import control_or_alt, editing_modifier
from karaoke.performer import PlaybackApp

class KeyboardInputTests(unittest.TestCase):
    def test_windows_lock_and_extended_flags_are_not_modifiers(self):
        for state in (0,8,2,32,8|2|32,0x40000|8):
            self.assertFalse(control_or_alt(state,'win32'))
            self.assertFalse(editing_modifier(state,'win32'))
    def test_windows_real_alt_control_and_shift_are_preserved(self):
        for state in (4,4|8,0x20000,0x60008):
            self.assertTrue(control_or_alt(state,'win32'))
        self.assertTrue(editing_modifier(9,'win32'))
    def test_x11_alt_remains_mod1(self):
        self.assertTrue(control_or_alt(8,'linux'))
        self.assertFalse(control_or_alt(16,'linux'))
    def app(self):
        app=NS(search_entry=Mock(),stage=None,hide_search=Mock(),browse_queue=Mock(return_value='break'),
            navigate_search=Mock(return_value='break'))
        app.search_entry.winfo_toplevel.return_value=app
        app.search_entry.winfo_class.return_value='TEntry'
        return app
    def test_each_arrow_works_with_windows_numlock_on(self):
        with patch('karaoke.keyboard_input.sys.platform','win32'):
            for key in ('Up','Down','Left','Right'):
                app=self.app()
                self.assertEqual(PlaybackApp.arrow_press(app,NS(widget=app.search_entry,keysym=key,state=8)),'break')
                (app.navigate_search if key in ('Up','Down') else app.browse_queue).assert_called_once_with(-1 if key in ('Up','Left') else 1)
    def test_numlock_held_direction_switch_and_release(self):
        app=self.app()
        with patch('karaoke.keyboard_input.sys.platform','win32'):
            def press(key):return PlaybackApp.arrow_press(app,NS(widget=app.search_entry,keysym=key,state=8))
            press('Down');press('Right');press('Down')
            app.navigate_search.assert_called_once_with(1)
            app.browse_queue.assert_called_once_with(1)
            PlaybackApp.arrow_release(app,NS(keysym='Down'));press('Down')
            self.assertEqual(app.navigate_search.call_count,2)
    def test_insert_delete_with_numlock_reaches_song_context(self):
        app=self.app();app.search_visible=True;app.songs=Mock();app.search_pending=True;app.status_var=Mock()
        with patch('karaoke.keyboard_input.sys.platform','win32'):
            self.assertEqual(PlaybackApp.change_key_shortcut(app,NS(widget=app.search_entry,state=8),1),'break')
        app.status_var.set.assert_called_once()
    def test_numlock_does_not_block_instant_search(self):
        app=self.app();widget=Mock();widget.winfo_toplevel.return_value=app;widget.winfo_class.return_value='Canvas'
        app.search_visible=False;app.search_popup=Mock()
        with patch('karaoke.keyboard_input.sys.platform','win32'):
            self.assertEqual(PlaybackApp.instant_search(app,NS(widget=widget,state=8,char='ก')),'break')
        app.search_popup.assert_called_once_with('ก')
