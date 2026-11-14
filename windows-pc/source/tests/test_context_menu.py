"""Exercise menu routing and enabled states without a Windows display server."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from karaoke.context_menu import populate_context_menu
from karaoke.stage_layout import overlay_layout
from karaoke.performer import PlaybackApp

class Var:
    def __init__(self): self.value = False
    def get(self): return self.value
    def set(self, value): self.value = value

class Menu:
    def __init__(self, parent=None, **kwargs):
        self.parent, self.children, self.entries = parent, [], []
        if parent: parent.children.append(self)
    def winfo_children(self): return list(self.children)
    def destroy(self):
        for child in list(self.children): child.destroy()
        if self.parent: self.parent.children.remove(self)
    def delete(self, *args): self.entries.clear()
    def add_cascade(self, **kwargs): self.entries.append(dict(type='cascade', **kwargs))
    def add_command(self, **kwargs): self.entries.append(dict(type='command', **kwargs))
    def add_checkbutton(self, **kwargs): self.entries.append(dict(type='check', **kwargs))
    def add_radiobutton(self, **kwargs): self.entries.append(dict(type='radio', **kwargs))
    def add_separator(self): self.entries.append(dict(type='separator'))
    def find(self, prefix): return next(e for e in self.entries if e.get('label','').startswith(prefix))

class ContextMenuTests(unittest.TestCase):
    def app(self):
        app = SimpleNamespace(engine=None, current_song=None, search_visible=False, search_pending=False,
            search_revision=2, search_result_revision=2, stage=None, stage_fullscreen=False,
            settings={}, song_queue=SimpleNamespace(items=[]), songs=Mock())
        app.songs.selection.return_value = ('20120',)
        methods = ('search_popup save_settings stage_settings schedule_search choose_background background_options clear_background '
            'insert_queue_window history_window media_audio_window soundfont_mapping_window stage_fx_window medley_window record_window equalizer_window audio_diagnostics_window remote_window choose_lyrics lyric_editor show_controls backup_data restore_data help capabilities connect_catalog '
            'manage_songs add_folder add_files rebuild_library show_import_report song_details edit_song favorite_selected current_song_details choose_midi_output open_mixer '
            'open_midi_keyboard audio_settings play_pause next_song cancel_current_song stop apply_melody mark_loop_start mark_loop_end clear_loop '
            'show_queue browse_queue add_selected play_search_now import_queue export_queue set_stage_enabled '
            'set_stage_fullscreen choose_stage_monitor attributes pin_transport dismiss_overlays minimize_main about_program close_app').split()
        for name in methods:
            self.assertTrue(hasattr(PlaybackApp, name), 'Unimplemented menu command: '+name)
            setattr(app, name, Mock())
        for name in ('auto_var','playable_var','favorite_var','melody_var','stage_enabled_var',
                     'stage_fullscreen_var','stage_monitor_var','main_fullscreen_var','transport_pinned_var'):
            setattr(app, name, Var())
        app.defer_menu_command = lambda callback: callback()
        app.scanning = False
        app.cancel_scan = Mock()
        return app

    def test_category_order_and_action_routing(self):
        app, menu = self.app(), Menu()
        populate_context_menu(app, menu, Menu, [(0,0,1920,1080)])
        labels = [e['label'] for e in menu.entries if e['type']!='separator']
        self.assertFalse(any(e.get('label','').startswith('ค้นหาเพลง') for e in menu.find('ตัวเลือก')['menu'].entries))
        self.assertEqual(labels[:4], ['ตัวเลือก','พื้นหลัง','เครื่องมือ','จัดการข้อมูลเพลง'])
        self.assertEqual(labels[-2:], ['รายละเอียดโปรแกรม…','ออกจากโปรแกรม'])
        self.assertEqual(len(menu.children),6)
        self.assertLessEqual(len(menu.entries),18)
        menu.find('ซาวด์ฟอนท์')['command']()
        app.audio_settings.assert_called_once()
        self.assertEqual(menu.find('มิกเซอร์')['accelerator'],'F9')

    def test_stale_search_and_idle_commands_are_disabled(self):
        app, menu = self.app(), Menu()
        for visible,pending,revision in [(False,False,2),(True,True,2),(True,False,1)]:
            app.search_visible,app.search_pending,app.search_result_revision=visible,pending,revision
            populate_context_menu(app, menu, Menu, [])
            self.assertEqual(menu.find('จัดการข้อมูลเพลง')['state'],'normal')
            self.assertEqual(menu.find('ตัวควบคุม')['menu'].find('ยกเลิกเพลง')['state'],'disabled')
        app.search_visible,app.search_pending,app.search_result_revision=True,False,2
        populate_context_menu(app, menu, Menu, [])
        menu.find('จัดการข้อมูลเพลง')['command']()
        app.manage_songs.assert_called_once()

    def test_queue_and_transport_routes(self):
        app,menu=self.app(),Menu()
        app.engine=SimpleNamespace(playing=True)
        app.song_queue.items=[object()]
        populate_context_menu(app,menu,Menu,[])
        playback=menu.find('ตัวควบคุม')['menu']
        self.assertEqual(playback.find('ยกเลิกเพลง')['state'],'normal')
        playback.find('เพลงถัดไป')['command']()
        app.next_song.assert_called_once()
        self.assertFalse(any(e.get('label','').startswith('รายการเพลง') for e in menu.entries))
        app.browse_queue.assert_not_called()

    def test_monitor_state_and_repeated_menu_cleanup(self):
        app,menu=self.app(),Menu()
        screens=[(0,0,1920,1080),(-1280,0,1280,720)]
        for _ in range(4): populate_context_menu(app,menu,Menu,screens)
        self.assertEqual(len(menu.children),6)
        display=menu.find('ระบบ 2')['menu']
        self.assertEqual(len([e for e in display.entries if e['type']=='radio']),2)
        self.assertEqual(display.find('จอร้องเต็ม')['state'],'disabled')
        app.stage=SimpleNamespace(winfo_exists=lambda:True)
        populate_context_menu(app,menu,Menu,screens)
        self.assertTrue(app.stage_enabled_var.get())
        self.assertEqual(menu.find('ระบบ 2')['menu'].find('จอร้องเต็ม')['state'],'normal')

    def test_overlay_leaves_room_for_lyrics_at_supported_sizes(self):
        for width,height in [(800,500),(1024,600),(1280,720),(1920,1080),(3840,2160)]:
            layout=overlay_layout(width,height)
            for kind in ('search','queue'):
                x,y,w,h=layout[kind]
                self.assertGreaterEqual(x,0); self.assertLessEqual(x+w,width)
                self.assertGreaterEqual(y,100)
                self.assertGreaterEqual(height-(y+h+12)-24,100)
            self.assertLess(layout['query_width'],width*.5)

if __name__=='__main__': unittest.main()
