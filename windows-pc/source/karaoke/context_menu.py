"""Classic category order, wired only to implemented X-Stage commands."""
from .playback import MidiPlayer


def populate_context_menu(app, menu, factory, screens):
    for child in menu.winfo_children():
        child.destroy()
    menu.delete(0, 'end')
    selected = bool(app.search_visible and not app.search_pending and
                    app.search_result_revision == app.search_revision and app.songs.selection())
    waiting = bool(app.song_queue.items)
    loaded = app.engine is not None
    midi = isinstance(app.engine, MidiPlayer)
    def submenu(parent, label):
        child = factory(parent, tearoff=False)
        parent.add_cascade(label=label, menu=child)
        return child
    def command(parent, label, callback, key='', enabled=True):
        parent.add_command(label=label, command=lambda: app.defer_menu_command(callback), accelerator=key,
                           state='normal' if enabled else 'disabled')

    songs = submenu(menu, '1. เพลงและคิว')
    command(songs, 'จัดการข้อมูลเพลง…', app.manage_songs, 'F2')
    command(songs, 'แทรกเพลงเข้าคิว…', app.insert_queue_window)
    command(songs, 'ประวัติการเล่น…', app.history_window)
    songs.add_checkbutton(label='เฉพาะรูปแบบเพลงที่รองรับ', variable=app.playable_var, command=app.schedule_search)
    songs.add_checkbutton(label='เฉพาะเพลงโปรด', variable=app.favorite_var, command=app.schedule_search)

    playback = submenu(menu, '2. ควบคุมการเล่น')
    command(playback, 'เล่น / พัก', app.play_pause, 'F5', enabled=loaded or waiting or selected)
    command(playback, 'เพลงถัดไป', app.next_song, 'F6', enabled=waiting)
    command(playback, 'ยกเลิกเพลงปัจจุบัน', app.cancel_current_song, 'F7', enabled=loaded)
    command(playback, 'หยุดเพลง', app.stop, 'F8', enabled=loaded)
    playback.add_separator()
    command(playback, 'คีย์ / ความเร็ว / ระดับเสียง…', app.show_controls)
    playback.add_checkbutton(label='ปิดไกด์เมโลดี้ MIDI Ch4', variable=app.melody_var,
                             command=app.apply_melody, state='normal' if midi else 'disabled')
    playback.add_separator()
    command(playback, 'ตั้งจุดเริ่มวน A', app.mark_loop_start, enabled=midi)
    command(playback, 'ตั้งจุดจบ B / เริ่มวน', app.mark_loop_end, enabled=midi)
    command(playback, 'ยกเลิกวน A–B', app.clear_loop, enabled=midi)

    sound = submenu(menu, '3. ระบบเสียงและมิกเซอร์')
    command(sound, 'มิกเซอร์ MIDI / ชิ้นกลอง…', app.open_mixer, 'F9')
    command(sound, 'EQ X-Stage…', app.equalizer_window)
    command(sound, 'ช่องเสียงร้อง / แทร็กเสียง…', app.media_audio_window, enabled=loaded)
    midi_menu = submenu(menu, '4. MIDI และ SoundFont')
    command(midi_menu, 'เลือกมิดิขาออก…', app.choose_midi_output)
    command(midi_menu, 'ซาวด์ฟอนท์…', app.audio_settings)
    command(midi_menu, 'SoundFont แยกเครื่องดนตรี…', app.soundfont_mapping_window)
    command(midi_menu, 'ปรับโทนเครื่องดนตรี / กลอง (SoundFont)…', app.instrument_tone_window)
    command(midi_menu, 'EQ 31 ย่าน / ช่อง MIDI (SoundFont)…', app.instrument_channel_eq_window)
    command(midi_menu, 'คีย์บอร์ด MIDI…', app.open_midi_keyboard, 'F4')
    lyrics = submenu(menu, '5. เนื้อร้อง ภาพ และจอแสดงผล')
    command(lyrics, 'ตัวอักษร / สีเนื้อร้อง…', app.stage_settings)
    command(lyrics, 'ใช้ภาพเวที X-STAGE', app.choose_background)
    command(lyrics, 'ไม่มีรูปพื้นหลัง', app.clear_background)
    command(lyrics, 'เลือกไฟล์เนื้อร้อง LRC…', app.choose_lyrics, enabled=bool(app.current_song))
    command(lyrics, 'แก้ไขเนื้อร้อง LRC…', app.lyric_editor)
    command(lyrics, 'ชดเชยเวลาเนื้อร้อง…', app.show_controls, enabled=loaded)
    display = submenu(lyrics, 'ระบบ 2 หน้าจอ')
    stage_exists = bool(app.stage and app.stage.winfo_exists())
    app.stage_enabled_var.set(stage_exists)
    app.stage_fullscreen_var.set(app.stage_fullscreen)
    display.add_checkbutton(label='เปิดจอร้องแยก', variable=app.stage_enabled_var,
                            command=lambda: app.set_stage_enabled(app.stage_enabled_var.get()))
    display.add_checkbutton(label='จอร้องเต็มหน้าจอ', variable=app.stage_fullscreen_var,
                            command=app.set_stage_fullscreen, state='normal' if stage_exists else 'disabled')
    if screens:
        app.stage_monitor_var.set(max(0, min(int(app.settings.get('stage_monitor', 1)), len(screens)-1)))
        for index, (_, _, width, height) in enumerate(screens):
            display.add_radiobutton(label=f'จอ {index+1} — {width}×{height}', value=index,
                                    variable=app.stage_monitor_var, command=app.choose_stage_monitor)
    else:
        command(display, 'ยังไม่พบข้อมูลจอภาพ', lambda: None, enabled=False)

    windows = submenu(lyrics, 'หน้าต่าง')
    windows.add_checkbutton(label='เต็มหน้าจอหลัก', variable=app.main_fullscreen_var,
                            command=lambda: app.attributes('-fullscreen', app.main_fullscreen_var.get()), accelerator='F11')
    windows.add_checkbutton(label='แสดงแถบควบคุมตลอด', variable=app.transport_pinned_var, command=app.pin_transport)
    command(windows, 'ปิดแผงค้นหา / คิวบนจอ', app.dismiss_overlays, 'Esc')
    command(windows, 'ยุบหน้าต่าง', app.minimize_main)
    performance = submenu(menu, '6. เครื่องมือแสดงสด')
    command(performance, 'เสียงเอฟเฟกต์หน้าเวที…', app.stage_fx_window)
    command(performance, 'บันทึกเสียง…', app.record_window)
    command(performance, 'รีโมตมือถือ…', app.remote_window)
    if hasattr(app, 'random_medley_window'):
        command(performance, 'เริ่มสุ่มเมดเลย์ต่อเนื่องตามประเภท', app.start_continuous_medley)
        command(performance, 'หยุดสุ่มเมดเลย์ต่อเนื่อง', app.stop_continuous_medley,
                enabled=app.continuous_medley.enabled)
        command(performance, 'สุ่มเมดเล่ย์…', app.random_medley_window)
        if hasattr(app, 'popular_medley_window'):
            command(performance, 'เมดเล่ย์เพลงฮิตจากประวัติ…', app.popular_medley_window)
        command(performance, 'ยกเลิกเพลงที่เหลือในชุดเมดเล่ย์', app.cancel_random_medley,
                enabled=any(getattr(item, 'medley_session', '') for item in app.song_queue.items))
    command(performance, 'เมดเล่ย์ / ต่อเพลง…', app.medley_window)
    tools = submenu(menu, '7. ตั้งค่าและจัดการระบบ')
    command(tools, 'ตรวจระบบเสียง…', app.audio_diagnostics_window)
    def repair_components():
        from .dependency_ui import open_window
        open_window(app)
    command(tools, 'ตรวจและซ่อมส่วนประกอบ…', repair_components)
    def support_report():
        from .support_ui import open_window
        open_window(app)
    command(tools, 'รายงานตรวจระบบ / ผลทดสอบ Windows…', support_report)
    def view_logs():
        from .log_viewer import open_window
        open_window(app)
    command(tools, 'บันทึกเหตุการณ์ / ข้อผิดพลาด (Log)…', view_logs)
    command(tools, 'กู้คืนข้อมูล…', app.restore_data)
    command(tools, 'วิธีใช้ / ปุ่มลัด', app.help)
    command(tools, 'ความสามารถที่รองรับ', app.capabilities)
    system_root = submenu(menu, '8. โปรแกรมและการออก')
    command(system_root, 'ตรวจสอบอัปเดต X-Stage…', lambda: app.check_program_update(True))
    command(system_root, 'รายละเอียดโปรแกรม…', app.about_program)
    command(system_root, 'ออกจากโปรแกรม', app.close_app, 'Alt+F4')
