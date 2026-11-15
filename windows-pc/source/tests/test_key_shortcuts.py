import unittest
import sys
from types import SimpleNamespace as NS
from unittest.mock import Mock
from karaoke.performer import PlaybackApp
from karaoke.playback import MidiPlayer

class Var:
    def __init__(self,value=0):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value

class KeyShortcutTests(unittest.TestCase):
    def app(self):
        app=NS(engine=Mock(spec=MidiPlayer),key_var=Var(),status_var=Var(),
            search_visible=False,search_entry=Mock(),stage=Mock(),paint_lyrics=Mock(),
            library=Mock(get=lambda i:{'id':i,'path':'song.mid','playable':True}))
        app.apply_key=lambda:app.engine.set_key(app.key_var.get())
        app.search_entry.winfo_toplevel.return_value=app
        app.search_entry.winfo_class.return_value='TEntry'
        return app
    def test_hidden_search_intercept_does_not_type_or_open_search(self):
        app=self.app();event=NS(widget=app.search_entry,state=0)
        self.assertEqual(PlaybackApp.change_key_shortcut(app,event,1),'break')
        app.engine.set_key.assert_called_once_with(1)
        self.assertEqual(PlaybackApp.change_key_shortcut(app,event,-1),'break')
        self.assertEqual(app.key_var.get(),0)
    def test_visible_search_and_editor_preserve_typing(self):
        app=self.app();app.search_visible=True;app.songs=Mock();app.search_pending=True
        self.assertEqual(PlaybackApp.change_key_shortcut(app,NS(widget=app.search_entry,state=0),-1),'break')
        for cls in ['TSpinbox','Text','TCombobox']:
            widget=Mock();widget.winfo_toplevel.return_value=app;widget.winfo_class.return_value=cls
            self.assertIsNone(PlaybackApp.change_key_shortcut(app,NS(widget=widget,state=0),1))
        app.engine.set_key.assert_not_called()
    def test_clamps_both_limits(self):
        app=self.app();event=NS(widget=app.search_entry,state=0)
        for value,step in [(12,1),(-12,-1)]:
            app.key_var.set(value);PlaybackApp.change_key_shortcut(app,event,step)
            self.assertEqual(app.key_var.get(),value)
    def test_stage_supported_but_dialogs_and_modifiers_ignored(self):
        app=self.app();widget=Mock();widget.winfo_class.return_value='Canvas';widget.winfo_toplevel.return_value=app.stage
        self.assertEqual(PlaybackApp.change_key_shortcut(app,NS(widget=widget,state=0),1),'break')
        app.engine.set_key.reset_mock()
        for state in [4, 0x20000 if sys.platform == 'win32' else 8]:
            self.assertIsNone(PlaybackApp.change_key_shortcut(app,NS(widget=widget,state=state),1))
        widget.winfo_toplevel.return_value=Mock()
        self.assertIsNone(PlaybackApp.change_key_shortcut(app,NS(widget=widget,state=0),1))
        app.engine.set_key.assert_not_called()
    def test_non_midi_does_not_change_key(self):
        app=self.app();app.engine=None
        self.assertEqual(PlaybackApp.change_key_shortcut(app,NS(widget=app.search_entry,state=0),1),'break')
        self.assertEqual(app.key_var.get(),0)
    def test_insert_delete_replace_previous_bindings(self):
        window=Mock();app=NS(change_key_shortcut=Mock(),alt_key_shortcut=Mock())
        PlaybackApp.bind_key_shortcuts(app,window)
        for call,step in zip(window.bind.call_args_list,[-1,1]):
            call.args[1]('event');app.change_key_shortcut.assert_called_with('event',step)
        self.assertEqual([c.args[0] for c in window.bind.call_args_list],['<KeyPress-Delete>','<KeyPress-Insert>','<Alt-KeyPress-Up>','<Alt-KeyPress-Down>'])
        for call,step in zip(window.bind.call_args_list[2:],[1,-1]):
            call.args[1]('event');app.alt_key_shortcut.assert_called_with('event',step)

    def test_search_key_changes_selected_song_only_and_follows_into_queue(self):
        app=self.app();app.search_visible=True;app.search_pending=False
        app.search_revision=app.search_result_revision=2
        app.songs=Mock();app.songs.selection.return_value=('17',)
        app.update_search_detail=Mock()
        event=NS(widget=app.search_entry,state=0)
        PlaybackApp.change_key_shortcut(app,event,1)
        PlaybackApp.change_key_shortcut(app,event,1)
        self.assertEqual(PlaybackApp.search_queue_item(app,17).key,2)
        self.assertEqual(PlaybackApp.search_queue_item(app,18).key,0)
        app.engine.set_key.assert_not_called()
        self.assertEqual(app.key_var.get(),0)

    def test_shift_insert_and_delete_keep_editing_behavior(self):
        app=self.app()
        self.assertIsNone(PlaybackApp.change_key_shortcut(app,NS(widget=app.search_entry,state=1),1))
        app.engine.set_key.assert_not_called()

    def test_alt_up_down_adjust_current_song_without_navigation(self):
        app=self.app()
        app.change_key_shortcut=lambda event,step: PlaybackApp.change_key_shortcut(app,event,step)
        app.navigate_search=Mock();app.browse_queue=Mock()
        for mask in (8, 0x20000):
            self.assertEqual(PlaybackApp.alt_key_shortcut(app,NS(widget=app.search_entry,state=mask),1),'break')
            self.assertEqual(app.key_var.get(),1)
            PlaybackApp.alt_key_shortcut(app,NS(widget=app.search_entry,state=mask),-1)
            self.assertEqual(app.key_var.get(),0)
        app.navigate_search.assert_not_called();app.browse_queue.assert_not_called()

    def test_alt_in_search_adjusts_selected_song_only(self):
        app=self.app();app.search_visible=True;app.search_pending=False
        app.search_revision=app.search_result_revision=1
        app.songs=Mock();app.songs.selection.return_value=('42',)
        app.update_search_detail=Mock()
        app.change_key_shortcut=lambda event,step: PlaybackApp.change_key_shortcut(app,event,step)
        PlaybackApp.alt_key_shortcut(app,NS(widget=app.search_entry,state=8),-1)
        self.assertEqual(PlaybackApp.search_queue_item(app,42).key,-1)
        app.engine.set_key.assert_not_called()

    def test_alt_preserves_editor_and_extra_modifiers(self):
        app=self.app();app.change_key_shortcut=lambda event,step: PlaybackApp.change_key_shortcut(app,event,step)
        editor=Mock();editor.winfo_toplevel.return_value=app;editor.winfo_class.return_value='Text'
        self.assertIsNone(PlaybackApp.alt_key_shortcut(app,NS(widget=editor,state=8),1))
        for mask in (9,12):
            self.assertIsNone(PlaybackApp.alt_key_shortcut(app,NS(widget=app.search_entry,state=mask),1))
        app.engine.set_key.assert_not_called()
