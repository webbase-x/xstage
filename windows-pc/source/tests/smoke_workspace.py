"""Exercise the real Tk search keys and context-menu actions on Windows."""
import json
import shutil
import sys
import tempfile
import time
import base64
import traceback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from karaoke.performer import PlaybackApp
from karaoke.library import QueueItem
from karaoke import DISPLAY_NAME


def run():
    result = {'ok': False, 'errors': [], 'checks': []}
    with tempfile.TemporaryDirectory() as temporary:
        home = Path(__file__).resolve().parents[1]
        app = PlaybackApp(home, Path(temporary)/'Data', auto_catalog=False)
        app.show_error = lambda error: result['errors'].append(str(error))
        app.report_callback_exception = lambda kind, value, trace: result['errors'].append(str(value))
        app.volume_var.set(1)
        source = next((home/'samples').glob('*.mid'))
        test_ids = []
        for index in range(3):
            file = Path(temporary)/f'workspace-{index}.mid'
            shutil.copy2(source, file)
            song_id = app.library.add_files([file])[0]
            app.library.edit(song_id, str(index), f'ทดสอบจอ {index}', 'ทดสอบ')
            test_ids.append(song_id)
        for name in ('A013677 - 02รักน้องพรจดหมายผิดซอง - สดใส.mid', '20120 - รักน้องพร - บาซู.mid'):
            file = Path(temporary)/name
            shutil.copy2(source, file)
            app.library.add_files([file])

        def failed(error):
            result['errors'].append(traceback.format_exc() if sys.exc_info()[0] else str(error))
            app.close_app()

        def wait_results(then, deadline=None):
            deadline = deadline or time.monotonic()+8
            if time.monotonic() > deadline:
                return failed('Search result timed out')
            if app.search_pending:
                app.after(30, lambda: wait_results(then, deadline))
                return
            try:
                then()
            except Exception as error:
                failed(error)

        def begin():
            try:
                app.update_idletasks()
                assert bool(app.attributes('-fullscreen')) and app.main_fullscreen_var.get(), 'Startup is not fullscreen'
                assert app.title() == DISPLAY_NAME and app.preview.state[0] == ''
                assert not app.cget('menu'), 'Main window still has a menu bar'
                assert not app.search_visible and not app.search_overlay.winfo_manager()
                assert app.queue_window.state() == app.control_window.state() == 'withdrawn'
                assert app.preview.winfo_height() >= app.surface.winfo_height()*.95
                result['checks'].append('Startup is a full playback surface; search, queue and controls are hidden')
                result['checks'].append('Starts fullscreen without user input; native text receiver stays ready')
                # Exercise Tk's native Entry insertion, not the KeyPress handler.
                # The restricted desktop has no alphabetic keysym mapping.
                assert app.focus_get() is app.search_entry
                assert app.search_entry.winfo_ismapped(), 'Idle text receiver is unmapped'
                app.tk.call('tk::EntryInsert', app.search_entry, 'ร')
                assert app.search_visible and app.search_var.get() == 'ร', 'First Thai character lost or duplicated'
                assert app.search_overlay.winfo_manager() == 'place', 'Search did not appear synchronously with the first character'
                assert app.focus_get() is app.search_entry and app.search_entry.winfo_viewable(), 'Visible search input lost focus after the first character'
                result['checks'].append('Native Entry insertion opens search from startup without F3 or a search click')
                app.search_entry.delete(0, 'end')
                app.search_entry.insert(0, 'รักน้องพร')
                app.search_entry.event_generate('<Return>')
                assert not app.song_queue.items, 'Enter queued a stale result during debounce'
                wait_results(check_ranked_startup)
            except Exception as error:
                failed(error)

        def check_ranked_startup():
            rows = app.songs.get_children()
            assert rows and app.songs.selection() == (rows[0],)
            assert app.songs.item(rows[0], 'values')[0] == '20120', 'Wrong first result for exact Thai title'
            assert app.search_selected_title.get().startswith('20120')
            app.search_entry.event_generate('<Return>')
            assert app.current_song['code'] == '20120' and not app.song_queue.items
            assert app.settings['search_preload'][0] == 'รักน้องพร'
            app.cancel_current_song()
            result['checks'].append('Startup accepts typing without focus clicks; exact-title 20120 is selected and played; successful query saved for preload')
            app.tk.call('tk::EntryInsert', app.search_entry, 'ทดสอบจอ')
            wait_results(select_result)

        def select_result():
            rows = app.songs.get_children()
            assert len(rows) == 3, f'Thai query returned {len(rows)} results'
            assert app.songs.selection() == (rows[0],)
            app.search_entry.event_generate('<Down>')
            assert app.songs.selection() == (rows[1],), 'Down did not advance selection'
            app.search_entry.event_generate('<Up>')
            assert app.songs.selection() == (rows[0],), 'Up did not restore selection'
            app.search_entry.event_generate('<Down>')
            selected_id = int(rows[1])
            assert not app.song_queue.items
            app.search_entry.event_generate('<Return>')
            assert app.current_song['id'] == selected_id and app.engine.playing
            assert not app.song_queue.items and not app.search_visible
            result['checks'].append('Empty queue: Enter on a search result plays immediately without creating a queued duplicate')
            old_engine = app.engine
            for state in ('playing', 'paused', 'stopped'):
                if state == 'paused':
                    app.engine.pause()
                elif state == 'stopped':
                    app.stop()
                app.search_popup()
                assert 'เพิ่มเข้าคิว' in app.search_action_var.get()
                position = app.engine.position
                app.search_entry.event_generate('<Return>')
                assert app.engine is old_engine, 'Enter replaced the current song with an empty waiting queue'
                assert len(app.song_queue.items) == 1 and app.song_queue.items[0].song_id == selected_id
                if state == 'playing':
                    assert app.engine.playing and app.engine.position >= position
                else:
                    assert not app.engine.playing and abs(app.engine.position-position) < .02
                app.song_queue.pop(0)
                app.refresh_queue()
            result['checks'].append('Enter with empty waiting queue preserves playing/paused/stopped song and queues selected song')
            app.search_entry.event_generate('<F7>')
            assert app.engine is None and app.current_song is None and app.current_item is None
            assert not old_engine.playing and not app.lyrics.lines and app.preview.state[0] == ''
            assert not app.song_queue.items
            app.song_queue.add(QueueItem(int(rows[0])))
            app.refresh_queue()
            assert app.start_song(QueueItem(int(rows[0])))
            engine = app.engine
            app.search_popup()
            app.search_entry.event_generate('<Return>')
            assert len(app.song_queue.items) == 2 and app.song_queue.items[-1].song_id == selected_id
            assert not app.search_visible and not app.search_overlay.winfo_manager()
            assert app.engine is engine and app.engine.playing, 'Queueing interrupted playback'
            app.song_queue.pop(0)
            app.refresh_queue()
            result['checks'].append('Thai search; Up/Down; Enter queues selected result once without interrupting playback')
            waiting = list(app.song_queue.items)
            app.cancel_current_song()
            assert app.engine is not None and app.current_item is waiting[0]
            assert app.song_queue.items == waiting[1:]
            result['checks'].append('F7 cancel advances to the next queued song; remaining order is preserved')
            assert app.start_song(QueueItem(int(rows[0])))
            app.search_popup()
            app.search_entry.icursor(2)
            app.search_entry.event_generate('<Left>')
            assert not app.queue_browser_visible and app.search_entry.index('insert') == 1, 'Left arrow hijacked text editing'
            app.search_entry.event_generate('<Control-Return>')
            assert app.current_song['id'] == selected_id and len(app.song_queue.items) == 1
            assert not app.search_visible, 'Ctrl+Enter did not return to playback'
            app.search_popup()
            assert app.search_entry.selection_present(), 'F3 should select the previous query for replacement'
            app.hide_search()
            assert app.focus_get() is app.search_entry, 'Search input was not rearmed after closing'
            app.tk.call('tk::EntryInsert', app.search_entry, 'b')
            assert app.search_visible and app.search_var.get() == 'b', 'New search reused previous text'
            assert not app.search_entry.selection_present(), 'Previous selection would replace the first typed character'
            app.tk.call('tk::EntryInsert', app.search_entry, 'e')
            assert app.search_var.get() == 'be', 'Second typed character replaced the first'
            app.search_entry.event_generate('<Escape>')
            assert not app.search_visible
            app.tk.call('tk::EntryInsert', app.search_entry, 'เพลงไทย')
            assert app.search_visible and app.search_var.get() == 'เพลงไทย', 'Pasted/native committed text failed to open search'
            app.hide_search()
            app.song_queue.add(QueueItem(test_ids[0]))
            app.refresh_queue()
            app.browse_queue(1)
            assert app.queue_browser_visible
            app.tk.call('tk::EntryInsert', app.search_entry, 'ก')
            app.tk.call('tk::EntryInsert', app.search_entry, 'า')
            assert app.search_visible and not app.queue_browser_visible and app.search_var.get() == 'กา'
            app.song_queue.pop(len(app.song_queue.items)-1)
            app.refresh_queue()
            app.hide_search()
            result['checks'].append('Typing rearms after Escape; native text/paste opens search; typing from queue browser preserves both first characters')
            app.search_popup('NO_MATCH_749193')
            wait_results(no_match)

        def no_match():
            assert not app.songs.get_children()
            app.search_entry.event_generate('<Return>')
            assert len(app.song_queue.items) == 1 and app.search_visible
            app.search_entry.event_generate('<Escape>')
            result['checks'].append('Esc returns to playback; a new query replaces old text; no-match Enter adds nothing')
            app.song_queue.add(QueueItem(test_ids[0], singer='ทดสอบคิวกลาง', key=2, speed=110))
            app.song_queue.add(QueueItem(test_ids[2], singer='ทดสอบเล่นทันที', key=-1, speed=95))
            app.refresh_queue()
            app.preview.focus_set()
            app.update()
            engine = app.engine
            app.preview.event_generate('<Right>')
            assert app.queue_browser_visible and app._queue_position() == 0
            app.preview.event_generate('<Right>')
            assert app._queue_position() == 1
            app.preview.event_generate('<Left>')
            assert app._queue_position() == 0
            app.preview.event_generate('<Left>')
            assert app._queue_position() == 2, 'Left did not wrap to the last queued song'
            assert app.engine is engine, 'Browsing queue changed playback before confirmation'
            item = app.song_queue.items[2]
            app.preview.event_generate('<Return>')
            assert app.current_item is item and app.current_song['id'] == test_ids[2]
            assert app.engine.key == -1 and app.engine.speed == .95
            assert len(app.song_queue.items) == 2 and not app.queue_browser_visible
            mouse_item = app.song_queue.items[0]
            app.browse_queue(1)
            app.browse_queue(1)
            app.update_idletasks()
            card = app.queue_cards[0][1]
            card.event_generate('<ButtonPress-1>', x=15, y=15, time=5000)
            card.event_generate('<ButtonRelease-1>', x=15, y=15, time=5020)
            assert app._queue_position() == 0, 'First mouse click did not select neighboring queue card'
            card.event_generate('<ButtonPress-1>', x=15, y=15, time=5100)
            card.event_generate('<ButtonRelease-1>', x=15, y=15, time=5120)
            assert app.current_item is mouse_item and len(app.song_queue.items) == 1, f'Double-click: current={app.current_item}, expected={mouse_item}, queue={len(app.song_queue.items)}, selected={app._queue_position()}'
            result['checks'].append('Double-click on neighboring queue card plays the original selected song after recentering')
            app.preview.event_generate('<Right>')
            app.song_queue.pop(0)
            app.refresh_queue()
            assert not app.queue_browser_visible, 'Removed queue selection remained playable'
            result['checks'].append('Left/Right browse and wrap; Enter plays exact selected queue item with key/speed; text cursor and queue mutations stay safe')
            app.show_transport()
            app.update_idletasks()
            assert app.transport.winfo_manager() == 'place'
            app.hide_transport(force=True)
            assert not app.transport.winfo_manager()
            assert app.preview.telemetry.get('bpm'), 'Live BPM missing'
            sample = 'ปี่ กุ้ง น้ำ ผู้หญิงขึ้นเวที'
            app.preview.show_frame(sample, 'น้องปุ้ยร้องเพลงให้เพื่อน ๆ ฟัง',
                'ปี่ ', 'ทดสอบภาษาไทย', 'กุ้ง', .65, app.settings)
            first_box, next_box = app.preview._line_boxes
            assert first_box[3]+12 < next_box[1], 'Thai lyric rows overlap'
            assert 0 <= first_box[1] < first_box[3] < app.preview.winfo_height()
            assert next_box[3] < app.preview.winfo_height(), 'Lower Thai marks are clipped'
            result['checks'].append('Native Thai stacked marks render with separate lyric rows and complete wipe bounds')
            if '--render' in sys.argv:
                png = app.preview.tk.call(str(app.preview._images[0]), 'data', '-format', 'png')
                result['render_png_base64'] = png if isinstance(png, str) else base64.b64encode(png).decode('ascii')
            result['checks'].append('Compact transport shows/hides; HUD reports actual MIDI tempo and musical position')
            app.toggle_main_fullscreen()
            app.update_idletasks()
            assert not bool(app.attributes('-fullscreen'))
            app.toggle_main_fullscreen()
            app.update_idletasks()
            assert bool(app.attributes('-fullscreen'))
            result['checks'].append('F11 fullscreen toggle works after fullscreen startup')
            # Prevent posting a native modal menu; invoke the real generated commands.
            screens = [(0, 0, 1280, 720), (1280, 0, 1024, 768)]
            with patch('karaoke.performer.monitors', return_value=screens), \
                 patch.object(app.context_menu, 'tk_popup', return_value=None):
                app.show_context_menu(SimpleNamespace(num=3, x_root=100, y_root=100))
                menu = app.context_menu
                labels = [menu.entrycget(i, 'label') for i in range(menu.index('end')+1) if menu.type(i) != 'separator']
                assert 'ระบบ 2 หน้าจอ' in labels and 'เครื่องมือ' in labels
                index = next(i for i in range(menu.index('end')+1) if menu.type(i)=='cascade' and menu.entrycget(i,'label')=='ระบบ 2 หน้าจอ')
                displays = app.nametowidget(menu.entrycget(index, 'menu'))
                displays.invoke(0)
                assert app.stage and app.stage_canvas.winfo_exists()
                app.update_idletasks()
                assert app.stage.winfo_x() == 1280 and app.stage.winfo_width() == 1024
                assert app.stage_canvas.bind('<Button-3>'), 'Singer window has no context menu'
                from karaoke.branding import asset
                retained = app.choose_background()
                assert retained == asset('xstage-background.jpg') and retained.is_file()
                assert app.preview.preferences['background_mode'] == app.stage_canvas.preferences['background_mode'] == 'stage'
                persisted = json.loads(app.settings_path.read_text(encoding='utf-8'))
                assert persisted['background_mode'] == 'stage'
                try:
                    app.set_background(Path(temporary)/'custom.png')
                    raise AssertionError('Custom background was accepted')
                except ValueError:
                    pass
                app.clear_background()
                assert app.preview.preferences['background_mode'] == 'none'
                result['checks'].append('Only bundled background or no picture on both screens; custom paths rejected')
                app.show_context_menu(SimpleNamespace(num=3, x_root=100, y_root=100))
                index = next(i for i in range(menu.index('end')+1) if menu.type(i)=='cascade' and menu.entrycget(i,'label')=='ระบบ 2 หน้าจอ')
                displays = app.nametowidget(menu.entrycget(index, 'menu'))
                displays.invoke(1)
                assert app.stage_fullscreen and bool(app.stage.attributes('-fullscreen'))
                app.exit_stage_fullscreen()
                displays.invoke(2)  # first monitor radio command
                app.update_idletasks()
                assert app.settings['stage_monitor'] == 0 and app.stage.winfo_x() == 0
                app.close_stage()
                assert app.stage is None and not app.stage_enabled_var.get()
            # Rebuild repeatedly: old submenus must not accumulate.
            with patch.object(app.context_menu, 'tk_popup', return_value=None):
                for _ in range(3):
                    app.show_context_menu(SimpleNamespace(num=3, x_root=100, y_root=100))
                assert len(app.context_menu.winfo_children()) == 8
            app.show_queue()
            app.show_controls()
            app.update_idletasks()
            assert app.queue_window.state() != 'withdrawn' and app.control_window.state() != 'withdrawn'
            result['checks'].append('Right-click actions open queue/controls and open, position, fullscreen, move and close singer output')
            result['checks'].append('Dual-monitor coordinates tested with simulated monitor inventory; physical two-display output needs onsite check')
            assert not result['errors'], result['errors']
            result['ok'] = True
            app.close_app()

        app.after(150, begin)
        app.mainloop()
    return result


if __name__ == '__main__':
    result = run()
    print(json.dumps(result, ensure_ascii=True, indent=2))
    raise SystemExit(0 if result['ok'] else 1)
