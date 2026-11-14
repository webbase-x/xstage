"""Playback-first workspace with an in-window keyboard search overlay."""
from __future__ import annotations

from .dialog_layout import DialogWindow, ActionBar
import tkinter as tk
import sqlite3
import threading
import time
from pathlib import Path
from tkinter import ttk, filedialog
from . import APP_NAME, DISPLAY_NAME, __version__
from .classic import ClassicApp
from .stage import monitors
from .playback import MidiPlayer
from .library import QueueItem, SearchCancelled
from .lyrics import Lyrics
from .keyboard_input import control_or_alt, editing_modifier


from .performance_features import PerformanceFeatures

class PlaybackApp(PerformanceFeatures,ClassicApp):
    def __init__(self, home, data_dir=None, auto_catalog=True):
        from .continuous_medley import ContinuousMedley
        self.continuous_medley = ContinuousMedley()
        self._arrow_down, self._arrow_blocked = set(), set()
        self._search_key_offsets = {}
        self.search_visible = False
        self._search_insert_next = False
        self.search_pending = True
        self.search_result_revision = -1
        self._stage_position = None
        self.queue_browser_visible = False
        self._browsed_item = None
        self._transport_timer = None
        self._pointer_on_transport = False
        self._search_condition = threading.Condition()
        self._search_request = None
        self._search_thread = None
        self._search_stopping = False
        self._active_reader = None
        self.database_ready = False
        self._search_started = time.perf_counter()
        super().__init__(home, data_dir, auto_catalog)
        self.init_system_volume()
        self.title(DISPLAY_NAME)
        self.minsize(min(800,max(300,self.winfo_screenwidth())),
                     min(500,max(250,self.winfo_screenheight())))
        self.main_fullscreen_var.set(True)
        self.attributes('-fullscreen', True)
        self.after_idle(self.focus_song_input)
        self.after(100, self.activate_startup_input)
        self.after(8000, self._background_update_tick)
        if self.transport_pinned_var.get():
            self.after_idle(self.show_transport)

    def _background_update_tick(self):
        """Check again hourly without interrupting active playback."""
        self.check_program_update(False)
        self.after(60 * 60 * 1000, self._background_update_tick)

    def _setup_style(self):
        super()._setup_style()
        style = ttk.Style(self)
        for name in ('TFrame', 'TLabel', 'TCheckbutton'):
            style.configure(name, background='#10192d', foreground='#ecf2ff')
        style.configure('Muted.TLabel', foreground='#9eacc7')
        style.configure('TButton', background='#22324e', foreground='#e8f2ff', padding=(12, 8))
        style.map('TButton', background=[('active', '#324867')])
        style.configure('Accent.TButton', background='#78e4ea', foreground='#081321')
        style.map('Accent.TButton', background=[('active', '#a5f4f5')])
        style.configure('TEntry', fieldbackground='#091225', foreground='#f5f8ff', insertcolor='#78e4ea', padding=10)
        style.configure('Treeview', background='#10192d', fieldbackground='#10192d', rowheight=34)
        style.configure('Treeview.Heading', background='#18253d', foreground='#a5b6d5', relief='flat')
        style.map('Treeview', background=[('selected', '#78e4ea')], foreground=[('selected', '#071321')])
        style.configure('Horizontal.TScale', background='#10192d', troughcolor='#31425c')
        for option, value in [('background', '#10192d'), ('foreground', '#eaf2ff'),
                ('activeBackground', '#294563'), ('activeForeground', '#ffffff'), ('font', '{Tahoma} 11')]:
            self.option_add('*Menu.'+option, value)
        # Use Windows' Thai-capable UI family and enough height for both levels
        # of combining marks in controls, result rows, and queue cards.
        self.option_add('*Font', '{Leelawadee UI} 11')
        style.configure('.', font=('Leelawadee UI', 11))
        style.configure('Treeview', font=('Leelawadee UI', 11), rowheight=40)
        style.configure('Treeview.Heading', font=('Leelawadee UI', 10, 'bold'))
        style.configure('Search.Treeview', font=('Leelawadee UI', 11), rowheight=32)
        from tkinter.font import Font
        line=Font(self,family='Leelawadee UI',size=11).metrics('linespace')
        style.configure('Treeview',rowheight=max(40,line+12))
        style.configure('Search.Treeview',rowheight=max(32,line+10))

    def _build(self):
        self.config(menu='')
        self.settings.setdefault('stage_bg', '#090d1f')
        self.settings.setdefault('font_size', 64)
        self.settings.setdefault('active_color', '#ffe079')
        self.surface = tk.Frame(self, bg='#090d1f')
        self.surface.pack(fill='both', expand=True)
        self.preview = self.canvas_class(self.surface, takefocus=True)
        self.preview.pack(fill='both', expand=True)
        self.video_frame = tk.Frame(self.surface, bg='black', takefocus=True)
        self.video_frame.bind('<Configure>', lambda _: self.resize_video())
        self.now_var = tk.StringVar(value='พิมพ์ชื่อเพลง/รหัสได้เลย • * แล้วพิมพ์รหัสเพื่อแทรกคิวถัดไป')
        self.status_var = tk.StringVar(value='กำลังเตรียมค้นหา • พิมพ์คำค้นรอได้เลย')
        self.status_label = tk.Label(self.surface, textvariable=self.status_var,
            bg='#10192d', fg='#a9bad6', font=('Leelawadee UI', 10), anchor='w', padx=12, pady=5)
        self._build_search()
        self._build_queue()
        self._build_controls()
        self._build_queue_browser()
        self._build_transport()
        self.main_fullscreen_var = tk.BooleanVar(value=False)
        self.stage_enabled_var = tk.BooleanVar(value=False)
        self.stage_fullscreen_var = tk.BooleanVar(value=False)
        self.stage_monitor_var = tk.IntVar(value=int(self.settings.get('stage_monitor', 1)))
        self.context_menu = tk.Menu(self, tearoff=False)
        for widget in (self, self.preview, self.video_frame, self.status_label):
            widget.bind('<Button-3>', self.show_context_menu)
        self.preview.bind('<Button-1>', lambda _: self.focus_song_input())
        self.surface.bind('<Configure>', self.layout_overlays)
        self.bind('<Motion>', self.pointer_motion, add='+')
        self.bind('<FocusIn>', lambda event: self.focus_song_input() if event.widget is self else None, add='+')

    def _build_search(self):
        self.search_overlay = tk.Frame(self.surface, bg='#10192d', padx=12, pady=8,
                                       highlightbackground='#10192d', highlightthickness=0)
        self.search_header = ttk.Frame(self.search_overlay, height=76)
        self.search_header.pack(fill='x', pady=(0, 8))
        self.search_header.pack_propagate(False)
        self.search_query_slot = ttk.Frame(self.search_header, width=280)
        self.search_query_slot.pack(side='left', fill='y', padx=(0, 14))
        self.search_query_slot.pack_propagate(False)
        ttk.Label(self.search_query_slot, text='ค้นหาเพลง • พิมพ์ได้เลย', foreground='#78e4ea',
                  font=('Leelawadee UI', 10)).pack(anchor='w')
        self.search_input_slot = ttk.Frame(self.search_query_slot)
        self.search_input_slot.pack(fill='both', expand=True, pady=(3, 0))
        ttk.Style(self).configure('Search.TEntry', fieldbackground='#10192d', foreground='#f4f7ff',
                                  borderwidth=0, relief='flat', padding=(2, 2), insertcolor='#78e4ea')
        self.search_var = tk.StringVar()
        # Real native text input remains mapped while resting, including IME/paste.
        self.search_entry = ttk.Entry(self.surface, textvariable=self.search_var,
                                      font=('Leelawadee UI', 25), style='Search.TEntry')
        self.search_entry.place(x=-4, y=-4, width=1, height=1)
        self.search_var.trace_add('write', self.schedule_search)
        self.favorite_var = tk.BooleanVar(value=False)
        self.playable_var = tk.BooleanVar(value=True)
        self.song_count = tk.StringVar()
        self.search_selected_title = tk.StringVar(value='ชื่อเพลง / ศิลปิน / รหัส / เนื้อร้อง')
        self.search_selected_meta = tk.StringVar(value='')
        self.search_selected_lyric = tk.StringVar(value='')
        detail = ttk.Frame(self.search_header)
        detail.pack(side='left', fill='both', expand=True)
        self.search_title_label = ttk.Label(detail, textvariable=self.search_selected_title,
            font=('Leelawadee UI', 16, 'bold'), foreground='#f2f6ff', anchor='w')
        self.search_title_label.pack(fill='x')
        ttk.Label(detail, textvariable=self.search_selected_meta, style='Muted.TLabel').pack(anchor='w')
        self.search_lyric_label = ttk.Label(detail, textvariable=self.search_selected_lyric,
            foreground='#ffe079', anchor='w', font=('Leelawadee UI', 10))
        self.search_lyric_label.pack(fill='x')
        table = ttk.Frame(self.search_overlay)
        table.pack(fill='both', expand=True)
        self.songs = ttk.Treeview(table, columns=('code', 'title', 'artist', 'kind'),
                                 show='headings', selectmode='browse', height=4, style='Search.Treeview')
        for name, label, width in [('code', 'รหัส', 90), ('title', 'ชื่อเพลง', 320),
                                   ('artist', 'ศิลปิน', 190), ('kind', 'ชนิด', 75)]:
            self.songs.heading(name, text=label)
            self.songs.column(name, width=width, minwidth=45, stretch=name in ('title', 'artist'))
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.songs.yview)
        self.songs.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.songs.pack(fill='both', expand=True)
        self.songs.tag_configure('unsupported', foreground='#8c9ab6')
        footer = ttk.Frame(self.search_overlay)
        footer.pack(fill='x', pady=(5, 0))
        ttk.Label(footer, textvariable=self.song_count, style='Muted.TLabel').pack(side='right')
        self.search_action_var = tk.StringVar()
        ttk.Label(footer, textvariable=self.search_action_var,
                  foreground='#78e4ea', font=('Leelawadee UI', 10)).pack(side='left')
        for widget in (self.search_entry, self.songs):
            self.bind_arrow_navigation(widget)
            widget.bind('<Return>', self.input_enter)
            widget.bind('<Control-Return>', lambda event: self.play_search_now())
            widget.bind('<Escape>', self.escape_main)
        # The normal hidden search entry has native input focus. Intercept
        # Numpad * before Tk inserts it into the search text.
        self.search_entry.bind('<KeyPress-asterisk>', self.insert_next_code_shortcut)
        self.search_entry.bind('<KeyPress-KP_Multiply>', self.insert_next_code_shortcut)
        self.songs.bind('<Double-1>', lambda event: self.confirm_search())
        self.songs.bind('<Button-3>', self.show_context_menu)
        self.songs.bind('<<TreeviewSelect>>', lambda _: self.update_search_detail())

    def _dialog(self, title, geometry):
        window = DialogWindow(self)
        window.withdraw()
        window.title(title)
        window.geometry(geometry)
        window.configure(bg='#10192d')
        window.protocol('WM_DELETE_WINDOW', window.withdraw)
        window.bind('<Escape>', lambda _: window.withdraw())
        return window

    def _build_queue(self):
        self.queue_window = self._dialog('คิวเพลง — X-Stage Karaoke', '850x440')
        self.queue_title = tk.StringVar(value='คิวเพลง')
        self.auto_var = tk.BooleanVar(value=bool(True))
        bar = ttk.Frame(self.queue_window.content, padding=12)
        bar.pack(fill='x')
        ttk.Label(bar, textvariable=self.queue_title, font=('Leelawadee UI', 14, 'bold')).pack(side='left')
        ttk.Label(bar, text='จบเพลงแล้วเล่นคิวถัดไปอัตโนมัติ', style='Muted.TLabel').pack(side='right')
        self.queues = ttk.Treeview(self.queue_window.content, columns=('number', 'title', 'singer', 'setting'),
                                  show='headings', selectmode='browse')
        for name, label, width in [('number', '#', 45), ('title', 'ชื่อเพลง', 340),
                                   ('singer', 'ผู้ร้อง', 160), ('setting', 'คีย์ / เร็ว', 120)]:
            self.queues.heading(name, text=label)
            self.queues.column(name, width=width, minwidth=30, stretch=name in ('title', 'singer'))
        self.queues.pack(fill='both', expand=True, padx=12)
        self.queues.bind('<Double-1>', lambda _: self.edit_queue())
        self.queues.bind('<Return>', self.queue_table_enter)
        for sequence, step in (('<Alt-Up>', 1), ('<Alt-Down>', -1)):
            self.queues.bind(sequence, lambda event, step=step: self.adjust_queue_key(self.queue_index(), step))
        self.queues.bind('<KeyRelease-Return>', lambda _: setattr(self, '_queue_enter_held', False))
        self.queues.bind('<FocusOut>', lambda _: setattr(self, '_queue_enter_held', False))
        actions = ActionBar(self.queue_window.footer, padding=12)
        actions.pack(fill='x')
        for label, command in [('▲', lambda: self.move_queue(-1)), ('▼', lambda: self.move_queue(1)),
                ('ลบ', self.remove_queue), ('แก้คิว', self.edit_queue), ('เล่นคิวนี้', self.play_queue_selected),
                ('แทรกเพลง', self.insert_queue_window), ('ประวัติ', self.history_window), ('นำเข้า', self.import_queue), ('ส่งออก', self.export_queue)]:
            ttk.Button(actions, text=label, command=command).pack(side='left', padx=3)

    def _build_controls(self):
        self.control_window = self._dialog('ควบคุมการเล่น — X-Stage Karaoke', '760x310')
        controls = ttk.Frame(self.control_window.content, padding=16)
        controls.pack(fill='both', expand=True)
        ttk.Label(controls, textvariable=self.now_var, font=('Leelawadee UI', 14, 'bold'), wraplength=700).pack(anchor='w')
        self.time_var = tk.StringVar(value='00:00 / 00:00')
        self.beat_var = tk.StringVar(value='ห้อง — จังหวะ —')
        info = ttk.Frame(controls)
        info.pack(fill='x', pady=10)
        ttk.Label(info, textvariable=self.time_var).pack(side='left')
        ttk.Label(info, textvariable=self.beat_var).pack(side='right')
        self.seek_var = tk.DoubleVar(value=0)
        self.seek = ttk.Scale(controls, from_=0, to=1, variable=self.seek_var)
        self.seek.pack(fill='x')
        self.seek.bind('<ButtonPress-1>', lambda _: setattr(self, 'dragging', True))
        self.seek.bind('<ButtonRelease-1>', self.seek_release)
        bar = ttk.Frame(controls)
        bar.pack(fill='x', pady=12)
        self.play_button = ttk.Button(bar, text='▶ เล่น / พัก F5', command=self.play_pause)
        self.play_button.pack(side='left')
        for label, command in [('หยุด F8', self.stop), ('ถัดไป F6', self.next_song)]:
            ttk.Button(bar, text=label, command=command).pack(side='left', padx=5)
        self.key_var = tk.IntVar(value=0)
        self.speed_var = tk.IntVar(value=100)
        self.volume_var = tk.DoubleVar(value=float(self.settings.get('volume', 75)))
        self.melody_var = tk.BooleanVar(value=False)
        ttk.Label(bar, text='คีย์').pack(side='left', padx=5)
        self.key_box = ttk.Spinbox(bar, from_=-12, to=12, width=4, textvariable=self.key_var, command=self.apply_key)
        self.key_box.pack(side='left')
        self.key_box.bind('<Return>', lambda _: self.apply_key())
        ttk.Label(bar, text='เร็ว %').pack(side='left', padx=5)
        self.speed_box = ttk.Spinbox(bar, from_=50, to=150, width=5, textvariable=self.speed_var, command=self.apply_speed)
        self.speed_box.pack(side='left')
        self.speed_box.bind('<Return>', lambda _: self.apply_speed())
        bar = ttk.Frame(controls)
        bar.pack(fill='x')
        ttk.Label(bar, text='ระดับเสียง').pack(side='left')
        ttk.Scale(bar, from_=0, to=100, variable=self.volume_var, command=self.apply_volume, length=200).pack(side='left', padx=8)
        ttk.Checkbutton(bar, text='ปิดไกด์ MIDI Ch4', variable=self.melody_var, command=self.apply_melody).pack(side='left')
        ttk.Button(bar, text='ยกเลิกเพลง F7', command=self.cancel_current_song).pack(side='right')
        self.lyric_controls = ttk.Frame(controls)
        self.lyric_controls.pack(fill='x', pady=12)
        self.offset_var = tk.IntVar(value=0)
        ttk.Label(self.lyric_controls, text='ชดเชยเนื้อร้อง ms').pack(side='left')
        ttk.Spinbox(self.lyric_controls, from_=-10000, to=10000, increment=100,
                    width=8, textvariable=self.offset_var, command=self.save_offset).pack(side='left', padx=8)
        ttk.Button(self.lyric_controls, text='บันทึกชดเชย', command=self.save_offset).pack(side='left')

    def _build_transport(self):
        self.transport_pinned_var = tk.BooleanVar(value=False)
        self.transport = tk.Frame(self.surface, bg='#10192d', padx=12, pady=6,
                                   highlightbackground='#344760', highlightthickness=1)
        self.status_label.pack(in_=self.transport, side='bottom', fill='x')
        row = ttk.Frame(self.transport)
        row.pack(side='top', fill='x')
        from .tooltip import attach
        for label, tip, command in [('◀','เพลงก่อนหน้า / เลื่อนคิว', lambda: self.browse_queue(-1)), ('▶ / Ⅱ','เล่นหรือพัก • F5', self.play_pause),
                ('■','หยุดเพลง • F8', self.stop), ('ยกเลิก','ยกเลิกเพลงปัจจุบัน • F7', self.cancel_current_song), ('▶▶','เพลงถัดไป • F6', self.next_song)]:
            def invoke(command=command):
                command()
                self.focus_song_input()
            attach(ttk.Button(row, text=label, width=5, command=invoke),tip).pack(side='left', padx=(0, 4))
        ttk.Label(row, text='เสียง', style='Muted.TLabel').pack(side='left', padx=(8, 3))
        ttk.Scale(row, from_=0, to=100, variable=self.volume_var, command=self.apply_volume, length=95).pack(side='left')
        self.transport_queue_var = tk.StringVar(value='คิว 0')
        attach(ttk.Button(row, textvariable=self.transport_queue_var, command=lambda: self.browse_queue(1)), 'เปิดคิวเพลง • F10').pack(side='right', padx=(6, 0))
        attach(ttk.Button(row, text='EQ', command=self.equalizer_window), 'เปิดอีควอไลเซอร์').pack(side='right', padx=4)
        medley_button = ttk.Menubutton(row, text='สุ่มเมดเล่ย์')
        medley_menu = tk.Menu(medley_button, tearoff=False)
        medley_menu.add_command(label='▶ เริ่มสุ่มต่อเนื่องแยกตามประเภทอัตโนมัติ', command=self.start_continuous_medley)
        medley_menu.add_command(label='■ หยุดสุ่มต่อเนื่อง', command=self.stop_continuous_medley)
        medley_menu.add_separator()
        medley_menu.add_command(label='สร้างชุดสุ่ม…', command=lambda: self.after_idle(self.random_medley_window))
        medley_menu.add_command(label='เพลงฮิตจากประวัติ…  Ctrl+Shift+H', command=lambda: self.after_idle(self.popular_medley_window))
        medley_menu.add_command(label='ยกเลิกเพลงที่เหลือในชุด', command=lambda: self.after_idle(self.cancel_random_medley))
        medley_button.configure(menu=medley_menu)
        medley_button.pack(side='right', padx=4)
        ttk.Label(row, textvariable=self.now_var, style='Muted.TLabel', anchor='w').pack(side='left', fill='x', expand=True, padx=12)

    def pointer_motion(self, event):
        if event.widget.winfo_toplevel() is not self:
            return
        in_header = 0 <= event.y_root-self.winfo_rooty() <= 28
        pending = self.__dict__.get('_keyboard_hover_after')
        panel = self.__dict__.get('_midi_keyboard_window')
        visible = panel is not None and panel.winfo_exists() and panel.winfo_ismapped()
        if in_header and not visible:
            if pending is None:
                def reveal():
                    self._keyboard_hover_after = None
                    x,y = self.winfo_pointerxy()
                    if (self.winfo_rootx() <= x < self.winfo_rootx()+self.winfo_width()
                            and 0 <= y-self.winfo_rooty() <= 28):
                        self.open_midi_keyboard()
                self._keyboard_hover_after = self.after(300,reveal)
        elif pending is not None:
            self.after_cancel(pending);self._keyboard_hover_after=None
        threshold = self.transport.winfo_height() if self.transport.winfo_ismapped() else 18
        self._pointer_on_transport = event.y_root >= self.winfo_rooty()+self.winfo_height()-threshold
        if self._pointer_on_transport and not self.search_visible and not self.queue_browser_visible:
            self.show_transport()

    def show_transport(self):
        self.transport.place(relx=0, rely=1, relwidth=1, y=0, anchor='sw')
        self.transport.lift()
        if self._transport_timer:
            self.after_cancel(self._transport_timer)
        self._transport_timer = self.after(700, self.hide_transport)

    def hide_transport(self, force=False):
        if self._transport_timer:
            self.after_cancel(self._transport_timer)
        self._transport_timer = None
        if not force and self.scanning:
            if hasattr(self,'after'):self._transport_timer=self.after(700,self.hide_transport)
            return
        x,y=self.winfo_pointerxy()
        self._pointer_on_transport=(self.transport.winfo_ismapped() and self.transport.winfo_rootx()<=x<self.transport.winfo_rootx()+self.transport.winfo_width() and self.transport.winfo_rooty()<=y<self.transport.winfo_rooty()+self.transport.winfo_height())
        if not force and (self.transport_pinned_var.get() or self._pointer_on_transport):
            self._transport_timer=self.after(700,self.hide_transport)
            return
        self.transport.place_forget()

    def pin_transport(self):
        self.settings['transport_pinned'] = self.transport_pinned_var.get()
        self.save_settings()
        self.show_transport() if self.transport_pinned_var.get() else self.hide_transport(force=True)

    def _build_queue_browser(self):
        self.queue_browser = tk.Frame(self.surface, bg='#10192d', padx=18, pady=16,
                                       highlightbackground='#3b6882', highlightthickness=1)
        header = ttk.Frame(self.queue_browser)
        header.pack(fill='x', pady=(0, 12))
        ttk.Label(header, text='เลือกเพลงในคิว', font=('Leelawadee UI', 14, 'bold'), foreground='#78e4ea').pack(side='left')
        self.queue_browser_count = tk.StringVar(value='')
        ttk.Label(header, textvariable=self.queue_browser_count, style='Muted.TLabel').pack(side='right')
        cards = ttk.Frame(self.queue_browser)
        cards.pack(fill='x')
        self.queue_cards = []
        cards.columnconfigure(0, weight=1)
        for index in range(3):
            frame = tk.Frame(cards, bg='#203c50' if index == 1 else '#10192d', padx=10, pady=4)
            frame.grid(row=index, column=0, sticky='ew', pady=2)
            color = '#203c50' if index == 1 else '#10192d'
            label = tk.Label(frame, bg=color, fg='#78e4ea', font=('Leelawadee UI', 11), width=10, anchor='w')
            label.pack(side='left')
            meta = tk.Label(frame, bg=color, fg='#a6b7d1', font=('Leelawadee UI', 11), width=24, anchor='e')
            meta.pack(side='right')
            title = tk.Label(frame, bg=color, fg='#f4f7ff', font=('Leelawadee UI', 16, 'bold'), anchor='w')
            title.pack(side='left', fill='x', expand=True)
            for widget in (frame, label, title, meta):
                widget.bind('<Button-1>', lambda event, slot=index: self.select_queue_card(slot))
                widget.bind('<Double-1>', lambda event: self.play_browsed_queue())
            self.queue_cards.append((label, title, meta))
        ttk.Label(self.queue_browser, text='← เลื่อนขึ้น   → เลื่อนลง   Enter เล่นคิวที่เลือก   Esc ปิด',
                  foreground='#78e4ea').pack(anchor='w', pady=(6, 0))

    def layout_overlays(self, event=None):
        from .stage_layout import overlay_layout
        width, height = self.surface.winfo_width(), self.surface.winfo_height()
        layout = overlay_layout(width, height)
        if self.search_visible:
            x, y, w, h = layout['search']
            self.search_overlay.place(x=x, y=y, width=w, height=h)
        if self.queue_browser_visible:
            x, y, w, h = layout['queue']
            self.queue_browser.place(x=x, y=y, width=w, height=h)
        self.songs.configure(height=layout['rows'])
        self.search_query_slot.configure(width=layout['query_width'])
        # Single-line labels clip at the right edge instead of expanding the band.
        self.search_title_label.configure(wraplength=0)
        self.search_lyric_label.configure(wraplength=0)
        for index, (_, title, _) in enumerate(self.queue_cards):
            title.configure(wraplength=0)

    def _queue_position(self):
        return next((index for index, item in enumerate(self.song_queue.items) if item is self._browsed_item), None)

    def browse_queue(self, step):
        if not self.song_queue.items:
            self.status_var.set('คิวว่าง • พิมพ์ค้นหาเพลง แล้วกด Enter เพิ่มเข้าคิว')
            self.show_transport()
            return 'break'
        index = self._queue_position() if self.queue_browser_visible else None
        index = (index+step) % len(self.song_queue.items) if index is not None else (0 if step>=0 else len(self.song_queue.items)-1)
        self._browsed_item = self.song_queue.items[index]
        self.hide_search()
        self.hide_transport(force=True)
        self.queue_browser_visible = True
        self.update_queue_browser()
        self.layout_overlays()
        self.queue_browser.lift()
        self.focus_song_input()
        return 'break'

    def update_queue_browser(self):
        index = self._queue_position()
        if index is None:
            self.hide_queue_browser()
            return
        count = len(self.song_queue.items)
        self.queue_browser_count.set(f'{index+1} / {count} เพลง')
        for slot, (label, title, meta) in enumerate(self.queue_cards):
            position = index+slot-1
            if 0 <= position < count:
                item = self.song_queue.items[position]
                song = self.library.get(item.song_id)
                label.configure(text=f'คิว {position+1}' + (' ▶' if slot == 1 else ''))
                title.configure(text=song['title'] if song else 'ไม่พบข้อมูลเพลง')
                meta.configure(text=(item.singer or (song['artist'] if song else ''))[:32]+f' • คีย์ {item.key:+d}')
            else:
                label.configure(text='')
                title.configure(text='—')
                meta.configure(text='')

    def select_queue_card(self, slot, play=False):
        index = self._queue_position()
        if index is not None and 0 <= index+slot-1 < len(self.song_queue.items):
            self._browsed_item = self.song_queue.items[index+slot-1]
            self.update_queue_browser()
            if play:
                self.play_browsed_queue()

    def hide_queue_browser(self):
        was_visible = self.queue_browser_visible
        self.queue_browser_visible = False
        self.queue_browser.place_forget()
        self._browsed_item = None
        if was_visible and not self.search_visible:
            self.focus_song_input()
        if self.transport_pinned_var.get() and not self.search_visible:
            self.show_transport()
        return 'break'

    def play_browsed_queue(self):
        index = self._queue_position()
        if index is not None:
            self.play_queue_now(index)
        return 'break'

    def play_queue_selected(self):
        index = self.queue_index()
        if index is not None:
            self.play_queue_now(index)
        return 'break'

    def play_queue_now(self, index):
        if not 0 <= index < len(self.song_queue.items):
            return 'break'
        item = self.song_queue.items[index]
        self.cancel_current_song(advance=False)
        self.last_load_error = ''
        try:
            started = self.start_song(item, quiet=True)
        except Exception as error:
            import logging
            logging.exception('Selected queue playback failed; queue preserved')
            self.last_load_error = str(error)
            started = False
        if started:
            # Remove this occurrence only, even when several entries share a song ID.
            position = next((i for i, value in enumerate(self.song_queue.items) if value is item), None)
            if position is not None:
                self.song_queue.pop(position)
            self.refresh_queue()
        else:
            self.cancel_current_song(advance=False)
            self.status_var.set('เปิดเพลงที่เลือกไม่สำเร็จ • เก็บคิวเดิมไว้ • '+self.last_load_error)
        return 'break'

    def queue_table_enter(self, event=None):
        if not getattr(self, '_queue_enter_held', False):
            self._queue_enter_held = True
            self.play_queue_selected()
        return 'break'

    def refresh_queue(self, select=None):
        super().refresh_queue(select)
        if hasattr(self, 'search_action_var'):
            action = self.search_action_text()
            self.search_action_var.set(f'↑ ↓ เลือกเพลง   {action}   Ctrl+Enter เล่นทันที   Esc ปิด')
            if self.search_visible and not self.search_pending:
                self.update_search_detail()
        if hasattr(self, 'transport_queue_var'):
            self.transport_queue_var.set(f'คิว {len(self.song_queue.items)}')
        if self.queue_browser_visible:
            self.update_queue_browser()

    def start_continuous_medley(self):
        """Repeat shuffled, detected rhythm groups until the user stops."""
        if not self.database_ready:
            self.status_var.set('กำลังเตรียมคลังเพลง กรุณารอสักครู่')
            self.show_transport()
            return
        self.continuous_medley.start(self)
        self.status_var.set('เริ่มสุ่มเมดเลย์ต่อเนื่อง · กำลังตรวจประเภทเพลง…')
        self.show_transport()

    def stop_continuous_medley(self, stop_playback=True):
        if not self.continuous_medley.enabled and not self.continuous_medley.session_ids:
            return
        self.continuous_medley.stop(self)
        from .medley import cancel_random_fill
        cancel_random_fill(self)
        if stop_playback:
            super().stop()
        self.status_var.set('หยุดสุ่มเมดเลย์ต่อเนื่องแล้ว')
        self.show_transport()

    def next_song(self, index=0):
        """Keep automatic medley alive even when the user manually skips songs."""
        result = super().next_song(index)
        if self.continuous_medley.enabled:
            self.continuous_medley.fill(self)
        return result

    def stop(self):
        # F8 and the transport stop button must stop automatic replenishment.
        self.stop_continuous_medley(stop_playback=False)
        return super().stop()

    def random_medley_window(self):
        if not self.database_ready:
            self.status_var.set('กำลังเตรียมคลังเพลง กรุณารอสักครู่')
            self.show_transport()
            return
        from .random_medley import open_window
        open_window(self)

    def popular_medley_window(self):
        if not self.database_ready:
            self.status_var.set('กำลังเตรียมคลังเพลง กรุณารอสักครู่')
            self.show_transport()
            return
        from .random_medley import open_window
        open_window(self, 'popular')

    def enqueue_random_medley(self, items, play_next=False):
        from .library import SUPPORTED
        from .name_duplicates import identity

        occupied = {item.song_id for item in self.song_queue.items}
        if self.current_item:
            occupied.add(self.current_item.song_id)
        occupied_keys = set()
        try:
            ids = tuple(occupied | {item.song_id for item in items})
            rows = {}
            with self.library.connect() as db:
                db.execute('BEGIN')
                for start in range(0, len(ids), 500):
                    batch = ids[start:start + 500]
                    placeholders = ','.join('?' for _ in batch)
                    rows.update((row['id'], row) for row in db.execute(
                        f'SELECT id,path,title,artist,key_signature,playable,duplicate_of,duplicate_state '
                        f'FROM songs WHERE id IN ({placeholders})', batch))
            for song_id in tuple(occupied):
                row = rows.get(song_id)
                if row:
                    occupied.add(row['duplicate_of'] or song_id)
                    occupied_keys.add(identity(row['title'], row['artist'], row['key_signature']))
            for item in items:
                row = rows.get(item.song_id)
                if not row or not row['playable'] or row['duplicate_of'] or row['duplicate_state'] in (
                        'moved', 'recycled', 'deleted', 'invalid') or Path(row['path']).suffix.lower() not in SUPPORTED:
                    return 0
                key = identity(row['title'], row['artist'], row['key_signature'])
                if item.song_id in occupied or (key is not None and key in occupied_keys):
                    return 0
                occupied.add(item.song_id)
                occupied_keys.add(key)
            count = self.song_queue.add_medley(items, play_next=play_next)
        except (OSError, ValueError, sqlite3.Error) as error:
            self.show_error(error)
            return 0
        if not count:
            return 0
        self.refresh_queue()
        if play_next and self.engine is None and self.current_song is None:
            self.next_song()
        else:
            where = 'เป็นชุดถัดไป' if play_next else 'ท้ายคิว'
            self.status_var.set(f'เพิ่มชุดเมดเล่ย์ {count} เพลง {where}')
            self.show_transport()
        return count

    def cancel_random_medley(self):
        current = getattr(self.current_item, 'medley_session', '')
        sessions = [item.medley_session for item in self.song_queue.items if item.medley_session]
        if not sessions or (current and current not in sessions):
            self.status_var.set('ไม่มีเพลงในชุดเมดเล่ย์ที่รอเล่น')
            self.show_transport()
            return
        try:
            count = self.song_queue.cancel_medley(current or sessions[0])
        except (OSError, ValueError) as error:
            self.show_error(error)
            return
        self.refresh_queue()
        self.status_var.set(f'นำเพลงที่เหลือในชุดเมดเล่ย์ออกจากคิว {count} เพลง')
        from .medley import cancel_random_fill
        cancel_random_fill(self, advance=True)
        self.show_transport()

    def _queue_key(self, event, step=None):
        if event.widget.winfo_toplevel() is not self or self.search_visible:
            return
        if event.widget.winfo_class() in ('Entry', 'TEntry', 'TSpinbox', 'Text', 'TCombobox', 'TScale', 'Scale'):
            return
        if step is not None:
            return self.browse_queue(step)
        if self.queue_browser_visible:
            return self.play_browsed_queue()

    def _bindings(self):
        for key, command in [('<F2>', self.manage_songs), ('<F3>', self.search_popup), ('<Control-f>', self.search_popup),
                ('<F5>', self.play_pause), ('<F6>', self.next_song), ('<F7>', self.cancel_current_song), ('<F8>', self.stop),
                ('<F4>', self.toggle_midi_keyboard), ('<F9>', self.open_mixer), ('<F10>', self.show_queue), ('<F11>', self.toggle_main_fullscreen)]:
            self.bind(key, lambda event, command=command: self._shortcut(event, command))
        self.bind('<Key>', self.instant_search, add='+')
        self.bind('<Control-Shift-H>', lambda event: self._shortcut(event, self.popular_medley_window))
        self.bind('<Control-Shift-h>', lambda event: self._shortcut(event, self.popular_medley_window))
        self.bind('<Escape>', self.escape_main)
        self.bind('<Shift-F10>', self.show_context_menu)
        self.bind('<Menu>', self.show_context_menu)
        self.bind_arrow_navigation(self)
        self.bind('<FocusOut>', lambda _: self.after_idle(self.reset_arrows_if_unfocused), add='+')
        self.bind('<Return>', self._queue_key)
        self.bind_volume_wheel(self)
        self.bind_key_shortcuts(self)
        # The hidden entry owns typing focus: intercept before its class inserts text.
        self.bind_key_shortcuts(self.search_entry)
        self.bind_key_shortcuts(self.songs)

    def bind_arrow_navigation(self, widget):
        for key in ('Up', 'Down', 'Left', 'Right'):
            widget.bind('<KeyPress-'+key+'>', self.arrow_press)
            widget.bind('<KeyRelease-'+key+'>', self.arrow_release)

    def arrow_press(self, event):
        if control_or_alt(event.state):
            return
        top = event.widget.winfo_toplevel()
        if top is not self and top is not getattr(self, 'stage', None):
            return
        if event.widget is not self.search_entry and event.widget.winfo_class() in (
                'Entry', 'TEntry', 'Spinbox', 'TSpinbox', 'Text', 'Combobox', 'TCombobox', 'Scale', 'TScale'):
            return
        if not hasattr(self, '_arrow_down'):
            self._arrow_down, self._arrow_blocked = set(), set()
        key = event.keysym
        if key in self._arrow_blocked:
            return 'break'
        if key not in self._arrow_down:
            # The newest physical press wins. Repeats from an older held key
            # remain ignored until that key is physically released.
            self._arrow_blocked.update(self._arrow_down)
            self._arrow_down.add(key)
        if key in ('Left', 'Right'):
            self.hide_search()
            return self.browse_queue(-1 if key == 'Left' else 1)
        return self.navigate_search(-1 if key == 'Up' else 1)

    def arrow_release(self, event):
        getattr(self, '_arrow_down', set()).discard(event.keysym)
        getattr(self, '_arrow_blocked', set()).discard(event.keysym)

    def reset_arrows_if_unfocused(self):
        focused = self.focus_get()
        if focused is None or focused.winfo_toplevel() not in (self, getattr(self, 'stage', None)):
            self._arrow_down, self._arrow_blocked = set(), set()

    def bind_key_shortcuts(self, window):
        for sequence, step in (('<KeyPress-Delete>', -1), ('<KeyPress-Insert>', 1)):
            window.bind(sequence, lambda event, step=step: self.change_key_shortcut(event, step))

        for sequence, step in (('<Alt-KeyPress-Up>', 1), ('<Alt-KeyPress-Down>', -1)):
            window.bind(sequence, lambda event, step=step: self.alt_key_shortcut(event, step))

    def alt_key_shortcut(self, event, step):
        if event.state & 0x05:  # Leave Ctrl/Shift combinations alone.
            return
        from types import SimpleNamespace
        # Tk resolves the Alt binding (including platform-specific Alt masks).
        # Reuse the same context checks without treating Alt as text editing.
        return self.change_key_shortcut(SimpleNamespace(widget=event.widget, state=0), step)

    def change_key_shortcut(self, event, step):
        if editing_modifier(event.state):  # Preserve Shift/Ctrl/Alt editing combinations.
            return
        top = event.widget.winfo_toplevel()
        if top is not self and top is not getattr(self, 'stage', None):
            return
        if self.search_visible and event.widget in (self.search_entry, self.songs):
            if self.search_pending or self.search_result_revision != self.search_revision or not self.songs.selection():
                self.status_var.set('เลือกเพลงจากผลค้นหาก่อนปรับคีย์')
                return 'break'
            song_id = int(self.songs.selection()[0])
            from .library import song_supports_key
            if not song_supports_key(self.library.get(song_id)):
                self.status_var.set('เพลงนี้ไม่รองรับปรับคีย์ • MIDI หรือ WAV/MP3 ที่ติดตั้ง BASS FX')
                return 'break'
            offsets = getattr(self, '_search_key_offsets', None)
            if offsets is None:
                self._search_key_offsets = offsets = {}
            offsets[song_id] = max(-12, min(12, offsets.get(song_id, 0)+step))
            self.update_search_detail()
            self.status_var.set(f'คีย์เพลงที่เลือก {offsets[song_id]:+d} • Enter เพิ่มเข้าคิว/เล่นเพลง')
            return 'break'
        if getattr(self, 'queue_browser_visible', False):
            return self.adjust_queue_key(self._queue_position(), step)
        hidden_search = event.widget is self.search_entry and not self.search_visible
        if not hidden_search and event.widget.winfo_class() in (
                'Entry', 'TEntry', 'Spinbox', 'TSpinbox', 'Text', 'Combobox', 'TCombobox'):
            return
        if isinstance(self.engine,MidiPlayer) or getattr(self.engine,'supports_pitch',False):
            self.key_var.set(max(-12, min(12, self.key_var.get()+step)))
            self.apply_key()
            self.status_var.set(f'คีย์เสียง {self.key_var.get():+d} ครึ่งเสียง')
            self.paint_lyrics()
        else:
            self.status_var.set('เพลงปัจจุบันยังไม่มีระบบปรับคีย์พร้อมใช้งาน')
        return 'break'

    def adjust_queue_key(self, index, step):
        from .library import song_supports_key
        if index is None or not 0 <= index < len(self.song_queue.items):
            return 'break'
        item = self.song_queue.items[index]
        if not song_supports_key(self.library.get(item.song_id)):
            self.status_var.set('เพลงในคิวนี้ไม่รองรับปรับคีย์ • MIDI หรือ WAV/MP3 ที่ติดตั้ง BASS FX')
            return 'break'
        item.key = max(-12, min(12, item.key+step))
        self.song_queue.save()
        self.refresh_queue(index)
        self.status_var.set(f'คิว {index+1} • คีย์ {item.key:+d} • เปลี่ยนเฉพาะรายการนี้')
        return 'break'

    def init_system_volume(self):
        import sys
        self.system_volume = None
        self._volume_sync_timer = None
        self._syncing_volume = False
        self._windows_muted = False
        if sys.platform == 'win32':
            from .system_volume import WindowsVolume
            try:
                self.system_volume = WindowsVolume()
            except OSError as error:
                self.status_var.set(f'เชื่อมตัวควบคุมระดับเสียงไม่สำเร็จ • ใช้เสียงในโปรแกรม: {error}')
            else:
                self.poll_system_volume()

    def read_system_volume(self):
        value, muted = self.system_volume.read()
        self._syncing_volume = True
        try:
            self.volume_var.set(value)
            self._windows_muted = muted
        finally:
            self._syncing_volume = False
        return value

    def poll_system_volume(self):
        try:
            self.read_system_volume()
        except OSError:
            pass  # A removed device is retried on the next tick; never write on startup.
        self._volume_sync_timer = self.after(400, self.poll_system_volume)

    def apply_volume(self, _=None):
        if getattr(self, '_syncing_volume', False):
            return
        controller = getattr(self, 'system_volume', None)
        if controller is None:
            return super().apply_volume(_)
        try:
            value, muted = controller.write(self.volume_var.get())
            self._syncing_volume = True
            try:
                self.volume_var.set(value)
                self._windows_muted = muted
            finally:
                self._syncing_volume = False
        except OSError as error:
            try:
                self.read_system_volume()
            except OSError:
                pass
            self.status_var.set(f'ปรับระดับเสียงไม่สำเร็จ: {error}')

    def bind_volume_wheel(self, window):
        for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            window.bind(sequence, self.volume_wheel, add='+')

    def volume_wheel(self, event):
        # Only the playback surface owns this gesture; lists/dialogs keep scrolling.
        target = event.widget
        if hasattr(event, 'x_root') and hasattr(event, 'y_root'):
            target = self.winfo_containing(event.x_root, event.y_root) or target
        surfaces = (self, self.surface, self.preview, self.video_frame,
                    self.stage, self.stage_canvas, self.stage_video)
        if not any(target is widget for widget in surfaces if widget is not None):
            return
        from .volume_wheel import wheel_change
        remainder, change = wheel_change(getattr(self, '_wheel_remainder', 0),
                                         getattr(event, 'delta', 0), getattr(event, 'num', None))
        self._wheel_remainder = remainder
        if change:
            if getattr(self, 'system_volume', None) is not None:
                try:
                    self.read_system_volume()
                except OSError as error:
                    self.status_var.set(f'ไม่พบตัวควบคุมระดับเสียง: {error}')
                    return 'break'
            self.volume_var.set(max(0, min(100, self.volume_var.get()+change)))
            self.apply_volume()
            self.show_volume_overlay()
        return 'break'

    def show_volume_overlay(self):
        value = round(self.volume_var.get())
        source = 'ระดับเสียง'
        muted = value == 0 or getattr(self, '_windows_muted', False)
        message = f'{source}  {value}%' + (' • ปิดเสียง' if muted else '')
        for parent in (self.surface, self.stage):
            if parent is None or not parent.winfo_exists():
                continue
            label = getattr(parent, '_volume_overlay', None)
            if label is None or not label.winfo_exists():
                label = parent._volume_overlay = tk.Label(parent, bg='#10192d', fg='#78e4ea',
                    font=('Leelawadee UI', 18, 'bold'), padx=18, pady=10,
                    highlightbackground='#345366', highlightthickness=1)
                for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
                    label.bind(sequence, lambda event: self.volume_wheel_on_overlay(event))
            label.configure(text=message)
            label.place(relx=1, x=-24, y=108, anchor='ne')
            label.lift()
        timer = getattr(self, '_volume_osd_timer', None)
        if timer is not None:
            self.after_cancel(timer)
        self._volume_osd_timer = self.after(1600, self.hide_volume_overlay)

    def volume_wheel_on_overlay(self, event):
        # Let repeated wheel input work while the pointer is over the feedback.
        from types import SimpleNamespace
        return self.volume_wheel(SimpleNamespace(widget=self.preview,
            delta=getattr(event, 'delta', 0), num=getattr(event, 'num', None)))

    def hide_volume_overlay(self):
        self._volume_osd_timer = None
        for parent in (self.surface, self.stage):
            if parent is not None and parent.winfo_exists():
                label = getattr(parent, '_volume_overlay', None)
                if label is not None and label.winfo_exists():
                    label.place_forget()

    def _shortcut(self, event, command):
        if event.widget.winfo_toplevel() is self:
            command()
            return 'break'

    def focus_song_input(self):
        """Arm native text entry without showing the search panel."""
        if not self.search_entry.winfo_ismapped():
            self.search_entry.update_idletasks()
        if not self.search_visible:
            self.search_entry.selection_range(0, 'end')
            self.search_entry.icursor('end')
        self.search_entry.focus_set()

    def activate_startup_input(self):
        if self.closing:
            return
        focused = self.focus_get()
        if focused and focused.winfo_toplevel() is not self:
            return
        self.lift()
        self.focus_force()
        self.focus_song_input()

    def input_enter(self, event=None):
        if self.queue_browser_visible:
            return self.play_browsed_queue()
        if self.search_visible:
            return self.confirm_search()
        return 'break'

    def insert_next_code_shortcut(self, event):
        """* then song code then Enter inserts at the front of the waiting queue.

        Never steal an asterisk from a visible search or a different editor.
        No global keyboard hook or third-party macro software is required.
        """
        if event.widget.winfo_toplevel() is not self or control_or_alt(event.state):
            return None
        if self.search_visible:
            return None
        if event.widget is not self.search_entry and event.widget.winfo_class() in (
                'Entry', 'TEntry', 'TSpinbox', 'Text', 'TCombobox'):
            return None
        self._search_insert_next = True
        self.search_popup(initial='', select_all=False)
        self.status_var.set('แทรกคิวถัดไป • พิมพ์รหัสเพลงแล้วกด Enter')
        return 'break'

    def instant_search(self, event):
        if event.widget.winfo_toplevel() is not self or control_or_alt(event.state):
            return
        if event.widget.winfo_class() in ('Entry', 'TEntry', 'TSpinbox', 'Text', 'TCombobox'):
            return
        if not self.search_visible and (event.char == '*' or getattr(event, 'keysym', '') == 'KP_Multiply'):
            return self.insert_next_code_shortcut(event)
        if event.char and event.char.isprintable() and (self.search_visible or not event.char.isspace()):
            initial = self.search_var.get() + event.char if self.search_visible else event.char
            self.search_popup(initial)
            return 'break'

    def search_popup(self, initial=None, select_all=True):
        self.search_visible = True
        self.search_action_var.set(f'↑ ↓ เลือกเพลง   {self.search_action_text()}   Ctrl+Enter เล่นทันที   Esc ปิด')
        self.hide_queue_browser()
        self.hide_transport(force=True)
        self.search_entry.place_forget()
        self.search_entry.place(in_=self.search_input_slot, x=0, y=0, relwidth=1, relheight=1)
        self.layout_overlays()
        self.search_overlay.lift()
        if initial is not None:
            self.search_var.set(initial)
            self.search_entry.selection_clear()
        elif select_all:
            self.search_entry.selection_range(0, 'end')
        else:
            self.search_entry.selection_clear()
        self.search_entry.update_idletasks()
        self.search_entry.lift()
        self.search_entry.focus_set()
        self.search_entry.icursor('end')
        return 'break'

    def hide_search(self):
        self._pending_search_action = None
        self.search_visible = False
        self._search_insert_next = False
        self.search_overlay.place_forget()
        self.search_entry.place_forget()
        self.search_entry.place(in_=self.surface, x=-4, y=-4, width=1, height=1)
        self.focus_song_input()
        if self.transport_pinned_var.get():
            self.show_transport()
        return 'break'

    def schedule_search(self, *_):
        self._pending_search_action = None
        # The overlay opens on the first key; the newest query starts at idle.
        if _ and not self.search_visible and self.search_var.get().strip():
            self.search_popup(select_all=False)
        self.search_revision += 1
        if self._active_reader:
            try:
                self._active_reader.interrupt()
            except Exception:
                pass
        self.search_pending = True
        self.songs.selection_remove(self.songs.selection())
        self.song_count.set('กำลังค้นหา…' if self.database_ready else 'กำลังเตรียมค้นหา • รับคำค้นแล้ว…')
        self.search_selected_title.set('กำลังค้นหา…')
        self.search_selected_meta.set('')
        self.search_selected_lyric.set('')
        if self.search_after:
            self.after_cancel(self.search_after)
        self.search_after = self.after_idle(self.refresh_library)

    def refresh_library(self):
        self.search_after = None
        self.search_revision += 1
        self.search_pending = True
        request = self.search_revision, self.search_var.get(), self.favorite_var.get(), self.playable_var.get()
        with self._search_condition:
            self._search_request = request
            self._search_condition.notify()
        if self._search_thread is None:
            self._search_thread = threading.Thread(target=self._search_work, daemon=True, name='instant-song-search')
            self._search_thread.start()

    def _search_work(self):
        from .name_duplicates import NameIndex
        names=NameIndex()
        reader = None
        saved = self.settings.get('search_preload', [])
        recent = list(saved)[:5] if isinstance(saved, list) else []
        try:
            reader = self.library.open_reader()
            count = reader.warm_up()
            self._active_reader = reader
            self.messages.put(('search_ready', count))
            while True:
                with self._search_condition:
                    self._search_condition.wait_for(lambda: self._search_stopping or self._search_request is not None or bool(recent))
                    if self._search_stopping:
                        return
                    request, self._search_request = self._search_request, None
                if request is None:
                    # Warm only small query/ID caches. New typing cancels this.
                    query = recent.pop(0)
                    if not isinstance(query, str) or not query.strip():
                        continue
                    preload_revision = self.search_revision
                    try:
                        reader.search(query, limit=200, playable_only=True,
                            cancelled=lambda: self._search_stopping or self._search_request is not None or
                                              preload_revision != self.search_revision)
                    except Exception:
                        # Preload is best effort; interactive search stays alive.
                        pass
                    continue
                revision, query, favorite, playable = request
                cancelled = lambda: self._search_stopping or revision != self.search_revision
                try:
                    rows = reader.search(query, favorite, limit=200, playable_only=playable, cancelled=cancelled)
                    if hasattr(reader,'db'):
                        names.refresh(reader.db,cancelled);names.annotate(rows)
                    if not cancelled():
                        self.messages.put(('search_results', (revision, rows, reader.count())))
                except SearchCancelled:
                    continue
                except Exception as error:
                    if not cancelled():
                        self.messages.put(('search_error', str(error)))
        except Exception as error:
            if not self._search_stopping:
                self.messages.put(('search_error', str(error)))
        finally:
            names.close()
            self._active_reader = None
            if reader:
                reader.close()

    def on_search_ready(self, count):
        self.database_ready = True
        self._index_ready_ms = round((time.perf_counter()-self._search_started)*1000, 1)
        if not self.current_song and not self.scanning:
            self.status_var.set(f'พร้อมค้นหา • คลัง {count:,} เพลง • พิมพ์ชื่อเพลงได้เลย')

    def remember_search(self):
        query = self.search_var.get().strip()
        recent = self.settings.get('search_preload', [])
        if not isinstance(recent, list):
            recent = []
        if query:
            self.settings['search_preload'] = ([query]+[old for old in recent if isinstance(old, str) and old != query])[:5]
            self.save_settings()

    def search_results_ready(self):
        self.search_pending = False
        self.search_result_revision = self.search_revision
        rows = self.songs.get_children()
        if rows:
            first=getattr(self,'_search_rows',{}).get(rows[0],{})
            keeper=str(first.get('name_keeper_id') or rows[0])
            target=keeper if keeper in rows else rows[0]
            self.songs.selection_set(target)
            self.songs.focus(target)
            self.songs.see(target)
        else:
            self.song_count.set('ไม่พบเพลง — ลองชื่อเพลง ศิลปิน รหัส หรือเนื้อร้อง')
        self.update_search_detail()
        pending = self.__dict__.pop('_pending_search_action', None)
        if pending and pending[0] == self.search_revision and self.search_visible and rows:
            if pending[1] == 'play':
                self.play_search_now()
            else:
                self.confirm_search()

    def update_search_detail(self):
        selected = self.songs.selection()
        song = getattr(self, '_search_rows', {}).get(selected[0]) if selected and not self.search_pending else None
        if song:
            self.search_selected_title.set(f"{song['code']}  {song['title']}".strip())
            self.search_selected_meta.set('  ·  '.join(str(value) for value in
                (song['artist'], song['format'] or song['kind'],
                 ('คีย์ '+song['key_signature']) if song['key_signature'] else '',
                 f"ปรับคีย์ {self.__dict__.get('_search_key_offsets', {}).get(int(selected[0]), 0):+d}",
                 (str(song['bpm'])+' BPM') if song['bpm'] else '', song['rhythm']) if value))
            action = self.search_action_text()
            self.search_selected_lyric.set((song['first_lyric'] or action+' • Ctrl+Enter เล่นทันที')[:200])
        elif not self.search_pending:
            self.search_selected_title.set('ไม่พบเพลง')
            self.search_selected_meta.set('ลองเปลี่ยนคำค้นหา หรือคลิกขวาเพื่อเพิ่มคลังเพลง')
            self.search_selected_lyric.set('')

    def search_queue_item(self, song_id):
        from .library import song_supports_key
        key = self.__dict__.get('_search_key_offsets', {}).get(song_id, 0)
        return QueueItem(song_id, key=key if song_supports_key(self.library.get(song_id)) else 0)

    def consume_search_key(self, song_id):
        self.__dict__.get('_search_key_offsets', {}).pop(song_id, None)
        if '_search_rows' in self.__dict__:
            self.update_search_detail()

    def add_selected(self):
        if self.search_pending or self.search_result_revision != self.search_revision:
            return 'break'
        for iid in self.songs.selection():
            song = self.library.get(int(iid))
            if song and song['playable']:
                if self.__dict__.get('_search_insert_next', False):
                    self.song_queue.insert(0, self.search_queue_item(song['id']))
                else:
                    self.song_queue.add(self.search_queue_item(song['id']))
                self.consume_search_key(song['id'])
        self.refresh_queue()
        self.update_search_detail()
        return 'break'

    def play_selected(self):
        return self.play_search_now()


    def defer_search_action(self, action):
        # Enter must not be discarded while the worker is finishing the query.
        # Flush an idle-scheduled query now, but never run SQLite on the UI thread.
        if self.__dict__.get('search_after'):
            self.after_cancel(self.search_after)
            self.refresh_library()
        self._pending_search_action = (self.search_revision, action)
        self.status_var.set('รับคำสั่งแล้ว • รอผลค้นหาล่าสุด…')
        return 'break'

    def play_search_now(self):
        if self.search_visible and (self.search_pending or self.search_result_revision != self.search_revision):
            return self.defer_search_action('play')
        if self.search_visible and not self.search_pending and self.search_result_revision == self.search_revision and self.songs.selection():
            song_id = int(self.songs.selection()[0])
            if self.start_song(self.search_queue_item(song_id)):
                self.consume_search_key(song_id)
                self.remember_search()
                self.hide_search()
        return 'break'

    def navigate_search(self, step):
        if not self.search_visible:
            self.search_popup()
        if self.search_pending:
            return 'break'
        rows = self.songs.get_children()
        if rows:
            selected = self.songs.selection()
            index = rows.index(selected[0]) if selected and selected[0] in rows else 0
            index = max(0, min(len(rows)-1, index + step))
            self.songs.selection_set(rows[index])
            self.songs.focus(rows[index])
            self.songs.see(rows[index])
            self.update_search_detail()
        self.search_entry.selection_clear()
        self.search_entry.icursor('end')
        self.search_entry.xview_moveto(1)
        self.search_entry.focus_set()
        return 'break'

    def can_play_search_immediately(self):
        from .playback import can_autoplay_search
        return can_autoplay_search(self.engine, self.song_queue.items)

    def search_action_text(self):
        if self.__dict__.get('_search_insert_next', False):
            return 'Enter แทรกเป็นเพลงถัดไป'
        return 'Enter เล่นทันที (ยังไม่มีเพลง)' if self.can_play_search_immediately() else 'Enter เพิ่มเข้าคิว'

    def confirm_search(self):
        if self.search_pending or self.search_result_revision != self.search_revision:
            return self.defer_search_action('confirm')
        if self.songs.selection():
            song = self.library.get(int(self.songs.selection()[0]))
            if song and song['playable']:
                if self.__dict__.get('_search_insert_next', False):
                    # Preserve the currently playing song and put this occurrence
                    # first in the waiting queue. The normal queue code persists it.
                    self.song_queue.insert(0, self.search_queue_item(song['id']))
                    self.refresh_queue(0)
                    self.status_var.set(f"แทรกคิวถัดไปแล้ว: {song['title']} • คิว {len(self.song_queue.items)} เพลง")
                elif self.can_play_search_immediately():
                    if not self.start_song(self.search_queue_item(song['id'])):
                        return 'break'
                    self.status_var.set(f"กำลังเล่น: {song['title']}")
                else:
                    self.song_queue.add(self.search_queue_item(song['id']))
                    self.refresh_queue()
                    self.status_var.set(f"เข้าคิวแล้ว: {song['title']} • คิว {len(self.song_queue.items)} เพลง • F5 เล่น")
                self.consume_search_key(song['id'])
                self.remember_search()
                self.hide_search()
        return 'break'

    def cancel_current_song(self, advance=True):
        if getattr(self,'_cleanup_busy',False):return self.status_var.set('กำลังลบเพลงตามรายงาน กรุณารอให้งานเสร็จ')
        from .medley_decks import cleanup
        cleanup(self)
        from .performance_features import history_finish
        history_finish(self,'interrupted')
        from .queue_countdown import cancel_countdown
        cancel_countdown(self)
        had_song = self.engine is not None or self.current_song is not None
        title = self.current_song['title'] if self.current_song else ''
        engine, self.engine = self.engine, None
        if engine:
            try:
                engine.close()
            except OSError as error:
                self.show_error(error)
        self.current_song = self.current_item = None
        self.__dict__.pop('_medley_carry', None)
        if advance and had_song and self.song_queue.items:
            self.next_song()
            return
        self.lyrics = Lyrics()
        self.loop_mark = None
        self.key_var.set(0)
        self.speed_var.set(100)
        self.offset_var.set(0)
        self.seek_var.set(0)
        self.seek.configure(to=1)
        self.time_var.set('00:00 / 00:00')
        self.beat_var.set('ห้อง — จังหวะ —')
        self.now_var.set('')
        self.show_main_media(False)
        self.update_stage_mode()
        self.paint_lyrics()
        self.status_var.set(('ยกเลิกแล้ว: '+title if title else 'ยังไม่มีเพลงกำลังเล่น')+
                            f' • คิวรอ {len(self.song_queue.items)} เพลง')
        if not self.search_visible:
            self.show_transport()
            self.focus_song_input()
        if self.remote:
            self.update_remote_snapshot()

    def escape_main(self, event):
        if event.widget.winfo_toplevel() is not self:
            return
        if self.search_visible:
            return self.hide_search()
        if self.queue_browser_visible:
            return self.hide_queue_browser()
        if self.main_fullscreen_var.get():
            self.main_fullscreen_var.set(False)
            self.attributes('-fullscreen', False)
        return 'break'

    def show_main_media(self, video):
        self.preview.pack_forget()
        self.video_frame.pack_forget()
        (self.video_frame if video else self.preview).pack(fill='both', expand=True)
        if self.search_visible:
            self.search_overlay.lift()
            self.search_entry.lift()
        if self.queue_browser_visible:
            self.queue_browser.lift()

    def show_queue(self):
        selected = self.queue_index()
        selected = min(selected if selected is not None else 0, len(self.song_queue.items)-1)
        self.refresh_queue(selected if selected >= 0 else None)
        self.queue_window.deiconify()
        self.queue_window.lift()
        self.queues.focus_set()

    def toggle_midi_keyboard(self):
        panel=self.__dict__.get('_midi_keyboard_window')
        if panel is not None and panel.winfo_exists() and panel.winfo_ismapped():
            panel._keyboard_hide()
        else:
            self.open_midi_keyboard()
            self._midi_keyboard_window._keyboard_pinned=True
        return 'break'

    def open_midi_keyboard(self):
        from .midi_keyboard import open_keyboard
        open_keyboard(self)

    def show_controls(self):
        self.control_window.deiconify()
        self.control_window.lift()

    def toggle_main_fullscreen(self):
        value = not bool(self.attributes('-fullscreen'))
        self.main_fullscreen_var.set(value)
        self.attributes('-fullscreen', value)

    def manage_songs(self):
        self.show_catalog_maintenance()

    def defer_menu_command(self, callback):
        """Finish native menu tracking before opening another window/dialog."""
        self.context_menu.unpost()
        self.context_menu.grab_release()
        def invoke():
            if self.closing:
                return
            try:
                callback()
            except Exception as error:
                import logging
                logging.exception('Menu command failed')
                self.show_error(error)
        self.after_idle(invoke)

    def start_index_job(self, operation, deduplicate=False, on_done=None):
        self.show_transport()
        return super().start_index_job(operation,deduplicate=deduplicate,on_done=on_done)

    def show_context_menu(self, event):
        from .context_menu import populate_context_menu
        # Use the row under the mouse, never an unrelated earlier selection.
        if getattr(event, 'widget', None) is self.songs and getattr(event, 'num', None) == 3:
            row = self.songs.identify_row(event.y)
            if row:
                self.songs.selection_set(row)
                self.songs.focus(row)
                self.update_search_detail()
        populate_context_menu(self, self.context_menu, tk.Menu, monitors())
        x = event.x_root if getattr(event, 'num', None) == 3 else self.winfo_rootx()+80
        y = event.y_root if getattr(event, 'num', None) == 3 else self.winfo_rooty()+80
        try:
            self.context_menu.tk_popup(x, y)
        finally:
            self.context_menu.grab_release()
        return 'break'

    def dismiss_overlays(self):
        self.hide_search()
        self.hide_queue_browser()
        self.focus_song_input()

    def minimize_main(self):
        self.attributes('-fullscreen', False)
        self.main_fullscreen_var.set(False)
        self.iconify()

    def current_song_details(self):
        from tkinter import messagebox
        song = self.current_song
        if song:
            messagebox.showinfo('เพลงปัจจุบัน', f"{song['code']} — {song['title']}\n{song['artist']}\n{song['path']}", parent=self)

    def check_program_update(self, interactive=True):
        from .program_updates import check_in_background
        check_in_background(self, __version__, interactive=interactive)

    def about_program(self):
        from PIL import Image, ImageTk
        from .branding import asset
        window = DialogWindow(self)
        window.title('รายละเอียดโปรแกรม')
        panel = ttk.Frame(window.content, padding=24)
        panel.pack(fill='both', expand=True)
        try:
            with Image.open(asset('xstage-logo.jpg')) as source:
                logo=source.convert('RGB');logo.thumbnail((150,150),Image.Resampling.LANCZOS)
            photo=ImageTk.PhotoImage(logo)
            label=ttk.Label(panel,image=photo);label.image=photo
            label.pack(pady=(0,16))
        except OSError:
            pass
        ttk.Label(panel,text=f'X-Stage Karaoke รุ่น {__version__}',font=('Tahoma',18,'bold')).pack(pady=8)
        for text in ('ผู้พัฒนาโปรแกรม','ครูไพรัช  อินควรชุม','รร.เทศบาล 1(ถนนนครนอก)','เทศบาลนครสงขลา จ.สงขลา'):
            ttk.Label(panel,text=text,font=('Tahoma',12),wraplength=400,justify='center').pack(pady=4)
        ttk.Button(window.footer,text='ปิด',command=window.destroy).pack(pady=12)

    def choose_midi_output(self):
        from .playback import WinMidi
        devices = WinMidi.devices()
        window = DialogWindow(self)
        window.title('เลือกมิดิขาออก — X-Stage Karaoke')
        window.transient(self)
        body = ttk.Frame(window.content, padding=18)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='อุปกรณ์ Windows MIDI • ใช้กับเพลงถัดไป').pack(anchor='w', pady=(0, 12))
        combo = ttk.Combobox(body, values=[name for _, name in devices], width=48, state='readonly')
        combo.pack(fill='x')
        if devices:
            current = int(self.settings.get('midi_device', -1))
            combo.current(next((i for i, (device, _) in enumerate(devices) if device == current), 0))
        else:
            ttk.Label(body, text='ไม่พบอุปกรณ์ MIDI ในระบบ').pack(anchor='w', pady=8)
        def save():
            if combo.current() >= 0:
                self.settings.update(midi_device=devices[combo.current()][0], synth_backend='winmm')
                self.save_settings()
                self.status_var.set('เลือก Windows MIDI แล้ว มีผลเพลงถัดไป')
                window.destroy()
        ttk.Label(body, text='หากใช้ SoundFont ให้เลือกผ่านเมนูซาวด์ฟอนท์', style='Muted.TLabel').pack(anchor='w', pady=10)
        ttk.Button(body, text='ใช้ Windows MIDI', command=save, state='normal' if devices else 'disabled').pack(anchor='e')

    @staticmethod
    def _submenu(parent, label, commands):
        child = tk.Menu(parent, tearoff=False)
        parent.add_cascade(label=label, menu=child)
        for title, command in commands:
            child.add_command(label=title, command=command)

    def toggle_stage(self):
        self.set_stage_enabled(not bool(self.stage and self.stage.winfo_exists()))

    def set_stage_enabled(self, enabled):
        if not enabled:
            self.close_stage()
            return
        if not (self.stage and self.stage.winfo_exists()):
            super().toggle_stage()
            self.stage.bind('<Button-3>', self.show_context_menu)
            self.stage_canvas.bind('<Button-3>', self.show_context_menu)
            self.stage_video.bind('<Button-3>', self.show_context_menu)
            self.stage.bind('<F11>', lambda _: self._toggle_stage_fullscreen())
            self.bind_volume_wheel(self.stage)
            self.bind_key_shortcuts(self.stage)
            self.bind_arrow_navigation(self.stage)
            self.stage.bind('<FocusOut>', lambda _: self.after_idle(self.reset_arrows_if_unfocused), add='+')
        self.stage_enabled_var.set(True)
        self.reposition_stage()

    def choose_stage_monitor(self):
        self.settings['stage_monitor'] = self.stage_monitor_var.get()
        self.save_settings()
        self.set_stage_enabled(True)

    def reposition_stage(self):
        screens = monitors()
        if self.stage and screens:
            index = max(0, min(int(self.settings.get('stage_monitor', 1)), len(screens)-1))
            x, y, width, height = screens[index]
            self.stage.geometry(f'{width}x{height}{x:+}{y:+}')
            self._stage_position = index
            self.stage_monitor_var.set(index)
            self.stage.lift()

    def _toggle_stage_fullscreen(self):
        self.stage_fullscreen_var.set(not self.stage_fullscreen)
        self.set_stage_fullscreen()
        return 'break'

    def set_stage_fullscreen(self):
        self.set_stage_enabled(True)
        self.stage_fullscreen = self.stage_fullscreen_var.get()
        if self.stage_fullscreen:
            self.stage.overrideredirect(False)
        self.stage.attributes('-fullscreen', self.stage_fullscreen)
        if not self.stage_fullscreen:
            self.stage.overrideredirect(True)

    def exit_stage_fullscreen(self):
        super().exit_stage_fullscreen()
        self.stage_fullscreen_var.set(False)

    def close_stage(self):
        super().close_stage()
        self.stage_enabled_var.set(False)
        self.stage_fullscreen_var.set(False)

    def save_settings(self):
        super().save_settings()
        if self.stage and self._stage_position != self.settings.get('stage_monitor', 1):
            self.reposition_stage()

    def start_song(self, item, quiet=False):
        if not (self.__dict__.get("_medley_overlap") or self.__dict__.get("_medley_prepared")):
            from .medley_decks import cleanup
            cleanup(self)
        voice=self.__dict__.get('_keyboard_voice')
        from .bass import BassSynth
        if voice and not isinstance(voice.output,BassSynth):voice.close()

        from .queue_countdown import cancel_countdown
        cancel_countdown(self)
        self.finished_empty = False
        from .performance_features import history_finish,history_start
        history_finish(self,'interrupted')
        result = super().start_song(item, quiet=quiet)
        if result:
            from .medley import begin
            begin(self)
            history_start(self,item)
            self.hide_queue_browser()
            if not self.search_visible:
                self.show_transport()
        return result

    def on_song_ended(self):
        """Advance once, or release the finished player and leave a clean stage."""
        continuous_medley = getattr(self, 'continuous_medley', None)
        if continuous_medley is not None and continuous_medley.enabled:
            continuous_medley.fill(self)
        from .transition_report import record
        record(self,'ended',queue_count=len(self.song_queue.items))
        from .performance_features import history_finish
        history_finish(self,'completed')
        from .medley import end_random_medley
        if end_random_medley(self):
            return
        if self.song_queue.items:
            from .medley import carry_at_end
            carry_at_end(self)
            from .medley_decks import advance_prepared
            try:advance_prepared(self)
            finally:self.__dict__.pop('_medley_carry',None)
        else:
            self.cancel_current_song(advance=False)
            self.finished_empty = True
            self.now_var.set('')
            self.status_var.set('จบเพลงแล้ว • คิวว่าง')
            self.hide_queue_browser()
            self.hide_transport(force=True)
            self.paint_lyrics()

    def paint_lyrics(self):
        engine = self.engine
        position = engine.position if engine else 0
        data = {'seconds': int(position), 'duration': engine.duration if engine else 0,
                'idle': self.current_song is None,
                'status': 'กำลังเล่น' if engine and engine.playing else ('พัก / หยุด' if engine else 'พร้อมเล่น')}
        if not self.database_ready and not engine:
            data['status'] = 'เตรียมค้นหา…'
        if isinstance(engine, MidiPlayer) and engine.song:
            song = engine.song
            tempo = 500000
            for _, seconds, value in song.tempo_map:
                if seconds > position:
                    break
                tempo = value
            bar, beat, beats = song.musical_position(position)
            data.update(bpm=round(60e6/tempo*engine.speed), bar=bar, beat=beat, beats=beats)
        from .branding import wall_clock, song_details
        title, artist, details = song_details(self.current_song, data['duration'], int(getattr(engine, 'key', 0)))
        if getattr(self, 'finished_empty', False) and not self.current_song:
            title = artist = details = ''
        data.update(clock=wall_clock(), song_title=title, song_artist=artist, song_details=details)
        from .remote_ui import stage_invite
        data['remote_invite'] = stage_invite(self)
        from .stage_layout import overlay_layout
        layout = overlay_layout(self.surface.winfo_width(), self.surface.winfo_height())
        reserved_top = 132 if self.surface.winfo_height() < 650 else 174
        if self.search_visible or self.queue_browser_visible:
            _, y, _, h = layout['search' if self.search_visible else 'queue']
            reserved_top = y + h + 12
        for canvas in (self.preview, self.stage_canvas):
            if canvas:
                canvas.telemetry = dict(data)
                if canvas is self.preview:
                    canvas.telemetry.update(reserved_top=reserved_top,
                        reserved_bottom=self.transport.winfo_reqheight()+12 if self.transport.winfo_manager() else 24)
        super().paint_lyrics()

    def choose_background(self):
        from .branding import asset
        return self.set_background(asset('xstage-background.jpg'))

    def set_background(self, file):
        from .branding import asset
        target = asset('xstage-background.jpg')
        if Path(file).resolve() != target.resolve():
            raise ValueError('เลือกได้เฉพาะภาพเวที X-STAGE ที่มากับโปรแกรม หรือไม่มีรูปพื้นหลัง')
        self.settings['background_mode'] = 'stage'
        self.settings.pop('background_image', None)
        self.save_settings()
        self.paint_lyrics()
        self.status_var.set('ใช้ภาพเวที X-STAGE ทั้งจอหลักและจอร้อง')
        return target

    def clear_background(self):
        self.settings['background_mode'] = 'none'
        self.settings.pop('background_image', None)
        self.save_settings()
        self.paint_lyrics()

    def background_options(self):
        window = self._dialog('ภาพพื้นหลัง', '480x220')
        ttk.Label(window.content, text='ความมืดของภาพ เพื่อให้อ่านเนื้อร้องชัด', font=('Leelawadee UI', 12, 'bold')).pack(padx=20, pady=(20, 12))
        dim = tk.DoubleVar(value=float(self.settings.get('background_dim', .25))*100)
        def preview(value):
            self.settings['background_dim'] = float(value)/100
            self.paint_lyrics()
        ttk.Scale(window.content, from_=0, to=80, variable=dim, command=preview).pack(fill='x', padx=24)
        row = ActionBar(window.footer, padding=18)
        row.pack(fill='x')
        ttk.Button(row, text='ใช้ภาพเวที X-STAGE', command=self.choose_background).pack(side='left')
        ttk.Button(row, text='ไม่มีรูปพื้นหลัง', command=self.clear_background).pack(side='left', padx=7)
        def done():
            self.save_settings()
            window.destroy()
        ttk.Button(row, text='เสร็จ', command=done).pack(side='right')
        window.protocol('WM_DELETE_WINDOW', done)
        window.bind('<Escape>', lambda _: done())
        window.deiconify()

    def close_app(self):
        from .shutdown import step
        from .medley_decks import cleanup
        from .performance_features import history_finish
        if self.__dict__.get('_shutdown_done'):return
        from .shutdown import wait_for_index
        if wait_for_index(self):return
        # Tk's __getattr__ recurses into self.tk before the Tk interpreter has
        # been constructed (e.g. partial startup / shutdown-failure recovery).
        self.closing=True
        step(self,'ปิด medley',lambda:cleanup(self))
        panel=self.__dict__.get('_midi_keyboard_window')
        if panel and hasattr(panel,'_keyboard_stop_input'):step(self,'ปิด MIDI input',panel._keyboard_stop_input)
        voice=self.__dict__.get('_keyboard_voice')
        if voice:step(self,'ปิด keyboard voice',voice.close)
        step(self,'จบประวัติ',lambda:history_finish(self,'interrupted'))
        rack=self.__dict__.get('_fx_rack')
        if rack:step(self,'ปิด sound effects',rack.close)
        for name in ('_volume_sync_timer','_volume_osd_timer','_transport_timer'):
            timer=self.__dict__.get(name)
            if timer is not None:
                step(self,'หยุด '+name,lambda timer=timer:self.after_cancel(timer));setattr(self,name,None)
        volume=self.__dict__.get('system_volume')
        if volume:step(self,'ปิด system volume',volume.close)
        def stop_search():
            with self._search_condition:
                self._search_stopping=True;self._search_condition.notify_all()
            reader=self.__dict__.get('_active_reader')
            if reader is not None:
                import sqlite3
                try:reader.interrupt()
                except sqlite3.Error:pass
            worker=self.__dict__.get('_search_thread')
            if worker is not None and worker is not threading.current_thread():worker.join(timeout=1)
        step(self,'หยุด search worker',stop_search)
        super().close_app()

    def help(self):
        from tkinter import messagebox
        messagebox.showinfo('วิธีใช้ X-Stage Karaoke',
            'เปิดโปรแกรมแล้วเริ่มที่จอเล่นเพลง\n'
            'พิมพ์ชื่อ / ศิลปิน / รหัส / เนื้อร้อง → ↑ ↓ เลือก → Enter\n'
            'กำลังเล่น/พัก/หยุด หรือมีคิวรอ: เพิ่มเข้าคิว • ไม่มีเพลงและคิวว่าง: เล่นทันที • F7 ยกเลิกเพลงปัจจุบัน\n'
            '← → เลือกเพลงในคิว → Enter เล่นทันที • Ctrl+Enter เล่นผลค้นหาทันที\n'
            'Esc ปิดค้นหา • F5 เล่น/พัก • F6 ถัดไป • F8 หยุด\n'
            'Alt+↑ เพิ่มคีย์ / Alt+↓ ลดคีย์ (Insert/Delete สำรอง): เพลงที่เลือกหรือ MIDI ที่เล่น\n'
            'ล้อเมาส์บนจอเพลง: ปรับระดับเสียงครั้งละ 5%\n'
            'คลิกขวาเพื่อเปิดคิว ควบคุมเพลง ตั้งค่า และเครื่องมือทั้งหมด\n'
            'คลิกขวา → ระบบ 2 หน้าจอ → เปิดจอร้องแยก / เลือกจอ\n'
            'คลิกขวา → พื้นหลัง → ภาพเวที X-STAGE / ไม่มีรูป • ขยับเมาส์เพื่อแสดงแถบควบคุมย่อ\n'
            'เริ่มพิมพ์ได้ทันที ไม่ต้องกด F3 • F9 มิกเซอร์ • F10 คิว • F11 เต็มจอ', parent=self)
