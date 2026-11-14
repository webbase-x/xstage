"""Independent classic operator workflow; source songs are linked read-only."""
from __future__ import annotations
import json
import logging
import os
import queue
import socket
from contextlib import closing
import sqlite3
import threading
import time
from .dialog_layout import DialogWindow, ActionBar
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox, colorchooser
from .ui import KaraokeApp, timestamp
from .stage import StageCanvas, lyric_progress, monitors
from .legacy import DEFAULT_LEGACY, import_catalog
from .library import QueueItem, write_json
from .playback import MidiPlayer, WinMidi
from . import DISPLAY_NAME


class ClassicApp(KaraokeApp):
    canvas_class = StageCanvas

    def __init__(self, home, data_dir=None, auto_catalog=True):
        self.remote = None
        from .remote_requests import RequestBook
        self.remote_requests = RequestBook()
        self.remote_invite = None
        self.snapshot_lock = threading.Lock()
        self.remote_state = {'title': '', 'queue': [], 'playing': False}
        self.search_revision = 0
        self.loop_mark = None
        self.recorder = None
        self.last_snapshot = 0
        super().__init__(home, data_dir)
        from . import __version__
        self.title(f'X-Stage Karaoke {__version__} — Classic Studio')
        self.minsize(1000, 650)
        self.geometry(f'{min(1440, self.winfo_screenwidth()-60)}x{min(900, self.winfo_screenheight()-90)}')
        if auto_catalog and self.settings.get('auto_catalog', False):
            self.after(600, self.auto_connect_catalog)

    def _setup_style(self):
        super()._setup_style()
        style = ttk.Style(self)
        style.configure('TFrame', background='#081d58')
        style.configure('TLabel', background='#081d58', foreground='white')
        style.configure('Muted.TLabel', foreground='#b9cbea')
        style.configure('TButton', background='#dce2ed', foreground='#14213b', padding=(8, 5))
        style.map('TButton', background=[('active', '#ffffff')])
        style.configure('Accent.TButton', background='#ffdf38', foreground='#172544', padding=(8, 5))
        style.map('Accent.TButton', background=[('active', '#fff4a5')])
        style.configure('TCheckbutton', background='#081d58', foreground='white')
        style.map('TCheckbutton', background=[('active', '#081d58')])
        style.configure('Treeview', background='#09255e', fieldbackground='#09255e', foreground='white', rowheight=28)
        style.map('Treeview', background=[('selected', '#ffdd43')], foreground=[('selected', '#101c37')])
        style.configure('Treeview.Heading', background='#dce3ed', foreground='#10234a', padding=5)

    def _build(self):
        menu = tk.Menu(self)
        self.config(menu=menu)
        songs = tk.Menu(menu, tearoff=False)
        menu.add_cascade(label='เพลง', menu=songs)
        songs.add_command(label='เชื่อมคลังเพลงรุ่นเก่า…', command=self.connect_catalog)
        songs.add_command(label='เพิ่มโฟลเดอร์เพลง…', command=self.add_folder)
        songs.add_command(label='เพิ่มไฟล์เพลง…', command=self.add_files)
        songs.add_separator()
        songs.add_command(label='ออกจากโปรแกรม', command=self.close_app)
        play = tk.Menu(menu, tearoff=False)
        menu.add_cascade(label='ควบคุมเพลง', menu=play)
        for label, command in [('เล่น / พัก  F5', self.play_pause), ('เพลงถัดไป  F6', self.next_song), ('หยุด  F8', self.stop),
                ('ค้นหาซ้อนจอ  F3', self.search_popup), ('มิกเซอร์ MIDI  F9', self.open_mixer),
                ('ตั้งจุดวน A', self.mark_loop_start), ('ตั้งจุดวน B / เปิดวน', self.mark_loop_end), ('ยกเลิกวน', self.clear_loop)]:
            play.add_command(label=label, command=command)
        tools = tk.Menu(menu, tearoff=False)
        menu.add_cascade(label='เครื่องมือ', menu=tools)
        tools.add_command(label='รีโมตมือถือผ่าน Wi-Fi…', command=self.remote_window)
        tools.add_command(label='บันทึกเสียงจากอุปกรณ์รับเสียง…', command=self.record_window)
        tools.add_command(label='แก้ไขเนื้อร้อง LRC…', command=self.lyric_editor)
        tools.add_command(label='เลือก SoundFont / ตั้งระบบเสียง…', command=self.audio_settings)
        tools.add_command(label='ตรวจไฟล์เพลงที่เลือก', command=self.song_details)
        settings = tk.Menu(menu, tearoff=False)
        menu.add_cascade(label='ตั้งค่า', menu=settings)
        settings.add_command(label='จอร้องเพลง สี และพื้นหลัง…', command=self.stage_settings)
        settings.add_command(label='นโยบายความเป็นส่วนตัวของ X-Stage Karaoke', command=self.open_privacy_policy)
        settings.add_command(label='ความสามารถและข้อจำกัดรุ่นนี้', command=self.capabilities)
        menu.add_command(label='วิธีใช้', command=self.help)
        outer = ttk.Frame(self, padding=10)
        outer.pack(fill='both', expand=True)
        bar = ttk.Frame(outer)
        bar.pack(fill='x', pady=(0, 8))
        ttk.Label(bar, text='X-Stage Karaoke', font=('Tahoma', 19, 'bold'), foreground='#ffdf38').pack(side='left', padx=(0, 14))
        ttk.Button(bar, text='เชื่อมคลังเดิม', command=self.connect_catalog, style='Accent.TButton').pack(side='left')
        ttk.Button(bar, text='เพิ่มเพลง', command=self.add_folder).pack(side='left', padx=5)
        ttk.Button(bar, text='ค้นหา F3', command=self.search_popup).pack(side='left')
        ttk.Button(bar, text='จอร้อง F11', command=self.toggle_stage).pack(side='right')
        ttk.Button(bar, text='รีโมต', command=self.remote_window).pack(side='right', padx=5)
        self.song_count = tk.StringVar()
        ttk.Label(bar, textvariable=self.song_count, style='Muted.TLabel').pack(side='right', padx=8)
        body = ttk.Panedwindow(outer, orient='horizontal')
        body.pack(fill='both', expand=True)
        left, right = ttk.Frame(body), ttk.Frame(body)
        body.add(left, weight=6)
        body.add(right, weight=5)
        search = ttk.Frame(left)
        search.pack(fill='x', padx=(0, 10), pady=(0, 7))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search, textvariable=self.search_var)
        self.search_entry.pack(fill='x', expand=True, side='left')
        self.search_var.trace_add('write', self.schedule_search)
        self.favorite_var = tk.BooleanVar(value=False)
        self.playable_var = tk.BooleanVar(value=True)
        filters = ttk.Frame(left)
        filters.pack(fill='x', pady=(0, 6))
        ttk.Checkbutton(filters, text='รูปแบบที่รองรับ', variable=self.playable_var, command=self.refresh_library).pack(side='left')
        ttk.Checkbutton(filters, text='เพลงโปรด', variable=self.favorite_var, command=self.refresh_library).pack(side='left', padx=7)
        ttk.Label(filters, text='ชื่อ • ศิลปิน • รหัส • เนื้อร้อง', style='Muted.TLabel').pack(side='left')
        table = ttk.Frame(left)
        table.pack(fill='both', expand=True, padx=(0, 10))
        self.songs = ttk.Treeview(table, columns=('code', 'title', 'artist', 'kind'), show='headings', selectmode='extended')
        for name, label, width in [('code', 'รหัส', 85), ('title', 'ชื่อเพลง', 230), ('artist', 'ศิลปิน', 145), ('kind', 'ชนิด', 65)]:
            self.songs.heading(name, text=label)
            self.songs.column(name, width=width, minwidth=45, stretch=name in ('title', 'artist'))
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.songs.yview)
        self.songs.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.songs.pack(fill='both', expand=True)
        self.songs.tag_configure('unsupported', foreground='#8c9ab6')
        self.songs.bind('<Double-1>', lambda _: self.add_selected())
        self.songs.bind('<Return>', lambda _: self.add_selected())
        actions = ttk.Frame(left)
        actions.pack(fill='x', pady=6)
        for text, command in [('+ เข้าคิว', self.add_selected), ('เล่นทันที', self.play_selected), ('โปรด ★', self.favorite_selected), ('ข้อมูล', self.song_details)]:
            ttk.Button(actions, text=text, command=command).pack(side='left', padx=(0, 5))
        self.now_var = tk.StringVar(value='พร้อมใช้งาน')
        ttk.Label(right, textvariable=self.now_var, font=('Tahoma', 12, 'bold'), wraplength=500).pack(anchor='w', pady=(0, 5))
        self.video_frame = tk.Frame(right, bg='black', height=185)
        self.video_frame.bind('<Configure>', lambda _: self.resize_video())
        self.preview = self.canvas_class(right, height=185)
        self.preview.pack(fill='x')
        self.lyric_controls = ttk.Frame(right)
        self.lyric_controls.pack(fill='x', pady=5)
        ttk.Button(self.lyric_controls, text='เนื้อร้อง LRC', command=self.choose_lyrics).pack(side='left')
        ttk.Label(self.lyric_controls, text='ชดเชย ms').pack(side='left', padx=5)
        self.offset_var = tk.IntVar(value=0)
        ttk.Spinbox(self.lyric_controls, from_=-10000, to=10000, increment=100, width=7, textvariable=self.offset_var, command=self.save_offset).pack(side='left')
        ttk.Button(self.lyric_controls, text='บันทึก', command=self.save_offset).pack(side='left', padx=4)
        qtitle = ttk.Frame(right)
        qtitle.pack(fill='x', pady=4)
        self.queue_title = tk.StringVar(value='คิวเพลง')
        ttk.Label(qtitle, textvariable=self.queue_title).pack(side='left')
        self.auto_var = tk.BooleanVar(value=bool(self.settings.get('auto_next', True)))
        ttk.Checkbutton(qtitle, text='เล่นต่ออัตโนมัติ', variable=self.auto_var).pack(side='right')
        self.queues = ttk.Treeview(right, columns=('number', 'title', 'singer', 'setting'), show='headings', height=4)
        for name, label, width in [('number', '#', 35), ('title', 'ชื่อเพลง', 230), ('singer', 'ผู้ร้อง', 100), ('setting', 'คีย์ / เร็ว', 95)]:
            self.queues.heading(name, text=label)
            self.queues.column(name, width=width, minwidth=30, stretch=name in ('title', 'singer'))
        self.queues.pack(fill='both', expand=True)
        self.queues.bind('<Double-1>', lambda _: self.edit_queue())
        qactions = ttk.Frame(right)
        qactions.pack(fill='x', pady=6)
        for text, command in [('▲', lambda: self.move_queue(-1)), ('▼', lambda: self.move_queue(1)), ('ลบ', self.remove_queue), ('แก้คิว', self.edit_queue), ('เล่นคิวนี้', self.play_queue_selected), ('นำเข้า', self.import_queue), ('ส่งออก', self.export_queue)]:
            ttk.Button(qactions, text=text, width=max(2, len(text)), command=command).pack(side='left', padx=2)
        progress = ttk.Frame(outer)
        progress.pack(fill='x', pady=(5, 0))
        self.time_var = tk.StringVar(value='00:00 / 00:00')
        ttk.Label(progress, textvariable=self.time_var, width=17).pack(side='left')
        self.seek_var = tk.DoubleVar(value=0)
        self.seek = ttk.Scale(progress, from_=0, to=1, variable=self.seek_var)
        self.seek.pack(side='left', fill='x', expand=True)
        self.seek.bind('<ButtonPress-1>', lambda _: setattr(self, 'dragging', True))
        self.seek.bind('<ButtonRelease-1>', self.seek_release)
        self.beat_var = tk.StringVar(value='ห้อง —  จังหวะ —')
        ttk.Label(progress, textvariable=self.beat_var, width=23).pack(side='right')
        controls = ttk.Frame(outer)
        controls.pack(fill='x', pady=6)
        self.play_button = ttk.Button(controls, text='▶ เล่น / พัก', style='Accent.TButton', command=self.play_pause)
        self.play_button.pack(side='left')
        for text, command in [('■ หยุด', self.stop), ('ถัดไป', self.next_song), ('มิกเซอร์ F9', self.open_mixer)]:
            ttk.Button(controls, text=text, command=command).pack(side='left', padx=4)
        ttk.Label(controls, text='คีย์').pack(side='left', padx=(8, 4))
        self.key_var = tk.IntVar(value=0)
        self.key_box = ttk.Spinbox(controls, from_=-12, to=12, width=4, textvariable=self.key_var, command=self.apply_key)
        self.key_box.pack(side='left')
        self.key_box.bind('<Return>', lambda _: self.apply_key())
        ttk.Label(controls, text='เร็ว %').pack(side='left', padx=5)
        self.speed_var = tk.IntVar(value=100)
        self.speed_box = ttk.Spinbox(controls, from_=50, to=150, increment=5, width=5, textvariable=self.speed_var, command=self.apply_speed)
        self.speed_box.pack(side='left')
        self.speed_box.bind('<Return>', lambda _: self.apply_speed())
        self.volume_var = tk.DoubleVar(value=float(self.settings.get('volume', 75)))
        ttk.Label(controls, text='ระดับเสียง').pack(side='left', padx=5)
        ttk.Scale(controls, from_=0, to=100, length=110, variable=self.volume_var, command=self.apply_volume).pack(side='left')
        self.melody_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text='ปิดไกด์ Ch4', variable=self.melody_var, command=self.apply_melody).pack(side='left', padx=7)
        self.status_var = tk.StringVar(value='F3 ค้นหา • Enter เข้าคิว • F5 เล่น/พัก • F6 ถัดไป • F8 หยุด • F11 จอร้อง')
        ttk.Label(outer, textvariable=self.status_var, style='Muted.TLabel', wraplength=1300).pack(anchor='w')

    def _bindings(self):
        super()._bindings()
        self.bind('<F3>', lambda _: self.search_popup())
        self.bind('<F9>', lambda _: self.open_mixer())
        self.bind('<Key>', self.instant_search, add='+')

    def instant_search(self, event):
        if event.widget.winfo_toplevel() is not self or event.state & 0x0c:
            return
        if event.widget.winfo_class() in ('Entry', 'TEntry', 'TSpinbox', 'Text', 'TCombobox'):
            return
        if event.char and event.char.isprintable() and not event.char.isspace():
            self.search_entry.focus_set()
            self.search_entry.insert('end', event.char)
            return 'break'

    def refresh_library(self):
        self.search_after = None
        self.search_revision += 1
        revision = self.search_revision
        query, favorite = self.search_var.get(), self.favorite_var.get()
        playable = self.playable_var.get()
        def work():
            try:
                songs = self.library.search(query, favorite, playable_only=playable)
                self.messages.put(('search_results', (revision, songs, self.library.count())))
            except Exception as error:
                self.messages.put(('search_error', str(error)))
        threading.Thread(target=work, daemon=True, name='song-search').start()

    def add_selected(self):
        added = 0
        for iid in self.songs.selection():
            song = self.library.get(int(iid))
            if song and song['playable']:
                self.song_queue.add(QueueItem(song['id']))
                added += 1
        self.refresh_queue()
        self.status_var.set(f'เพิ่มคิว {added} เพลง')
        return 'break'

    def start_song(self, item, quiet=False):
        song = self.library.get(item.song_id)
        if song and not song['playable']:
            self.report_load_error(f"เพลง {song['format']} ยังไม่มีตัวอ่านที่ผ่านการทดสอบในรุ่นนี้", quiet, kind='file')
            return False
        result = super().start_song(item, quiet=quiet)
        if result and isinstance(self.engine, MidiPlayer):
            preset = self.settings.get('midi_preset', [])
            if isinstance(preset, list):
                for channel, values in enumerate(preset[:16]):
                    if isinstance(values, dict):
                        self.engine.set_channel(channel, float(values.get('gain',1)), bool(values.get('mute',False)))
                        self.engine.set_pan(channel, int(values.get('pan',64)))
                        program = int(values.get('program',-1))
                        self.engine.set_program(channel, None if program<0 else program)
                        self.engine.set_solo(channel, bool(values.get('solo',False)))
            self.engine.enable_scheduler()
            if self.engine.lyric_warning:
                self.status_var.set('เล่น MIDI ได้ แต่เนื้อร้องยังไม่ผ่านการตรวจ: ' + self.engine.lyric_warning)
            warnings = getattr(self.lyrics, 'warnings', [])
            if warnings:
                self.status_var.set('แสดงเนื้อร้องได้บางช่วง: ' + warnings[0])
            self.write_lyric_diagnostics()
        return result

    def auto_connect_catalog(self):
        root = Path(self.settings.get('legacy_root', str(DEFAULT_LEGACY)))
        dbf = root / 'Data' / 'SONG.DBF'
        if dbf.is_file() and self.settings.get('catalog_stamp') != str(dbf.stat().st_mtime_ns):
            self.start_catalog(root)

    def connect_catalog(self):
        if self.scanning:
            return self.status_var.set('กำลังนำเข้าคลังเพลง กรุณารอ')
        root = filedialog.askdirectory(parent=self, mustexist=True, title='เลือกโฟลเดอร์โปรแกรมเก่าที่มี Data และ Songs', initialdir=str(DEFAULT_LEGACY))
        if root:
            from .import_ui import choose_copy,options
            copy_files=choose_copy(self)
            if copy_files is not None:self.start_catalog(Path(root),options(self,copy_files))

    def start_catalog(self, root, import_options=None):
        from .lister import build_list
        if import_options is None:
            from .import_ui import options
            import_options=options(self,False)
        def worker():
            result=build_list(self.library,[{'path':str(root),'type':'ทุกประเภท'}],
                              cancelled=self.cancel_scan,events=self.job_event,protected=self.index_protected_ids(),import_options=import_options)
            if not self.cancel_scan.is_set():self.messages.put(('catalog_location_saved',str(root)))
            return result
        self.start_index_job(worker)

    def tick(self):
        try:return ClassicApp._tick_once(self)
        except Exception as error:
            logging.exception('UI_TICK_FAILED')
            if not getattr(self,'closing',False):
                try:self.tick_after=self.after(25,self.tick)
                except Exception:logging.exception('UI_TICK_RESCHEDULE_FAILED')
            try:self.show_error(str(error))
            except Exception:logging.exception('UI_TICK_REPORT_FAILED')

    def _tick_once(self):
        if self.closing:
            return
        try:
            while True:
                kind, data = self.messages.get_nowait()
                from .import_ui import handle_message
                if handle_message(self,kind,data):continue
                if kind == 'search_ready':
                    self.on_search_ready(data)
                elif kind == 'search_results':
                    revision, songs, count = data
                    if revision != self.search_revision:
                        continue
                    self._search_rows = {str(song['id']): song for song in songs}
                    self.songs.delete(*self.songs.get_children())
                    for song in songs:
                        self.songs.insert('', 'end', iid=str(song['id']), values=(song['code'], ('★ ' if song['favorite'] else '') + song['title']+(' • ซ้ำ' if song.get('name_duplicate_count',0)>1 else ''), song['artist'], song['format'] or song['kind']), tags=() if song['playable'] else ('unsupported',))
                    self.song_count.set(f'{count:,} เพลง · แสดง {len(songs):,}')
                    self.search_results_ready()
                elif kind == 'search_error':
                    self.status_var.set(data)
                elif kind == 'catalog_location_saved':
                    from .lister import register_catalog_location
                    register_catalog_location(self.settings,data)
                    try:
                        from .legacy import catalog_location
                        self.settings['catalog_stamp']=str(catalog_location(Path(data))[0].stat().st_mtime_ns)
                    except (OSError,ValueError):
                        logging.warning('Catalog moved before settings could be updated')
                    self.save_settings()
                elif kind == 'catalog_progress':
                    self.status_var.set(f'เชื่อมดัชนีเดิมแล้ว {data:,} รายการ — เพลงต้นฉบับอยู่ที่เดิม')
                    if data % 10000 == 0:
                        self.refresh_library()
                elif kind == 'catalog_done':
                    self.scanning = False
                    root, (count, unsupported, invalid) = data
                    if not self.cancel_scan.is_set():
                        from .lister import register_catalog_location
                        register_catalog_location(self.settings,root)
                        from .legacy import catalog_location
                        self.settings['catalog_stamp'] = str(catalog_location(Path(root))[0].stat().st_mtime_ns)
                        self.save_settings()
                    self.refresh_library()
                    self.status_var.set(f'เชื่อมคลัง {count:,} รายการ · ยังไม่มี decoder {unsupported:,} · ข้อมูลข้าม {invalid:,}')
                elif kind == 'remote_command':
                    command, event, result = data
                    try:
                        result.update(self.apply_remote(command))
                    except Exception as error:
                        result.update(ok=False, error=str(error))
                    finally:
                        event.set()
                elif kind == 'popup_results':
                    window, tree, revision, rows = data
                    if window.winfo_exists() and revision == window.query_revision:
                        tree.delete(*tree.get_children())
                        for song in rows:
                            tree.insert('', 'end', iid=str(song['id']), values=(song['code'], song['title'], song['artist']))
                        if tree.get_children():
                            tree.selection_set(tree.get_children()[0])
                elif kind == 'progress':
                    self.status_var.set(f'กำลังค้นไฟล์เพลง… {data:,}')
                elif kind == 'scan_done':
                    self.scanning = False
                    count, skipped, errors = data
                    self.refresh_library()
                    self.refresh_queue()
                    self.status_var.set(('ยกเลิกแล้ว · ' if self.cancel_scan.is_set() else '') + f'ตรวจแล้ว {count:,} เพลง · ข้าม {skipped:,} · ข้อสังเกต {len(errors):,} — ดูรายงานตรวจเพลงในเมนูคลิกขวา')
                elif kind == 'job_progress':
                    self.handle_job_progress(data)
                elif kind == 'job_note':
                    self.status_var.set(data)
                elif kind == 'scan_error':
                    self.scanning = False
                    self.refresh_library();self.refresh_queue()
                    self.show_error(data)
        except queue.Empty:
            pass
        except Exception as error:
            logging.exception('UI_MESSAGE_FAILED kind=%s',locals().get('kind'))
            try:self.show_error('งานบางส่วนบันทึกไม่สำเร็จ: '+str(error))
            except Exception:logging.exception('UI_ERROR_REPORT_FAILED')
        if isinstance(self.engine, MidiPlayer):
            if self.engine.scheduler_error:
                self.show_error(self.engine.scheduler_error)
                self.engine.close()
                self.engine = None
            elif self.engine.song:
                bar, beat, total = self.engine.song.musical_position(self.engine.position)
                self.beat_var.set(f'ห้อง {bar}   จังหวะ {beat}/{total}')
        if self.remote and time.monotonic() - self.last_snapshot > .5:
            self.update_remote_snapshot()
            self.last_snapshot = time.monotonic()
        try:
            if self.engine:
                if not isinstance(self.engine, MidiPlayer) or not self.engine._scheduler:
                    self.engine.pump()
                position = self.engine.position
                self.time_var.set(f'{timestamp(position)} / {timestamp(self.engine.duration)}')
                if not self.dragging:
                    self.seek_var.set(position)
                if self.engine.ended:
                    self.engine.ended = False
                    self.on_song_ended()
            from .medley import tick as medley_tick
            try:medley_tick(self)
            except (OSError,ValueError) as error:
                from .medley_decks import cleanup
                cleanup(self)
                self.__dict__.pop('_medley_state',None)
                if self.engine:self.engine.set_volume(1 if getattr(self,'system_volume',None) is not None else self.volume_var.get()/100)
                self.show_error(error)
            from .queue_countdown import tick_countdown
            tick_countdown(self)
            self.paint_lyrics()
        except Exception as error:
            logging.exception('Playback update failed')
            if self.engine:
                self.engine.close()
                self.engine = None
            self.show_error(error)
        self.tick_after = self.after(25, self.tick)

    def on_song_ended(self):
        if self.auto_var.get() and self.song_queue.items:
            self.next_song()
        else:
            self.status_var.set('จบเพลงแล้ว')

    def search_results_ready(self):
        """Called on the UI thread after the current search is displayed."""

    def on_search_ready(self, count):
        """Optional startup preload status hook."""

    def paint_lyrics(self):
        position = self.engine.position if self.engine else 0
        try:
            offset = self.offset_var.get()
        except tk.TclError:
            offset = 0
        current, following, prefix, word, fraction = lyric_progress(self.lyrics, position, offset)
        title = self.now_var.get()
        if current:
            text = current.text
            nextline = following.text if following else ''
        elif following:
            # Show the upcoming lyrics before the first vocal cue, unpainted.
            text = following.text
            nextline = self.lyrics.lines[1].text if len(self.lyrics.lines)>1 else ''
        elif self.current_song:
            text, nextline = 'ยังไม่มีเนื้อร้องสำหรับเพลงนี้', 'คลิกขวา → เครื่องมือ → เลือกไฟล์เนื้อร้อง LRC'
        else:
            branded = self.settings.get('background_mode', 'stage') != 'none' or getattr(self, 'finished_empty', False)
            text = '' if branded else DISPLAY_NAME
            nextline = '' if branded else 'พิมพ์ค้นหาเพลง • Enter ยืนยัน • คลิกขวาเปิดเมนู'
        countdown=self.__dict__.get('_queue_countdown_seconds',0)
        if countdown and not self.current_song:
            text=f'เริ่มเพลงใน {countdown}'
            nextline='เตรียมตัวร้องเพลง • กดหยุดเพื่อยกเลิก'
            prefix=word='';fraction=0.
        for canvas in (self.preview, self.stage_canvas):
            if canvas and canvas.winfo_exists() and isinstance(canvas, StageCanvas):
                canvas.show_frame(text, nextline, prefix, title, word, fraction, self.settings)

    def write_lyric_diagnostics(self):
        value = {'song_id': self.current_song['id'], 'code': self.current_song['code'],
                 'path': self.current_song['path'], 'profile': getattr(self.lyrics,'profile','embedded MIDI / LRC'),
                 'lyric_lines': len(self.lyrics.lines), 'warning': getattr(self.engine,'lyric_warning',''),
                 'warnings': getattr(self.lyrics,'warnings',[]),
                 'removed_footer_lines':getattr(self.lyrics,'removed_footer_lines',0),
                 'first_cue_seconds': self.lyrics.lines[0].start if self.lyrics.lines else None}
        write_json(self.data_dir/'last-playback.json', value)

    def toggle_stage(self):
        new = not (self.stage and self.stage.winfo_exists())
        super().toggle_stage()
        if new:
            screens = monitors()
            index = int(self.settings.get('stage_monitor', 1 if len(screens) > 1 else 0))
            if screens:
                x, y, width, height = screens[min(max(index, 0), len(screens)-1)]
                self.stage.geometry(f'{width}x{height}{x:+}{y:+}')
            self.stage.bind('<F3>', lambda _: self.search_popup())

    def mark_loop_start(self):
        if isinstance(self.engine, MidiPlayer):
            self.loop_mark = self.engine.position
            self.status_var.set(f'จุดวน A: {timestamp(self.loop_mark)}')

    def mark_loop_end(self):
        if isinstance(self.engine, MidiPlayer) and self.loop_mark is not None:
            try:
                self.engine.set_loop(self.loop_mark, self.engine.position)
                self.status_var.set('เปิดวนช่วง A–B แล้ว')
            except ValueError as error:
                self.show_error(error)

    def clear_loop(self):
        if isinstance(self.engine, MidiPlayer):
            self.engine.set_loop()
            self.status_var.set('ยกเลิกวนเพลงแล้ว')

    def search_popup(self):
        window = DialogWindow(self)
        window.title('ค้นเพลง — Enter เข้าคิว / Esc ปิด')
        window.geometry('800x470')
        window.configure(bg='#081d58')
        window.transient(self.stage if self.stage and self.stage.winfo_exists() else self)
        window.query_revision = 0
        query = tk.StringVar()
        entry = ttk.Entry(window.content, textvariable=query, font=('Tahoma', 15))
        entry.pack(fill='x', padx=12, pady=12)
        tree = ttk.Treeview(window.content, columns=('code', 'title', 'artist'), show='headings')
        for name, text, width in [('code', 'รหัส', 100), ('title', 'ชื่อเพลง', 400), ('artist', 'ศิลปิน', 240)]:
            tree.heading(name, text=text)
            tree.column(name, width=width)
        tree.pack(fill='both', expand=True, padx=12)
        label = tk.StringVar(value='ค้นจากเพลงที่เล่นได้ในรุ่นนี้')
        ttk.Label(window.content, textvariable=label).pack(pady=10)
        pending = [None]
        def search(*_):
            if pending[0]:
                window.after_cancel(pending[0])
            def begin():
                window.query_revision += 1
                revision, value = window.query_revision, query.get()
                def worker():
                    rows = self.library.search(value, limit=50, playable_only=True)
                    self.messages.put(('popup_results', (window, tree, revision, rows)))
                threading.Thread(target=worker, daemon=True).start()
            pending[0] = window.after(160, begin)
        def add(_=None):
            if tree.selection():
                song = self.library.get(int(tree.selection()[0]))
                self.song_queue.add(QueueItem(song['id']))
                self.refresh_queue()
                label.set('เพิ่มคิวแล้ว: ' + song['title'])
            return 'break'
        def down(_):
            if tree.get_children():
                tree.focus_set()
                tree.selection_set(tree.get_children()[0])
            return 'break'
        entry.bind('<Down>', down)
        window.bind('<Return>', add)
        tree.bind('<Double-1>', add)
        window.bind('<Escape>', lambda _: window.destroy())
        query.trace_add('write', search)
        search()
        entry.focus_set()

    def backup_data(self):
        destination = filedialog.askdirectory(title='เลือกโฟลเดอร์สำรองข้อมูล')
        if not destination:
            return
        try:
            root = Path(destination) / time.strftime('X-Stage Karaoke-backup-%Y%m%d-%H%M%S')
            root.mkdir(parents=True, exist_ok=False)
            with self.library.connect() as source, closing(sqlite3.connect(root / 'songs.sqlite3')) as backup:
                source.backup(backup)
            self.song_queue.export(root / 'queue.json', self.library)
            write_json(root / 'settings.json', self.settings)
            from .first_run import write_transfer_metadata
            write_transfer_metadata(root)
            self.status_var.set('สำรองแล้ว: ' + str(root))
        except Exception as error:
            self.show_error(error)

    def restore_data(self):
        if self.engine is not None or self.recorder or self.scanning or self.remote:
            return messagebox.showinfo('กู้คืนข้อมูล','ยกเลิกเพลง (F7) หยุดบันทึกเสียง หยุดรีโมท และรอการสร้างรายการให้เสร็จก่อน',parent=self)
        folder=filedialog.askdirectory(parent=self,title='เลือกโฟลเดอร์สำรอง X-Stage Karaoke')
        if not folder:return
        try:
            from .restore import validate_backup,stage_restore
            info=validate_backup(folder)
            if not messagebox.askyesno('ยืนยันกู้คืนข้อมูล',
                f"ชุดสำรองมี {info['songs']:,} เพลง และ {len(info['queue']):,} รายการคิว\n\n"
                'จะแทนฐานข้อมูล คิว และการตั้งค่าตอนเปิดโปรแกรมครั้งถัดไป พร้อมเก็บสำรองข้อมูลปัจจุบันไว้\n'
                'ไม่คัดลอกหรือลบไฟล์เพลง และไฟล์เพลงต้องอยู่ตำแหน่งเดิม\n'
                'กรุณาปิด X-Stage หน้าต่างอื่นทั้งหมดก่อน\n\nเตรียมกู้คืนและปิดโปรแกรมตอนนี้หรือไม่?',parent=self):return
            stage_restore(folder,self.data_dir)
            messagebox.showinfo('พร้อมกู้คืน','เตรียมไฟล์แล้ว โปรแกรมจะปิด กรุณาเปิดใหม่เพื่อกู้คืนข้อมูล',parent=self)
            self.close_app()
        except (OSError,ValueError,sqlite3.Error) as error:self.show_error(error)

    def song_details(self):
        if not self.songs.selection():
            return
        song = self.library.get(int(self.songs.selection()[0]))
        messagebox.showinfo('ข้อมูลเพลง', '\n'.join([f"{song['code']} — {song['title']}", song['artist'],
            f"ชนิด: {song['format'] or song['kind']}  คีย์: {song['key_signature']}  BPM: {song['bpm']}",
            'ไฟล์: ' + song['path'], 'พบไฟล์: ' + ('พบ' if Path(song['path']).is_file() else 'ไม่พบ'),
            'สถานะ decoder: ' + ('พร้อมทดสอบเปิดเล่น' if song['playable'] else 'ยังไม่รองรับ')]), parent=self)

    def stage_settings(self):
        window = DialogWindow(self)
        window.title('จอร้องเพลง')
        window.configure(bg='#081d58')
        screens = monitors()
        names = [f'จอ {i+1}: {w}×{h} ({x},{y})' for i, (x, y, w, h) in enumerate(screens)] or ['จอหลัก']
        ttk.Label(window.content, text='ตำแหน่งจอร้อง').grid(row=0, column=0, padx=14, pady=10)
        display = ttk.Combobox(window.content, values=names, state='readonly', width=42)
        display.grid(row=0, column=1, padx=14, pady=10)
        display.current(min(int(self.settings.get('stage_monitor', 1 if len(screens)>1 else 0)), len(names)-1))
        size = tk.IntVar(value=int(self.settings.get('font_size', 84)))
        ttk.Label(window.content, text='ขนาดเนื้อร้อง (อ้างอิงจอ Full HD)').grid(row=1, column=0, padx=14, pady=10)
        ttk.Spinbox(window.content, from_=18, to=120, textvariable=size, width=8).grid(row=1, column=1, sticky='w', padx=14)
        colors = {key: self.settings.get(key, default) for key, default in [('stage_bg', '#001b68'), ('lyric_color', '#ffffff'), ('active_color', '#ffff00')]}
        for row, (key, label) in enumerate([('stage_bg', 'สีพื้นหลัง'), ('lyric_color', 'สีตัวอักษร'), ('active_color', 'สีป้ายเนื้อร้อง')], 2):
            def choose(key=key):
                color = colorchooser.askcolor(colors[key], parent=window)[1]
                if color:
                    colors[key] = color
            ttk.Button(window.content, text=label, command=choose).grid(row=row, column=0, padx=14, pady=7, sticky='ew')
        mode = tk.StringVar(value=self.settings.get('background_mode', 'stage'))
        ttk.Label(window.content, text='ภาพพื้นหลัง').grid(row=5, column=0, padx=14, pady=10)
        choices = ttk.Frame(window.content)
        choices.grid(row=5, column=1, sticky='w', padx=14)
        ttk.Radiobutton(choices, text='ภาพเวที X-STAGE', variable=mode, value='stage').pack(anchor='w')
        ttk.Radiobutton(choices, text='ไม่มีรูปพื้นหลัง', variable=mode, value='none').pack(anchor='w', pady=6)
        def save():
            try:
                self.settings.update(colors)
                self.settings.update(font_size=max(18, min(120, size.get())), stage_monitor=display.current(), background_mode=mode.get())
                self.save_settings()
                self.paint_lyrics()
                window.destroy()
            except (ValueError, tk.TclError) as error:
                self.show_error(error)
        ttk.Button(window.content, text='บันทึก', command=save, style='Accent.TButton').grid(row=7, column=1, padx=14, pady=16, sticky='e')

    def open_mixer(self):
        engine = self.engine if isinstance(self.engine, MidiPlayer) else None
        window = DialogWindow(self)
        window.title('MIDI Control — 16 ช่อง / ชิ้นกลอง')
        window.configure(bg='#081d58')
        window.geometry('1080x670')
        top = ttk.Frame(window.content, padding=10)
        top.pack(fill='x')
        heading = tk.StringVar(value='มิกเซอร์ MIDI')
        ttk.Label(top, textvariable=heading).pack(side='left')
        def panic():
            engine = self.engine if isinstance(self.engine, MidiPlayer) else None
            if engine:
                engine.seek(engine.position)
        ttk.Button(top, text='หยุดเสียงค้าง', command=panic).pack(side='right')
        devices = WinMidi.devices()
        device = ttk.Combobox(top, values=[name for _, name in devices], state='readonly', width=32)
        device.pack(side='right', padx=8)
        if devices:
            device.current(next((i for i, (number, _) in enumerate(devices) if number == self.settings.get('midi_device', -1)), 0))
        def choose_device(_):
            self.settings['midi_device'] = devices[device.current()][0]
            self.save_settings()
            self.status_var.set('เปลี่ยน MIDI output มีผลเพลงถัดไป')
        device.bind('<<ComboboxSelected>>', choose_device)
        notebook = ttk.Notebook(window.content)
        notebook.pack(fill='both', expand=True, padx=10, pady=10)
        channels, drums = ttk.Frame(notebook), ttk.Frame(notebook)
        notebook.add(channels, text='ช่อง MIDI')
        notebook.add(drums, text='ชิ้นกลอง Ch10')
        variables = []
        drum_variables = []
        syncing = [False]
        observed = [engine]
        for channel in range(16):
            group = ttk.Frame(channels, padding=6)
            group.grid(row=channel % 8, column=channel // 8, sticky='ew', padx=5)
            ttk.Label(group, text=f'Ch {channel+1:02}' + (' กลอง' if channel == 9 else ''), width=9).pack(side='left')
            gain = tk.DoubleVar(value=(engine.channel_gain[channel] if engine else 1)*100)
            pan = tk.IntVar(value=engine.pan[channel] if engine and engine.pan[channel] is not None else 64)
            patch = tk.IntVar(value=engine.program[channel] if engine and engine.program[channel] is not None else -1)
            mute = tk.BooleanVar(value=bool(engine and channel in engine.muted))
            solo = tk.BooleanVar(value=bool(engine and channel in engine.solo))
            variables.append((gain, pan, patch, mute, solo))
            def update(_=None, channel=channel, values=variables[-1]):
                engine = self.engine if isinstance(self.engine, MidiPlayer) else None
                if engine and not syncing[0] and engine is observed[0]:
                    gain, pan, patch, mute, solo = values
                    try:
                        engine.set_channel(channel, gain.get()/100, mute.get())
                        engine.set_pan(channel, pan.get())
                        engine.set_program(channel, None if patch.get() < 0 else patch.get())
                        engine.set_solo(channel, solo.get())
                    except (ValueError, tk.TclError):
                        pass
            ttk.Scale(group, from_=0, to=100, variable=gain, command=update, length=105).pack(side='left')
            ttk.Checkbutton(group, text='M', variable=mute, command=update).pack(side='left')
            ttk.Checkbutton(group, text='S', variable=solo, command=update).pack(side='left')
            ttk.Label(group, text='Pan').pack(side='left')
            ttk.Spinbox(group, from_=0, to=127, width=4, textvariable=pan, command=update).pack(side='left', padx=3)
            ttk.Label(group, text='เสียง').pack(side='left')
            box = ttk.Spinbox(group, from_=-1, to=127, width=4, textvariable=patch, command=update)
            box.pack(side='left', padx=3)
            box.bind('<Return>', update)
        ttk.Label(channels, text='M ปิดเสียง · S โซโล · Program 0–127; -1 ใช้เสียงจากเพลง · Pan 0 ซ้าย / 64 กลาง / 127 ขวา').grid(row=8, column=0, columnspan=2, padx=10, pady=12)
        for index, (note, name) in enumerate([(35,'Kick 35'),(36,'Kick 36'),(37,'Side stick'),(38,'Snare 38'),(40,'Snare 40'),(42,'Hi-hat ปิด'),(44,'Hi-hat เท้า'),(46,'Hi-hat เปิด'),(41,'Low tom'),(45,'Mid tom'),(48,'High tom'),(49,'Crash'),(51,'Ride'),(54,'Tambourine'),(56,'Cowbell'),(75,'Claves')]):
            value = tk.BooleanVar(value=bool(engine and note in engine.drum_muted))
            drum_variables.append((note, value))
            def update_drum(note=note, value=value):
                engine = self.engine if isinstance(self.engine, MidiPlayer) else None
                if engine and not syncing[0] and engine is observed[0]:
                    engine.set_drum_muted(note, value.get())
            ttk.Checkbutton(drums, text=f'ปิด {name}', variable=value, command=update_drum).grid(row=index//4, column=index%4, sticky='w', padx=18, pady=20)
        footer = ActionBar(window.footer, padding=10)
        footer.pack(fill='x')
        def save_preset():
            values = []
            for gain, pan, patch, mute, solo in variables:
                values.append(dict(gain=gain.get()/100, pan=pan.get(), program=patch.get(), mute=mute.get(), solo=solo.get()))
            self.settings['midi_preset'] = values
            self.save_settings()
            self.status_var.set('บันทึก MIDI preset แล้ว มีผลเมื่อเริ่มเพลงถัดไปด้วย')
        ttk.Button(footer, text='จำค่าเป็น preset', command=save_preset).pack(side='left')
        ttk.Button(footer, text='ปิด', command=window.destroy).pack(side='right')

        observed[0] = object()
        pending = [None]
        def follow_song():
            current = self.engine if isinstance(self.engine, MidiPlayer) else None
            if current is not observed[0]:
                observed[0] = current
                syncing[0] = True
                try:
                    for channel, (gain, pan, patch, mute, solo) in enumerate(variables):
                        gain.set((current.channel_gain[channel] if current else 1)*100)
                        pan.set(current.pan[channel] if current and current.pan[channel] is not None else 64)
                        patch.set(current.program[channel] if current and current.program[channel] is not None else -1)
                        mute.set(bool(current and channel in current.muted))
                        solo.set(bool(current and channel in current.solo))
                    for note, value in drum_variables:
                        value.set(bool(current and note in current.drum_muted))
                    heading.set(('MIDI • '+self.current_song['title']) if current and self.current_song else 'ไม่มีเพลง MIDI กำลังเล่น')
                finally:
                    syncing[0] = False
            pending[0] = window.after(150, follow_song)
        def cleanup(event):
            if event.widget is window and pending[0] is not None:
                window.after_cancel(pending[0])
                pending[0] = None
        window.bind('<Destroy>', cleanup, add='+')
        follow_song()

    def update_remote_snapshot(self):
        value = {'title': self.current_song['title'] if self.current_song else '', 'playing': bool(self.engine and self.engine.playing), 'volume': self.volume_var.get(), 'key': self.key_var.get(), 'speed': self.speed_var.get(), 'queue': []}
        from .remote_ui import enrich_snapshot
        enrich_snapshot(self, value)
        with self.snapshot_lock:
            self.remote_state = value

    def get_remote_snapshot(self):
        with self.snapshot_lock:
            value = dict(self.remote_state)
            value['sample_age'] = max(0., time.monotonic()-value.pop('_sampled', time.monotonic()))
            return value

    def dispatch_remote(self, command):
        event, result = threading.Event(), {}
        command = dict(command, _expires=time.monotonic()+2)
        self.messages.put(('remote_command', (command, event, result)))
        if not event.wait(2):
            return {'ok': False, 'error': 'เครื่องเล่นตอบช้า กรุณาลองใหม่'}
        return result

    def apply_remote(self, command):
        if command.get('_expires', float('inf')) < time.monotonic():
            return {'ok': False, 'error': 'คำสั่งหมดอายุ'}
        from .remote_ui import validate_remote_command
        validate_remote_command(self, command)
        action = command['action']
        if action in ('queue', 'approve', 'reject', 'cancel_request', 'request_key'):
            result = self.remote_requests.command(self, command, self.remote.policy)
            self.update_remote_snapshot()
            return result
        elif action in ('play_pause', 'stop'):
            getattr(self, action)()
        elif action == 'next':
            self.next_song()
        elif action in ('key', 'speed', 'volume'):
            import math
            value = float(command['value'])
            if not math.isfinite(value):
                raise ValueError('ค่าควบคุมต้องเป็นตัวเลขที่มีขอบเขต')
            if action == 'key':
                if not (isinstance(self.engine,MidiPlayer) or getattr(self.engine,'supports_pitch',False)):
                    raise ValueError('เพลงปัจจุบันไม่รองรับปรับคีย์')
                self.key_var.set(max(-12, min(12, int(value))))
                self.apply_key()
            elif action == 'speed':
                self.speed_var.set(max(50, min(150, int(value))))
                self.apply_speed()
            else:
                self.volume_var.set(max(0, min(100, value)))
                self.apply_volume()
        self.update_remote_snapshot()
        return {'ok': True}

    def remote_window(self):
        from .remote_ui import remote_window
        return remote_window(self)

    def lyric_editor(self):
        from .lyrics import parse_lrc
        window = DialogWindow(self)
        bound_song = dict(self.current_song) if self.current_song else None
        bound_engine = self.engine
        window.title('แก้ไขเนื้อร้อง LRC' + (' — '+bound_song['title'] if bound_song else ''))
        window.geometry('850x600')
        window.configure(bg='#081d58')
        text = tk.Text(window.content, font=('Tahoma', 13), undo=True)
        text.pack(fill='both', expand=True, padx=12, pady=12)
        def stamp(seconds):
            return f'[{int(seconds//60):02}:{seconds%60:05.2f}]'
        if self.lyrics.lines:
            text.insert('1.0', '\n'.join(stamp(line.start)+line.text for line in self.lyrics.lines))
        bar = ActionBar(window.footer, padding=12)
        bar.pack(fill='x')
        def mark():
            position = self.lyric_stamp_position(bound_song, bound_engine)
            if position is None:
                self.status_var.set('ประทับเวลาไม่ได้ • เพลงที่เล่นไม่ตรงกับเพลงที่เปิดแก้ไข')
                return
            line = text.index('insert').split('.')[0]
            text.insert(line+'.0', stamp(position))
        def load():
            from .lyrics import decode_text
            file = filedialog.askopenfilename(parent=window, filetypes=[('LRC','*.lrc')])
            if file:
                text.delete('1.0','end')
                text.insert('1.0', decode_text(Path(file).read_bytes()))
        def save(apply=False):
            content = text.get('1.0','end-1c')
            if not parse_lrc(content).lines:
                return messagebox.showerror('LRC', 'ต้องมีเวลา เช่น [00:10.50]เนื้อร้อง', parent=window)
            file = filedialog.asksaveasfilename(parent=window, defaultextension='.lrc', filetypes=[('LRC','*.lrc')])
            if file:
                try:
                    Path(file).write_text(content, encoding='utf-8')
                    if apply and bound_song:
                        self.apply_saved_lyrics(bound_song['path'], file, content)
                    else:
                        self.status_var.set('บันทึก LRC แล้ว: '+file)
                except OSError as error:
                    self.show_error(error)
        if bound_song:
            ttk.Label(window.content, text='บันทึกและใช้จะผูกกับเพลงที่เปิดในหน้าต่างนี้ แม้คิวเปลี่ยนเพลงแล้ว', wraplength=700).pack(fill='x', padx=12)
            ttk.Button(bar, text='บันทึกและใช้กับเพลงนี้', command=lambda: save(True), style='Accent.TButton').pack(side='left', padx=5)
        for label, command in [('เปิด LRC', load), ('ประทับเวลาปัจจุบัน', mark), ('บันทึกเป็น…', save)]:
            button = ttk.Button(bar, text=label, command=command)
            button.pack(side='left', padx=5)
            if command is mark:
                mark_button = button
        pending = [None]
        def refresh_mark():
            mark_button.configure(state='normal' if self.lyric_stamp_position(bound_song, bound_engine) is not None else 'disabled')
            pending[0] = window.after(200, refresh_mark)
        def cleanup(event):
            if event.widget is window and pending[0] is not None:
                window.after_cancel(pending[0])
                pending[0] = None
        window.bind('<Destroy>', cleanup, add='+')
        refresh_mark()

    def lyric_stamp_position(self, song, engine):
        if (song and engine is not None and self.engine is engine and self.current_song
                and self.current_song['path'] == song['path']):
            return engine.position
        return None

    def apply_saved_lyrics(self, song_path, file, content):
        from .lyrics import parse_lrc
        lyrics = parse_lrc(content)
        if not lyrics.lines:
            raise ValueError('LRC ไม่มีเนื้อร้องที่มีเวลา')
        self.settings.setdefault('lyric_files', {})[song_path] = str(Path(file).resolve())
        self.save_settings()
        if self.current_song and self.current_song['path'] == song_path:
            self.lyrics = lyrics
            self.paint_lyrics()
            self.status_var.set('บันทึกและใช้ LRC กับเพลงปัจจุบันแล้ว')
        else:
            self.status_var.set('บันทึก LRC แล้ว • ใช้อัตโนมัติเมื่อเล่นเพลงที่แก้ไขอีกครั้ง')

    def audio_settings(self):
        from .audio_dialog import AudioSettings
        existing = getattr(self, '_audio_settings_window', None)
        if existing is not None and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            existing.focus_set()
            existing.grab_set()
            return
        import logging
        before = set(self.winfo_children())
        logging.info('SOUNDFONT_WINDOW opening')
        try:
            self._audio_settings_window = AudioSettings(self)
        except Exception:
            logging.exception('SOUNDFONT_WINDOW construction failed')
            for child in set(self.winfo_children()) - before:
                if isinstance(child, AudioSettings):
                    try: child.grab_release(); child.destroy()
                    except Exception: logging.exception('SoundFont partial-window cleanup failed')
            raise
        logging.info('SOUNDFONT_WINDOW ready')

    def record_window(self):
        from .audio_tools_ui import record_window
        return record_window(self)

    def equalizer_window(self):
        from .audio_tools_ui import eq_window
        return eq_window(self)

    def audio_diagnostics_window(self):
        from .audio_tools_ui import diagnostics_window
        return diagnostics_window(self)

    def capabilities(self):
        from . import __version__
        messagebox.showinfo('สถานะ X-Stage Karaoke '+__version__,
            'มีแล้ว: ค้นคลัง DBF/NCN, คิวและ playlist, MIDI/KAR, EMK legacy SFDS, NCN24 lyrics, LRC, ปรับคีย์/tempo MIDI, '
            'mute/solo/pan/program, ปิดชิ้นกลอง, วน A–B, สองจอ, รีโมต LAN, สำรอง/กู้คืน SQLite, ประวัติ/แทรกคิว, SoundFont แยกกลุ่ม GM, เสียง FX, เมดเล่ย์ Mark Out/Fade และตัวแก้ LRC\n\n'
            'มีเงื่อนไข: ภาพ/เสียงตาม codec Windows; SoundFont ต้องมี native DLL ทางการ; WAV/MP3 ปรับคีย์แยกความเร็วต้องมี BASS FX; EQ สำหรับ BASS; บันทึกไมค์หรือไมค์ผสมเสียงลำโพง Windows ต้องมีอุปกรณ์และ SoundCard\n\n'
            'ยังไม่ครบ: EMK revision อื่น/XMK/XAK/XVK/XSF decoder, ASIO/audio bus/VST, Crossfade/Keep Rhythm เต็มรูปแบบ, fill/electone, '
            'DMX USB และระบบตู้หยอดเหรียญ\n\nไม่ใช่รุ่นที่รับรองว่าแทน eXtreme 3 ได้ครบทุกฟังก์ชัน', parent=self)

    def help(self):
        messagebox.showinfo('วิธีใช้', 'เปิดครั้งแรกจะเชื่อม Data\\SONG.DBF ของคลังเดิมอัตโนมัติ\n'
            'ค้นชื่อ/ศิลปิน/รหัส/เนื้อร้อง → Enter เข้าคิว → F5 เล่น\n'
            'F3 ค้นซ้อนจอ · F5 เล่น/พัก · F6 ถัดไป · F8 หยุด · F9 มิกเซอร์ · F11 จอร้อง\n'
            'ตั้งจอ สี พื้นหลังได้จากเมนูตั้งค่า\n'
            'เพลงเดิมไม่ถูกคัดลอกหรือแก้ไข; รองรับ EMK legacy SFDS profile ที่ทดสอบแล้ว\n'
            'ดูเมนู ความสามารถและข้อจำกัด สำหรับสถานะการพัฒนาจริง', parent=self)

    def close_app(self):
        from .shutdown import step
        if self.__dict__.get('_shutdown_done'):return
        from .shutdown import wait_for_index
        if wait_for_index(self):return
        self.closing=True
        monitor=self.__dict__.get('_wifi_monitor')
        if monitor:step(self,'ปิด WiFi monitor',monitor.close)
        if self.remote:step(self,'ปิด remote',self.remote.close);self.remote=None
        if self.recorder:step(self,'หยุดบันทึกเสียง',self.recorder.stop);self.recorder=None
        super().close_app()
