"""Thai-language desktop UI. Tkinter and all other imports are standard library."""
from __future__ import annotations

import logging
import json
import os
import queue
import threading
import time
from .dialog_layout import DialogWindow
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import ttk, filedialog, messagebox, simpledialog

from . import __version__, DISPLAY_NAME
from .library import (SongLibrary, SongQueue, QueueItem, SearchCancelled, MIDI_EXT, VIDEO_EXT,
                      SUPPORTED, read_json, write_json, read_json_snapshot, JSON_UNSET, PlaylistImportError, scan_folder)
from .lyrics import Lyrics, parse_lrc, decode_text, sidecar_lyrics
from .playback import MidiPlayer, MediaPlayer, WavePlayer, WinMidi

BG = "#0b1120"
PANEL = "#141e30"
FIELD = "#1e2b42"
TEXT = "#edf3ff"
MUTED = "#94a5be"
TEAL = "#43e3bf"


def timestamp(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02}:{seconds % 60:02}"


def playback_lyrics(settings, path, lyrics, stored_path):
    sidecar = sidecar_lyrics(path)
    if sidecar:
        lyrics = sidecar
    overrides = settings.get("lyric_files", {})
    if isinstance(overrides, dict) and stored_path in overrides:
        lyric_path = Path(overrides[stored_path])
        if lyric_path.is_file():
            lyrics = parse_lrc(decode_text(lyric_path.read_bytes()))
    offsets = settings.get("offsets", {})
    return lyrics, offsets.get(stored_path, 0) if isinstance(offsets, dict) else 0


class LyricsCanvas(tk.Canvas):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg="#080e1a", highlightthickness=0, **kwargs)
        self.state = ("พร้อมร้องเพลง", "เพิ่มเพลงเข้าคิว แล้วกดเล่น", "", "X-Stage Karaoke")
        self.bind("<Configure>", lambda _: self.redraw())

    def show(self, current, upcoming, prefix="", title=""):
        state = (current, upcoming, prefix, title)
        if self.state != state:
            self.state = state
            self.redraw()

    def redraw(self):
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        if width < 10:
            return
        current, upcoming, prefix, title = self.state
        self.create_rectangle(0, 0, width, 4, fill=TEAL, outline="")
        self.create_text(24, 24, text=title[:100], anchor="nw", fill=MUTED,
                         font=("Leelawadee UI", 12), width=max(20, width - 48))
        font = tkfont.Font(family="Leelawadee UI", size=max(22, min(42, width // 20)), weight="bold")
        while font.measure(current) > width - 50 and font.cget("size") > 12:
            font.configure(size=font.cget("size") - 1)
        left = max(20, (width - font.measure(current)) / 2)
        middle = max(90, height * 0.5)
        self.create_text(left + 2, middle + 2, text=current, fill="#000000", font=font, anchor="w")
        self.create_text(left, middle, text=current, fill=TEXT, font=font, anchor="w")
        if prefix and current.startswith(prefix):
            self.create_text(left, middle, text=prefix, fill=TEAL, font=font, anchor="w")
        self.create_text(width / 2, middle + 65, text=upcoming, fill=MUTED,
                         font=("Leelawadee UI", 17), width=max(30, width - 60), justify="center")
        self.create_text(width - 20, height - 20, text="X-STAGE KARAOKE", anchor="se", fill="#30415d",
                         font=("Segoe UI", 10, "bold"))


class KaraokeApp(tk.Tk):
    canvas_class = LyricsCanvas
    def __init__(self, home: Path, data_dir: Path | None = None):
        super().__init__()
        self.home = Path(home)
        from .branding import install_window_icon
        install_window_icon(self)
        self.data_dir = Path(data_dir or home / "data")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.title(f"X-Stage Karaoke {__version__} — Python Karaoke")
        # Respect the actual Windows work area on compact, high-DPI and
        # secondary displays. Never force a default geometry larger than the
        # monitor before PlaybackApp switches to the stage.
        available_w = max(300, self.winfo_screenwidth())
        available_h = max(250, self.winfo_screenheight())
        self.geometry(f'{min(1400,available_w)}x{min(900,available_h)}')
        self.minsize(min(800,available_w), min(500,available_h))
        self.configure(bg=BG)
        self.option_add("*Font", "{Leelawadee UI} 10")
        self.settings_path = self.data_dir / "settings.json"
        self.settings, self._settings_revision = read_json_snapshot(self.settings_path, {})
        if not isinstance(self.settings, dict):
            self.settings = {}
        from .lister import migrate_locations
        migrate_locations(self.settings)
        if self.settings.get('lyric_layout_version', 0) < 1:
            try:
                size = int(self.settings.get('font_size', 84))
            except (TypeError, ValueError):
                size = 84
            self.settings.update(font_size=max(84, min(120, size)), lyric_layout_version=1)
        self.library = SongLibrary(self.data_dir / "songs.sqlite3")
        self.song_queue = SongQueue(self.data_dir / "queue.json")
        self.engine = None
        self.current_song = None
        self.current_item = None
        self.lyrics = Lyrics()
        self.stage = None
        self.stage_canvas = None
        self.stage_video = None
        self.stage_fullscreen = False
        self.messages = queue.Queue()
        self.cancel_scan = threading.Event()
        self.scanning = False
        self.closing = False
        self.last_paint = 0
        self.dragging = False
        self.search_after = None
        self._setup_style()
        self._build()
        self._bindings()
        if not self.library.has_songs():
            self.library.add_files(sorted((home / "samples").glob("*")))
        self.refresh_library()
        self.refresh_queue()
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self.tick_after = self.after(25, self.tick)

    def _setup_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=PANEL, foreground=TEXT, borderwidth=0, font=("Leelawadee UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("TButton", background=FIELD, foreground=TEXT, padding=(11, 8))
        style.map("TButton", background=[("active", "#2d4263"), ("disabled", PANEL)])
        style.configure("Accent.TButton", background=TEAL, foreground="#081823", font=("Leelawadee UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#85f2d7")])
        style.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, padding=8, insertcolor=TEXT)
        style.configure("TSpinbox", fieldbackground=FIELD, foreground=TEXT, padding=4, arrowcolor=TEXT)
        style.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=TEXT, padding=5, arrowcolor=TEXT)
        style.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)])
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=32,
                        borderwidth=0)
        style.map("Treeview", background=[("selected", "#244955")], foreground=[("selected", "#ffffff")])
        style.configure("Treeview.Heading", background=FIELD, foreground=MUTED, padding=8, relief="flat")
        style.configure("TCheckbutton", background=BG, foreground=TEXT)
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure("Horizontal.TScale", background=BG, troughcolor=FIELD)
        style.configure("TSeparator", background=FIELD)

    def _build(self):
        menu = tk.Menu(self)
        self.config(menu=menu)
        settings_menu = tk.Menu(menu, tearoff=False)
        menu.add_cascade(label="ตั้งค่า", menu=settings_menu)
        settings_menu.add_command(label="นโยบายความเป็นส่วนตัวของ X-Stage Karaoke", command=self.open_privacy_policy)
        outer = ttk.Frame(self, padding=(24, 18))
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 18))
        ttk.Label(header, text="X-Stage ", foreground=TEAL, font=("Segoe UI", 27, "bold")).pack(side="left")
        ttk.Label(header, text="Karaoke", font=("Segoe UI", 27, "bold")).pack(side="left")
        ttk.Label(header, text="  เวทีเพลงของคุณ", style="Muted.TLabel").pack(side="left", padx=12)
        ttk.Button(header, text="จอร้องเพลง  F11", command=self.toggle_stage).pack(side="right")
        ttk.Button(header, text="วิธีใช้", command=self.help).pack(side="right", padx=8)

        toolbar = ttk.Frame(outer)
        toolbar.pack(fill="x", pady=(0, 14))
        ttk.Button(toolbar, text="+ เพิ่มโฟลเดอร์เพลง", style="Accent.TButton", command=self.add_folder).pack(side="left")
        ttk.Button(toolbar, text="เพิ่มไฟล์", command=self.add_files).pack(side="left", padx=8)
        ttk.Button(toolbar, text="นำเข้าคิว", command=self.import_queue).pack(side="left")
        ttk.Button(toolbar, text="ส่งออกคิว", command=self.export_queue).pack(side="left", padx=8)
        self.song_count = tk.StringVar()
        ttk.Label(toolbar, textvariable=self.song_count, style="Muted.TLabel").pack(side="right")

        body = ttk.Panedwindow(outer, orient="horizontal")
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=5)
        body.add(right, weight=5)
        search_row = ttk.Frame(left)
        search_row.pack(fill="x", pady=(0, 10), padx=(0, 14))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_row, textvariable=self.search_var)
        self.search_entry.pack(fill="x", side="left", expand=True)
        self.search_entry.insert(0, "")
        self.search_var.trace_add("write", self.schedule_search)
        self.favorite_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(search_row, text="เพลงโปรด", variable=self.favorite_var, command=self.refresh_library).pack(side="left", padx=8)
        ttk.Label(left, text="ค้นหาชื่อเพลง • ศิลปิน • รหัสเพลง  |  Enter เพิ่มคิว / ดับเบิลคลิกเพิ่มคิว",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        table_wrap = ttk.Frame(left)
        table_wrap.pack(fill="both", expand=True, padx=(0, 14))
        self.songs = ttk.Treeview(table_wrap, columns=("code", "title", "artist", "kind"), show="headings", selectmode="extended")
        for name, label, width in (("code", "รหัส", 65), ("title", "ชื่อเพลง", 230), ("artist", "ศิลปิน", 140), ("kind", "ชนิด", 65)):
            self.songs.heading(name, text=label)
            self.songs.column(name, width=width, minwidth=45, stretch=name in ("title", "artist"))
        scrollbar = ttk.Scrollbar(table_wrap, orient="vertical", command=self.songs.yview)
        self.songs.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.songs.pack(fill="both", expand=True)
        self.songs.bind("<Double-1>", lambda _: self.add_selected())
        self.songs.bind("<Return>", lambda _: self.add_selected())
        actions = ttk.Frame(left)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="+ เข้าคิว", style="Accent.TButton", command=self.add_selected).pack(side="left")
        ttk.Button(actions, text="เล่นทันที", command=self.play_selected).pack(side="left", padx=6)
        ttk.Button(actions, text="โปรด ★", command=self.favorite_selected).pack(side="left")
        ttk.Button(actions, text="แก้ชื่อ", command=self.edit_song).pack(side="left", padx=6)

        self.now_var = tk.StringVar(value="ยังไม่ได้เลือกเพลง")
        ttk.Label(right, textvariable=self.now_var, font=("Leelawadee UI", 13, "bold")).pack(anchor="w", pady=(0, 8))
        self.preview = self.canvas_class(right, height=240)
        self.preview.pack(fill="x")
        self.video_frame = tk.Frame(right, bg="black", height=240)
        self.video_frame.bind("<Configure>", lambda _: self.resize_video())
        line = ttk.Frame(right)
        self.lyric_controls = line
        line.pack(fill="x", pady=8)
        ttk.Button(line, text="เนื้อร้อง .lrc", command=self.choose_lyrics).pack(side="left")
        ttk.Label(line, text="ชดเชยเนื้อร้อง (ms)", style="Muted.TLabel").pack(side="left", padx=8)
        self.offset_var = tk.IntVar(value=0)
        ttk.Spinbox(line, from_=-10000, to=10000, increment=100, width=7, textvariable=self.offset_var,
                    command=self.save_offset).pack(side="left")
        ttk.Button(line, text="บันทึก", command=self.save_offset).pack(side="left", padx=5)

        queue_heading = ttk.Frame(right)
        queue_heading.pack(fill="x", pady=(4, 6))
        self.queue_title = tk.StringVar(value="คิวเพลง")
        ttk.Label(queue_heading, textvariable=self.queue_title, font=("Leelawadee UI", 12, "bold")).pack(side="left")
        self.auto_var = tk.BooleanVar(value=bool(self.settings.get("auto_next", True)))
        ttk.Checkbutton(queue_heading, text="เล่นต่ออัตโนมัติ", variable=self.auto_var).pack(side="right")
        self.queues = ttk.Treeview(right, columns=("number", "title", "singer", "setting"), show="headings", height=5)
        for name, label, width in (("number", "#", 36), ("title", "เพลง", 210), ("singer", "ผู้ร้อง", 110), ("setting", "คีย์ / เร็ว", 110)):
            self.queues.heading(name, text=label)
            self.queues.column(name, width=width, minwidth=30, stretch=name in ("title", "singer"))
        self.queues.pack(fill="both", expand=True)
        self.queues.bind("<Double-1>", lambda _: self.edit_queue())
        queue_actions = ttk.Frame(right)
        queue_actions.pack(fill="x", pady=(8, 0))
        ttk.Button(queue_actions, text="▲", width=3, command=lambda: self.move_queue(-1)).pack(side="left")
        ttk.Button(queue_actions, text="▼", width=3, command=lambda: self.move_queue(1)).pack(side="left", padx=4)
        ttk.Button(queue_actions, text="ลบคิว", command=self.remove_queue).pack(side="left")
        ttk.Button(queue_actions, text="แก้คิว", command=self.edit_queue).pack(side="left", padx=4)
        ttk.Button(queue_actions, text="เล่นคิวนี้", command=self.play_queue_selected).pack(side="left")
        ttk.Button(queue_actions, text="มิกเซอร์ MIDI", command=self.open_mixer).pack(side="right")

        ttk.Separator(outer).pack(fill="x", pady=14)
        progress_row = ttk.Frame(outer)
        progress_row.pack(fill="x")
        self.time_var = tk.StringVar(value="00:00 / 00:00")
        ttk.Label(progress_row, textvariable=self.time_var, width=16, style="Muted.TLabel").pack(side="left")
        self.seek_var = tk.DoubleVar(value=0)
        self.seek = ttk.Scale(progress_row, variable=self.seek_var, from_=0, to=1)
        self.seek.pack(side="left", fill="x", expand=True)
        self.seek.bind("<ButtonPress-1>", lambda _: setattr(self, "dragging", True))
        self.seek.bind("<ButtonRelease-1>", self.seek_release)
        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(10, 0))
        self.play_button = ttk.Button(controls, text="▶ เล่น / พัก", style="Accent.TButton", command=self.play_pause)
        self.play_button.pack(side="left")
        ttk.Button(controls, text="■ หยุด", command=self.stop).pack(side="left", padx=6)
        ttk.Button(controls, text="เพลงถัดไป", command=self.next_song).pack(side="left")
        ttk.Label(controls, text="คีย์ MIDI", style="Muted.TLabel").pack(side="left", padx=(16, 5))
        self.key_var = tk.IntVar(value=0)
        self.key_box = ttk.Spinbox(controls, from_=-12, to=12, width=4, textvariable=self.key_var, command=self.apply_key)
        self.key_box.pack(side="left")
        self.key_box.bind("<Return>", lambda _: self.apply_key())
        self.key_box.bind("<FocusOut>", lambda _: self.apply_key())
        ttk.Label(controls, text="เร็ว %", style="Muted.TLabel").pack(side="left", padx=(12, 5))
        self.speed_var = tk.IntVar(value=100)
        self.speed_box = ttk.Spinbox(controls, from_=50, to=150, increment=5, width=5,
                                     textvariable=self.speed_var, command=self.apply_speed)
        self.speed_box.pack(side="left")
        self.speed_box.bind("<Return>", lambda _: self.apply_speed())
        self.speed_box.bind("<FocusOut>", lambda _: self.apply_speed())
        ttk.Label(controls, text="เสียง", style="Muted.TLabel").pack(side="left", padx=(15, 5))
        self.volume_var = tk.DoubleVar(value=float(self.settings.get("volume", 75)))
        ttk.Scale(controls, from_=0, to=100, length=140, variable=self.volume_var, command=self.apply_volume).pack(side="left")
        self.melody_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text="ปิดไกด์ MIDI Ch4", variable=self.melody_var, command=self.apply_melody).pack(side="left", padx=12)
        self.status_var = tk.StringVar(value="พร้อมใช้งาน • มีเพลงทดสอบในคลัง • กด Ctrl+F เพื่อค้นหา")
        ttk.Label(outer, textvariable=self.status_var, style="Muted.TLabel", wraplength=1250).pack(anchor="w", pady=(12, 0))

    def open_privacy_policy(self):
        webbrowser.open("https://webbase-x.github.io/xstage/privacy.html")

    def _bindings(self):
        self.bind("<Control-f>", lambda _: (self.search_entry.focus_set(), self.search_entry.selection_range(0, "end")))
        self.bind("<F11>", lambda _: self.toggle_stage())
        self.bind("<F5>", lambda _: self.play_pause())
        self.bind("<F6>", lambda _: self.next_song())
        self.bind("<F8>", lambda _: self.stop())

    def schedule_search(self, *_):
        if self.search_after:
            self.after_cancel(self.search_after)
        self.search_after = self.after(180, self.refresh_library)

    def refresh_library(self):
        self.search_after = None
        selected = set(self.songs.selection())
        self.songs.delete(*self.songs.get_children())
        for song in self.library.search(self.search_var.get(), self.favorite_var.get()):
            title = ("★ " if song["favorite"] else "") + song["title"]
            iid = str(song["id"])
            self.songs.insert("", "end", iid=iid, values=(song["code"], title, song["artist"], song["kind"]))
            if iid in selected:
                self.songs.selection_add(iid)
        count = self.library.count()
        shown = len(self.songs.get_children())
        self.song_count.set(f"คลัง {count:,} เพลง  •  แสดง {shown:,}" + (" (สูงสุด 3,000)" if shown >= 3000 else ""))

    def refresh_queue(self, select=None):
        if select is None:
            previous = self.queues.selection()
            select = int(previous[0]) if previous else 0
        select = min(select, len(self.song_queue.items)-1) if self.song_queue.items else None
        self.queues.delete(*self.queues.get_children())
        for index, item in enumerate(self.song_queue.items):
            song = self.library.get(item.song_id)
            self.queues.insert("", "end", iid=str(index), values=(index + 1, song["title"] if song else "ไม่พบเพลง",
                                  item.singer, f"{item.key:+} / {item.speed}%"))
        self.queue_title.set(f"คิวเพลง  ·  {len(self.song_queue.items)}")
        if select is not None and self.queues.exists(str(select)):
            self.queues.selection_set(str(select))
            self.queues.focus(str(select))
            self.queues.see(str(select))

    def add_files(self):
        if self.scanning:
            return self.status_var.set('กำลังตรวจรายการเพลง กรุณารอหรือยกเลิกงานเดิม')
        paths = filedialog.askopenfilenames(parent=self, title="เพิ่มเพลง", filetypes=[("เพลงและวิดีโอ", " ".join("*" + ext for ext in sorted(SUPPORTED))), ("ไฟล์ทั้งหมด", "*.*")])
        if paths:
            from .import_ui import choose_copy,options
            copy_files=choose_copy(self)
            if copy_files is None:return
            import_options=options(self,copy_files)
            def work():
                from .index_plan import SongPlan
                with SongPlan() as plan:
                    self.job_event(dict(type='phase',phase='นับไฟล์ที่เลือก',total=None))
                    for path in paths:
                        if self.cancel_scan.is_set():break
                        plan.add(path)
                    from .managed_import import run_plan
                    return run_plan(self.library,plan,self.cancel_scan,self.job_event,single=len(paths)==1,**import_options)
            self.start_index_job(work)

    def index_protected_ids(self):
        result={item.song_id for item in self.song_queue.items}
        if self.current_song:result.add(self.current_song['id'])
        return result

    def managed_catalog_root(self):
        return Path(self.data_dir).parent / 'Songs'

    def show_catalog_maintenance(self):
        from .catalog_window import CatalogWindow

        window = getattr(self, 'catalog_window', None)
        if window is None or not window.window.winfo_exists():
            self.catalog_window = CatalogWindow(self)
        else:
            window.show()

    def start_catalog_maintenance(self, source, mode, copy_external=False, *,
                                  duplicate_policy='review', auto_shutdown=False):
        from .catalog_maintenance import maintain_catalog
        from .fast_catalog import build_fast_catalog

        if self.scanning or getattr(self, '_cleanup_busy', False):
            self.catalog_window.finish(error='กรุณารอให้งานสร้างรายการเพลงเดิมเสร็จก่อน')
            return False
        if mode in {'rebuild', 'safe_rebuild', 'clear'} and self.engine:
            self.catalog_window.finish(error='กรุณาหยุดเพลงก่อนล้างหรือสร้างรายการใหม่')
            return False

        self.scanning = True
        self._catalog_auto_shutdown_requested = bool(auto_shutdown and mode in ('fast', 'full', 'safe_rebuild'))
        self.cancel_scan.clear()
        protected = self.index_protected_ids()
        queue_ids = {item.song_id for item in self.song_queue.items}
        self.status_var.set('กำลังเตรียมสร้างรายการเพลง…')
        last_event = 0.0

        def report(event):
            nonlocal last_event
            now = time.monotonic()
            if event.get('type') == 'phase' or now - last_event >= 0.12:
                self.messages.put(('catalog_progress', event))
                last_event = now

        def worker():
            try:
                before = {}
                ids = list(queue_ids)
                with self.library.connect() as db:
                    for offset in range(0, len(ids), 500):
                        batch = ids[offset:offset + 500]
                        placeholders = ','.join('?' for _ in batch)
                        rows = db.execute(
                            'SELECT id,title,artist,key_signature FROM songs WHERE id IN (' + placeholders + ')',
                            batch)
                        before.update((row['id'], dict(row)) for row in rows)
                if mode in ('quick', 'fast', 'full', 'safe_rebuild'):
                    result = build_fast_catalog(
                        self.library, Path(source), self.managed_catalog_root(), mode,
                        copy_external=copy_external, duplicate_policy=duplicate_policy,
                        cancelled=self.cancel_scan, events=report, protected=protected,
                        strict_shutdown_check=bool(getattr(self, '_catalog_auto_shutdown_requested', False)))
                else:  # Old API remains for older jobs/tests; UI uses the new modes.
                    result = maintain_catalog(
                        self.library, Path(source), self.managed_catalog_root(), mode,
                        copy_external, cancelled=self.cancel_scan, events=report, protected=protected)
                self.messages.put(('catalog_finished', (result, None, before)))
            except SearchCancelled:
                self.messages.put(('catalog_finished', (None, None, {})))
            except Exception as error:
                logging.exception('CATALOG_MAINTENANCE_FAILED')
                self.messages.put(('catalog_finished', (None, str(error), {})))

        self._index_thread = threading.Thread(target=worker, daemon=True, name='catalog-maintenance')
        self._index_thread.start()
        return True

    def start_catalog_report_repair(self, duplicate_policy):
        from .fast_catalog import regenerate_catalog_reports
        self.scanning = True
        self._catalog_auto_shutdown_requested = False
        def worker():
            try:
                paths = regenerate_catalog_reports(self.library, duplicate_policy=duplicate_policy,
                                                   cancelled=self.cancel_scan)
                self.messages.put(('catalog_report_finished', (paths, None)))
            except SearchCancelled:
                self.messages.put(('catalog_report_finished', (None, None)))
            except Exception as error:
                logging.exception('CATALOG_REPORT_REPAIR_FAILED')
                self.messages.put(('catalog_report_finished', (None, str(error))))
        self._index_thread = threading.Thread(target=worker, daemon=True,
                                              name='catalog-report-repair')
        self._index_thread.start()

    def handle_catalog_message(self, kind, data):
        window = getattr(self, 'catalog_window', None)
        visible_window = window is not None and window.window.winfo_exists()
        if kind == 'catalog_progress':
            if visible_window:
                window.update_progress(data)
            return
        if kind == 'catalog_report_finished':
            paths, error = data
            self.scanning = False
            self._catalog_auto_shutdown_requested = False
            if visible_window:
                window.finish(result={'summary':'สร้างรายงานจากฐานที่บันทึกไว้แล้วครบ 4 ไฟล์'} if paths else None,
                              error=error, cancelled=paths is None and error is None)
                if paths:
                    window.duplicate_report_path = paths[0]
                    window.report_button.state(['!disabled'])
            self.status_var.set(error or ('สร้างรายงานใหม่แล้วโดยไม่สแกนเพลงซ้ำ' if paths else 'ยกเลิกสร้างรายงาน'))
            return
        result, error, before = data
        self.scanning = False
        cancelled = result is None and error is None
        if result is not None:
            try:
                self.reconcile_catalog_queue(before)
            except (ValueError, OSError) as queue_error:
                logging.exception('CATALOG_QUEUE_RECONCILIATION_FAILED')
                error = 'บันทึกรายการเพลงแล้ว แต่ปรับคิวเพลงไม่สำเร็จ: ' + str(queue_error)
            self.refresh_library()
            self.refresh_queue()
        if visible_window:
            window.finish(result=result, error=error, cancelled=cancelled)
        if error:
            self.status_var.set(error)
        elif cancelled:
            self.status_var.set('ยกเลิกการสร้างรายการเพลงแล้ว')
        else:
            self.status_var.set((result[2][1] if getattr(result, 'metrics', {}).get('post_commit_errors')
                                 else f'มีเพลงในรายการ {result[0]:,} เพลง · ข้าม {result[1]:,} รายการ'))
            if getattr(result, 'metrics', {}).get('reports_deferred') and visible_window:
                window.duplicate_report_path = None
                window.report_button.state(['disabled'])
            if getattr(result, 'duplicate_report', None) and visible_window:
                window.duplicate_report_path = result.duplicate_report
                window.report_button.state(['!disabled'])
            if getattr(self, '_catalog_auto_shutdown_requested', False) and getattr(result, 'safe_to_shutdown', False):
                from .auto_shutdown_dialog import maybe_schedule_shutdown
                maybe_schedule_shutdown(self, result)
        self._catalog_auto_shutdown_requested = False

    def reconcile_catalog_queue(self, before):
        from dataclasses import replace
        from .name_duplicates import identity

        missing = {song_id: row for song_id, row in before.items()
                   if row is not None and self.library.get(song_id) is None}
        if not missing:
            return
        wanted = {identity(row['title'], row['artist'], row['key_signature']) for row in missing.values()}
        wanted.discard(None)
        replacements = {}
        if wanted:
            with self.library.connect() as db:
                for row in db.execute("SELECT id,title,artist,key_signature FROM songs WHERE duplicate_of=0 AND duplicate_state NOT IN ('deleted','invalid','moved','recycled','missing','excluded')"):
                    key = identity(row['title'], row['artist'], row['key_signature'])
                    if key in wanted:
                        replacements[key] = row['id']
        pending = []
        for item in self.song_queue.items:
            row = missing.get(item.song_id)
            if row is None:
                pending.append(item)
            else:
                replacement = replacements.get(identity(row['title'], row['artist'], row['key_signature']))
                if replacement is not None:
                    pending.append(replace(item, song_id=replacement))
        if pending != self.song_queue.items:
            self.song_queue._commit(pending)

    def rebuild_library(self, force=False):
        from .lister import locations, build_list
        roots = locations(self.settings)
        if roots:
            from .import_ui import choose_copy,options
            copy_files=choose_copy(self)
            if copy_files is None:return
            import_options=options(self,copy_files)
            if not messagebox.askyesno('ตรวจทั้งคลังใหม่' if force else 'อัปเดตรายการเพลง',
                    (f'ตรวจทั้งคลังและอ่านข้อมูลใหม่จาก {len(roots)} แห่งหรือไม่?\n' if force else f'อัปเดตเฉพาะเพลงใหม่หรือที่เปลี่ยนจาก {len(roots)} แห่งหรือไม่?\n')
                    + 'รักษารายการเดิม คิว เพลงโปรด และข้อมูลที่แก้ไว้ โดยไม่ย้ายหรือลบไฟล์', parent=self):
                return
            self.start_index_job(lambda: build_list(self.library, roots,
                progress=lambda n: self.messages.put(('progress', n)), cancelled=self.cancel_scan, events=self.job_event, force=force, protected=self.index_protected_ids(), import_options=import_options))
        else:
            if not messagebox.askyesno('ยังไม่ได้กำหนดที่เก็บเพลง',
                    'ยังไม่มีโฟลเดอร์ที่กำหนด ต้องการอ่านรายละเอียดเฉพาะเพลงที่อยู่ในฐานข้อมูลเดิมหรือไม่?\n'
                    'หากต้องการค้นหาเพลงใหม่ ให้เพิ่มโฟลเดอร์ในหน้าสร้างรายการเพลงก่อน', parent=self):
                return
            self.start_index_job(lambda: self.library.rebuild(
                progress=lambda n: self.messages.put(('progress', n)), cancelled=self.cancel_scan, events=self.job_event, force=force, protected=self.index_protected_ids(), enforce_policy=True))

    def show_import_report(self):
        path = self.library.path.parent / 'import-report.txt'
        if not path.is_file():
            return messagebox.showinfo('รายงานตรวจเพลง', 'ยังไม่มีรายงานการเพิ่มเพลงหรือสร้างรายการใหม่', parent=self)
        window = DialogWindow(self)
        window.title('รายงานตรวจเพลง — รายละเอียดต้นทางที่อ่านไม่ได้')
        window.transient(self)
        window.lift()
        window.geometry('950x560')
        from tkinter.scrolledtext import ScrolledText
        text = ScrolledText(window.content, wrap='word', font=('Leelawadee UI', 12))
        text.pack(fill='both', expand=True)
        with path.open(encoding='utf-8') as stream:
            content = stream.read(200000)
            more = bool(stream.read(1))
        text.insert('end', content + ('\n… รายงานเต็ม: '+str(path) if more else ''))
        text.configure(state='disabled')

    def write_import_report(self, result):
        count, skipped, errors = result
        report = ('ยกเลิกงาน: เก็บรายการที่ตรวจเสร็จแล้ว' if self.cancel_scan.is_set() else 'ตรวจเพลงเสร็จ')
        report += f'\nอ่านได้ {count:,} · ข้าม/ซ้ำ/ยังไม่รองรับ {skipped:,} · ข้อสังเกต {len(errors):,}\n'
        reporter = getattr(self, 'job_reporter', None)
        if reporter:
            state = reporter.state
            report += f"เริ่ม: {reporter.started_at}\nใช้เวลา: {time.monotonic()-reporter.started:.2f} วินาที\n"
            report += f"เป้าหมาย {state.get('target',0):,} · ตรวจแล้ว {state.get('processed',0):,} · อ่านได้ {state.get('accepted',0):,} · ข้าม {state.get('rejected',0)+state.get('unsupported',0):,} · ซ้ำ {state.get('duplicates',0):,}\n"
            if state.get('incremental'):
                report += f"เดิมไม่เปลี่ยน {state.get('unchanged',0):,} · เพิ่มใหม่ {state.get('added',0):,} · อัปเดต {state.get('updated',0):,} · ซ้ำในรอบนี้ {state.get('duplicates',0):,} · อ่านไม่ได้ {state.get('failed',0):,}\n"
            if reporter.log_path.is_file():
                report += 'รายการทั้งหมด: '+str(reporter.log_path)+'\n'
        path = self.library.path.parent / 'import-report.txt'
        temp = path.with_suffix('.tmp')
        temp.write_text(report+'\n'.join(errors), encoding='utf-8')
        temp.replace(path)

    def begin_job(self, title='นำเข้าและสร้างรายการเพลง'):
        from .jobs import JobReporter
        self.job_reporter = JobReporter(self.messages, self.data_dir, title)
        self.show_job_progress()
        self.job_window.reset_job()
        self.job_reporter.emit(force=True)
        return self.job_reporter

    def show_job_progress(self):
        from .job_dialog import JobWindow
        window = getattr(self, 'job_window', None)
        if window is None or not window.window.winfo_exists():
            self.job_window = JobWindow(self)
            reporter = getattr(self, 'job_reporter', None)
            if reporter:
                self.job_window.update(dict(state=dict(reporter.state), rows=[]))
        else:
            window.show()

    def job_event(self, event):
        reporter = getattr(self, 'job_reporter', None)
        if reporter:
            reporter.event(event)

    def handle_job_progress(self, data):
        window = getattr(self, 'job_window', None)
        if window is not None and window.window.winfo_exists():
            window.update(data)

    def start_index_job(self, operation, deduplicate=False, on_done=None):
        if self.scanning:
            return self.status_var.set('กำลังตรวจรายการเพลง กรุณารอหรือยกเลิกงานเดิม')
        self.scanning = True
        self.cancel_scan.clear()
        self.status_var.set('กำลังนับจำนวนเพลงและเตรียมเป้าหมาย…')
        reporter = self.begin_job()
        protected = {item.song_id for item in self.song_queue.items}
        if self.current_song:
            protected.add(self.current_song['id'])
        def worker():
            try:
                result = operation()
                note = ''
                if reporter.state.get('incremental'):
                    state=reporter.state
                    note=f"เสร็จแล้ว · เดิมไม่เปลี่ยน {state.get('unchanged',0):,} · เพิ่มใหม่ {state.get('added',0):,} · อัปเดต {state.get('updated',0):,} · ซ้ำ {state.get('duplicates',0):,} · อ่านไม่ได้ {state.get('failed',0):,}"
                elif not deduplicate and result[2]:
                    note=result[2][0]
                if deduplicate and not self.cancel_scan.is_set():
                    from .duplicates import scan
                    found, warnings = scan(self.library, protected, self.cancel_scan,
                        lambda n: self.messages.put(('progress', n)), events=self.job_event,
                        verify_only=True)
                    count = sum(len(group)-1 for group in found) if found is not None else 0
                    note = f'ตรวจเสร็จ · พบเพลงซ้ำ {count} รายการ · ยังไม่ได้ซ่อนหรือลบไฟล์' if found is not None else 'ยกเลิกการตรวจเพลงซ้ำแล้ว'
                    result = (result[0], result[1], list(result[2]) +
                              [f'เพลงซ้ำที่ตรวจได้ {count} รายการ (รายงานอย่างเดียว)'] + warnings)
                if reporter.log_path.is_file():
                    result = (result[0], result[1], list(result[2])+['รายงานรายการทั้งหมด: '+str(reporter.log_path)])
                self.write_import_report(result)
                reporter.finish(cancelled=self.cancel_scan.is_set())
                self.messages.put(('scan_done', result))
                if note:
                    self.messages.put(('job_note', note))
                if on_done:on_done(result)
            except Exception as error:
                try:
                    reporter.finish(cancelled=self.cancel_scan.is_set(),error=str(error))
                    self.write_import_report((reporter.state.get('accepted',0), reporter.state.get('rejected',0), ['งานหยุดเพราะ: '+str(error)]))
                finally:
                    self.messages.put(('scan_error', str(error)))
        self._index_thread=threading.Thread(target=worker,daemon=True,name='song-index')
        self._index_thread.start()

    def add_folder(self):
        from .lister import locations
        manager = getattr(self, 'song_manager', None)
        parent = manager if manager is not None and manager.winfo_exists() else self
        folder = filedialog.askdirectory(parent=parent, mustexist=True,
            title='กำหนดที่เก็บเพลง — NCN ให้เลือกโฟลเดอร์ที่มี Song, Lyrics, Cursor')
        if not folder:
            return
        roots = locations(self.settings)
        kind_var = getattr(self, 'song_folder_type', None)
        kind = kind_var.get() if kind_var else 'ทุกประเภท'
        roots.append({'path': folder, 'type': kind})
        self.settings['song_folders'] = roots
        self.settings['song_folders'] = locations(self.settings)
        self.save_settings()
        self.status_var.set('บันทึกที่เก็บเพลงแล้ว — กดเริ่มสร้างรายการเพื่ออัปเดตเพลงใหม่ / ที่เปลี่ยน')

    def start_scan(self, folder):
        from .lister import build_list
        from .import_ui import options
        policy=options(self,False)
        self.start_index_job(lambda:build_list(self.library,[{'path':str(folder),'type':'ทุกประเภท'}],cancelled=self.cancel_scan,events=self.job_event,protected=self.index_protected_ids(),import_options=policy))

    def add_selected(self):
        selection = self.songs.selection()
        for iid in selection:
            self.song_queue.add(QueueItem(int(iid)))
        self.refresh_queue()
        self.status_var.set(f"เพิ่มคิวแล้ว {len(selection)} เพลง")
        return "break"

    def favorite_selected(self):
        if getattr(self,'scanning',False):return self.status_var.set('กำลังตรวจรายการเพลง กรุณารอให้งานเสร็จก่อนแก้ข้อมูล')
        for iid in self.songs.selection():
            self.library.favorite(int(iid))
        self.refresh_library()

    def edit_song(self):
        if getattr(self,'scanning',False):return self.status_var.set('กำลังตรวจรายการเพลง กรุณารอให้งานเสร็จก่อนแก้ข้อมูล')
        selection = self.songs.selection()
        if not selection:
            return
        song = self.library.get(int(selection[0]))
        values = self.edit_dialog("แก้ข้อมูลเพลง", [("รหัส", song["code"]), ("ชื่อเพลง", song["title"]), ("ศิลปิน", song["artist"]),("คีย์ เช่น C, Am",song.get("key_signature",""))])
        if values and values[1].strip():
            self.library.edit(song["id"], *values)
            self.refresh_library()
            self.refresh_queue()

    def edit_dialog(self, title, fields):
        dialog = DialogWindow(self)
        dialog.title(title)
        dialog.configure(bg=BG)
        dialog.transient(self)
        variables = []
        for row, (name, value) in enumerate(fields):
            ttk.Label(dialog.content, text=name).grid(row=row, column=0, sticky="w", padx=16, pady=10)
            variable = tk.StringVar(value=str(value))
            ttk.Entry(dialog.content, textvariable=variable, width=40).grid(row=row, column=1, padx=16, pady=10)
            variables.append(variable)
        result = []
        def submit():
            result.extend(variable.get() for variable in variables)
            dialog.destroy()
        ttk.Button(dialog.content, text="บันทึก", style="Accent.TButton", command=submit).grid(row=len(fields), column=1, sticky="e", padx=16, pady=16)
        dialog.bind("<Return>", lambda _: submit())
        dialog.bind("<Escape>", lambda _: dialog.destroy())
        dialog.grab_set()
        self.wait_window(dialog)
        return result or None

    def queue_index(self):
        selection = self.queues.selection()
        return int(selection[0]) if selection else None

    def move_queue(self, step):
        index = self.queue_index()
        if index is not None:
            self.refresh_queue(self.song_queue.move(index, step))

    def remove_queue(self):
        index = self.queue_index()
        if index is not None:
            self.song_queue.pop(index)
            self.refresh_queue(min(index, len(self.song_queue.items) - 1))

    def edit_queue(self):
        index = self.queue_index()
        if index is None:
            return
        item = self.song_queue.items[index]
        values = self.edit_dialog("ตั้งค่าคิวเพลง", [("ผู้ร้อง", item.singer), ("คีย์ MIDI (-12 ถึง 12)", item.key), ("ความเร็ว % (50 ถึง 150)", item.speed)])
        if values:
            try:
                value = QueueItem.from_dict(dict(song_id=item.song_id, singer=values[0], key=values[1],
                                                 speed=values[2], request_id=item.request_id,
                                                 medley_session=item.medley_session))
                from .library import song_supports_key
                if value.key and not song_supports_key(self.library.get(item.song_id)):
                    raise ValueError('เพลงนี้ไม่รองรับปรับคีย์')
                self.song_queue.items[index] = value
                self.song_queue.save()
                self.refresh_queue(index)
            except ValueError as error:
                messagebox.showerror("ข้อมูลไม่ถูกต้อง", str(error), parent=self)

    def export_queue(self):
        path = filedialog.asksaveasfilename(title="ส่งออกคิว", defaultextension=".json", filetypes=[("X-Stage Karaoke playlist", "*.json")])
        if path:
            try:
                self.song_queue.export(path, self.library)
                self.status_var.set("ส่งออกคิวแล้ว (ไม่รวมไฟล์เพลง)")
            except OSError as error:
                self.show_error(error)

    def import_queue(self):
        if self.scanning:return self.status_var.set('กำลังตรวจรายการเพลง กรุณารอให้เสร็จ')
        path=filedialog.askopenfilename(title='นำเข้าคิว',filetypes=[('X-Stage Karaoke playlist','*.json')])
        if not path:return
        payload=[]
        def work():
            errors=[]
            pending,missing=self.song_queue.import_file(path,self.library,errors,enforce_policy=True,prepare_only=True,cancelled=self.cancel_scan,events=self.job_event)
            payload.append((pending,missing,errors))
            return len(pending),missing,errors
        self.start_index_job(work,on_done=lambda result:self.messages.put(('playlist_ready',payload[0])))

    def play_selected(self):
        selection = self.songs.selection()
        if selection:
            self.start_song(QueueItem(int(selection[0])))

    def play_queue_selected(self):
        index = self.queue_index()
        if index is not None:
            self.next_song(index)

    def next_song(self, index=0):
        if getattr(self,'_cleanup_busy',False):return self.status_var.set('กำลังลบเพลงตามรายงาน กรุณารอให้งานเสร็จ')
        skipped = 0
        self.queue_skip_report = []
        while self.song_queue.items:
            index = min(max(0, index), len(self.song_queue.items)-1)
            item = self.song_queue.items[index]
            self.last_load_error = ''
            self.last_load_error_kind = 'system'
            try:
                started = self.start_song(item, quiet=True)
            except Exception as error:
                logging.exception('Queued playback failed')
                self.last_load_error = str(error)
                started = False
            if not started and self.last_load_error_kind != 'file':
                reason = self.last_load_error or 'ระบบเสียงยังไม่พร้อม'
                logging.error('Queue preserved after playback system failure: %s', reason)
                self.cancel_current_song(advance=False)
                self.status_var.set('หยุดเพื่อรักษาคิว • '+reason+' • ตรวจระบบเสียงแล้วกดเล่นใหม่')
                return
            self.song_queue.pop(index)
            self.refresh_queue()
            if started:
                if skipped:
                    self.status_var.set(self.status_var.get()+f' • ข้าม {skipped} เพลงที่เปิดไม่ได้ (ดูบันทึกโปรแกรม)')
                return
            skipped += 1
            song = self.library.get(item.song_id)
            title = song['title'] if song else str(item.song_id)
            reason = self.last_load_error or 'เปิดเพลงไม่สำเร็จ'
            self.queue_skip_report.append({'song_id': item.song_id, 'title': title, 'reason': reason})
            logging.warning('Queue skipped: id=%s title=%s reason=%s', item.song_id, title, reason)
        self.on_song_ended()
        self.status_var.set(f'คิวว่าง • ข้าม {skipped} เพลงที่เปิดไม่ได้ (ดูบันทึกโปรแกรม)' if skipped else 'คิวเพลงว่างแล้ว')

    def on_song_ended(self):
        """Finish at a clean idle stage, or honor the user's auto-next choice."""
        if self.song_queue.items:
            if self.auto_var.get():
                self.next_song()
            else:
                self.status_var.set('จบเพลงแล้ว • มีเพลงรอในคิว')
            return
        engine, self.engine = self.engine, None
        if engine:
            try: engine.close()
            except OSError: logging.exception('Cannot close completed song')
        self.current_song = self.current_item = None
        self.lyrics = Lyrics()
        self.now_var.set('')
        self.time_var.set('00:00 / 00:00')
        self.seek_var.set(0)
        self.seek.configure(to=1)
        self.show_main_media(False)
        self.update_stage_mode()
        self.status_var.set('จบเพลงแล้ว • คิวว่าง')
        self.paint_lyrics()

    def report_load_error(self, error, quiet=False, kind='system'):
        self.last_load_error_kind = kind
        self.last_load_error = str(error)
        if not quiet:
            self.show_error(error)

    def start_song(self, item, quiet=False):
        if getattr(self,'_cleanup_busy',False):
            self.status_var.set('กำลังลบเพลงตามรายงาน กรุณารอให้งานเสร็จก่อนเล่นเพลง')
            return False
        from .transition_report import record
        record(self,'start_requested',song_id=item.song_id,key=item.key,speed=item.speed)
        if getattr(self,'_audio_probe_busy',False):
            self.report_load_error('กำลังทดสอบระบบเสียง กรุณารอ',quiet,kind='system')
            return False
        song = self.library.get(item.song_id)
        if not song or not Path(song["path"]).is_file():
            self.report_load_error("ไม่พบไฟล์เพลง อาจถูกย้ายหรือถอดไดรฟ์ออก", quiet, kind='file')
            return False
        prepared=None;old_overlap=None;rhythm=None
        decks=self.__dict__.get('_medley_decks')
        if (self.__dict__.get('_medley_overlap') or self.__dict__.get('_medley_prepared')) and decks:prepared=decks.take(item,self)
        if prepared:old_overlap=self.engine;self.engine=None
        new_engine = None
        phase = 'system'
        try:
            if self.engine:
                self.engine.close()
                self.engine = None
            self.current_song = None
            self.current_item = None
            self.lyrics = Lyrics()
            self.show_main_media(False)
            path = Path(song["path"])
            video = path.suffix.lower() in VIDEO_EXT
            if path.suffix.lower() in MIDI_EXT:
                output = None
                if not prepared and self.settings.get('synth_backend') == 'bass':
                    from .bass import BassSynth
                    output = BassSynth(self.home / 'native' / 'x64', settings=self.settings)
                new_engine = prepared[0] if prepared else MidiPlayer(output=output, device=int(self.settings.get("midi_device", -1)))
                phase = 'file'
                if not prepared:new_engine.load(path)
                phase = 'system'
                lyrics = new_engine.song.lyrics
                new_engine.set_key(item.key)
                new_engine.set_channel(3, muted=self.melody_var.get())
                self.key_box.configure(state="normal")
            else:
                from .pcm_player import PcmPlayer,available
                use_pcm=not video and path.suffix.lower() in ('.wav','.mp3') and available(self.home/'native'/'x64')
                new_engine = prepared[0] if prepared else PcmPlayer(self.home/'native'/'x64') if use_pcm else WavePlayer() if path.suffix.lower() == ".wav" else MediaPlayer()
                if video:
                    self.show_main_media(True)
                    self.update_idletasks()
                handle = self.stage_video.winfo_id() if video and self.stage and self.stage.winfo_exists() else self.video_frame.winfo_id()
                phase = 'file'
                if not prepared:new_engine.load(path, handle, video)
                phase = 'system'
                lyrics = Lyrics()
                if use_pcm:
                    new_engine.set_key(item.key);self.key_box.configure(state="normal")
                else:
                    item.key = 0;self.key_box.configure(state="disabled")
            lyrics, offset = playback_lyrics(self.settings, path, lyrics, song["path"])
            try:
                new_engine.set_speed(item.speed / 100)
            except OSError as error:
                logging.warning("Media speed unsupported: %s", error)
                item.speed = 100
            try:
                new_engine.set_volume(1.0 if getattr(self, 'system_volume', None) is not None else self.volume_var.get() / 100)
            except OSError as error:
                logging.warning("Media volume unsupported: %s", error)
                self.status_var.set("สื่อนี้ไม่รองรับปรับระดับเสียงในโปรแกรม ให้ใช้เสียงของ Windows")
            from .equalizer import output_for,apply as apply_eq
            from .first_run import hardware_changed
            if output_for(new_engine) and self.settings.get('eq_scope')!='windows' and not getattr(self,'_audio_setup_needs_device',False) and not hardware_changed(getattr(self,'data_dir',None)):
                try:
                    from .song_eq import remembered,selected
                    if 'graphic_eq' in self.settings or remembered(self.settings,song) is not None:
                        from .parametric_eq import apply as apply_graphic
                        apply_graphic(new_engine,selected(self.settings,song))
                    elif 'parametric_eq' in self.settings:
                        from .parametric_eq import apply as apply_parametric
                        apply_parametric(new_engine,self.settings['parametric_eq'])
                    else:
                        gains=self.settings.get('output_eq',[0,0,0])
                        if any(gains):apply_eq(new_engine,gains)
                except (TypeError,ValueError,OSError) as error:
                    logging.warning('EQ bypassed: %s',error)
            self.engine, self.current_song, self.current_item = new_engine, song, item
            eq_window=self.__dict__.get('_eq_window') or self.__dict__.get('_graphic_eq_window')
            if eq_window is not None and eq_window.winfo_exists():eq_window.sync_song()
            self.lyrics = lyrics
            self.key_var.set(item.key)
            self.speed_var.set(item.speed)
            self.offset_var.set(offset)
            self.now_var.set(song["title"] + (f"  ·  {item.singer}" if item.singer else ""))
            self.seek.configure(to=max(1, new_engine.duration))
            self.update_stage_mode()
            from .medley import options as medley_options
            from .medley_full import session, start_at_trimmed_edge, source_bounds
            medley=medley_options(self.settings)
            if session(item):
                if not prepared:
                    scan_tail = path.suffix.lower() != '.mp3'
                    new_engine.medley_bounds = source_bounds(new_engine, path, scan_tail=scan_tail)
                    if not scan_tail and new_engine.medley_bounds is not None:
                        new_engine.medley_tail_path = path
                start = start_at_trimmed_edge(new_engine, lyrics, offset)
                if start:
                    record(self, 'medley_head_trim', song_id=item.song_id, seconds=round(start, 3))
            elif medley['enabled'] and medley['fade']:
                new_engine.set_volume(0)
            new_engine.play()
            record(self,'started',song_id=item.song_id,prepared=bool(prepared),overlap=bool(self.__dict__.get('_medley_overlap')),duration=new_engine.duration,engine=type(new_engine).__name__)
            if prepared:
                if self.__dict__.get('_medley_overlap'):
                    decks.attach(old_overlap,prepared[1],self,medley["fade"])
                else:
                    decks.stop_tail()
                    if old_overlap:old_overlap.close()
                    if prepared[1]:prepared[1].close()
                old_overlap=None
            self.resize_video()
            self.status_var.set(f"กำลังเล่น {song['title']}" + (" • ไม่มีเนื้อร้องแบบจับเวลา" if not lyrics.lines and not video else ""))
            return True
        except Exception as error:
            record(self,'start_failed',song_id=item.song_id,error=str(error),phase=phase)
            logging.exception("Cannot load song")
            if old_overlap:old_overlap.close()
            if prepared and prepared[1]:prepared[1].close()
            if new_engine:
                new_engine.close()
            self.engine = None
            self.now_var.set("เปิดเพลงไม่สำเร็จ")
            self.show_main_media(False)
            self.update_stage_mode()
            self.current_song = self.current_item = None
            self.lyrics = Lyrics()
            kind = 'file' if phase == 'file' and isinstance(error, (ValueError, EOFError)) else 'system'
            self.report_load_error(error, quiet, kind=kind)
            return False

    def show_main_media(self, video):
        """Switch the main surface; layouts can choose their own sizing."""
        self.preview.pack_forget()
        self.video_frame.pack_forget()
        widget = self.video_frame if video else self.preview
        widget.pack(fill="x", before=self.lyric_controls)

    def play_pause(self):
        from .medley import toggle_random_fill
        if toggle_random_fill(self):
            return
        if not self.engine:
            if self.song_queue.items:
                self.next_song()
            else:
                self.play_selected()
            return
        try:
            if self.engine.playing:
                self.engine.pause()
                self.status_var.set("พักเพลง")
            else:
                self.engine.play()
                self.status_var.set("กำลังเล่น")
        except OSError as error:
            self.show_error(error)

    def stop(self):
        from .medley import cancel_random_fill
        from .queue_countdown import cancel_countdown
        cancel_random_fill(self)
        cancel_countdown(self)
        if self.engine:
            try:
                self.engine.stop()
                from .medley_full import session, start_at_trimmed_edge
                if session(getattr(self, 'current_item', None)):
                    start_at_trimmed_edge(self.engine, self.lyrics, self.offset_var.get())
            except OSError as error:
                self.show_error(error)
        self.status_var.set("หยุดเพลง • กดเล่นเพื่อเริ่มเพลงเดิมอีกครั้ง")

    def seek_release(self, _=None):
        from .medley import cancel_random_fill
        cancel_random_fill(self)
        self.dragging = False
        if self.engine:
            try:
                self.engine.seek(self.seek_var.get())
            except OSError as error:
                self.show_error(error)

    def apply_key(self):
        if not (isinstance(self.engine,MidiPlayer) or getattr(self.engine,'supports_pitch',False)):
            self.key_var.set(0)
            return
        try:
            key = max(-12, min(12, self.key_var.get()))
            self.key_var.set(key)
            if isinstance(self.engine,MidiPlayer) or getattr(self.engine,'supports_pitch',False):
                self.engine.set_key(key)
                self.current_item.key = key
        except OSError as error:
            self.key_var.set(getattr(self.engine,'key',0));self.show_error(error)
        except (tk.TclError, ValueError):
            self.key_var.set(0)

    def apply_speed(self):
        try:
            speed = max(50, min(150, self.speed_var.get()))
            self.speed_var.set(speed)
            if self.engine:
                old = self.engine.speed
                try:
                    self.engine.set_speed(speed / 100)
                    self.current_item.speed = speed
                except OSError as error:
                    self.speed_var.set(round(old * 100))
                    self.show_error(error)
        except (tk.TclError, ValueError):
            self.speed_var.set(100)

    def apply_volume(self, _=None):
        if self.engine:
            try:
                self.engine.set_volume(self.volume_var.get() / 100)
            except OSError:
                self.status_var.set("สื่อนี้ไม่รองรับปรับเสียงในโปรแกรม ให้ปรับระดับเสียงจากระบบ")

    def apply_melody(self):
        if isinstance(self.engine, MidiPlayer):
            self.engine.set_channel(3, muted=self.melody_var.get())

    def save_offset(self):
        try:
            value = max(-10000, min(10000, self.offset_var.get()))
            self.offset_var.set(value)
            if self.current_song:
                self.settings.setdefault("offsets", {})[self.current_song["path"]] = value
                self.save_settings()
        except (ValueError, tk.TclError):
            self.offset_var.set(0)

    def choose_lyrics(self):
        if not self.current_song:
            self.status_var.set("เลือกเล่นเพลงก่อน จึงเลือกไฟล์เนื้อร้องได้")
            return
        path = filedialog.askopenfilename(title="เลือกเนื้อร้อง", filetypes=[("LRC timed lyrics", "*.lrc")])
        if path:
            try:
                lyrics = parse_lrc(decode_text(Path(path).read_bytes()))
                if not lyrics.lines:
                    raise ValueError("ไม่พบเวลาในไฟล์ LRC ตัวอย่าง: [00:12.50]เนื้อร้อง")
                self.lyrics = lyrics
                self.settings.setdefault("lyric_files", {})[self.current_song["path"]] = str(Path(path).resolve())
                self.save_settings()
            except (OSError, ValueError) as error:
                self.show_error(error)

    def open_mixer(self):
        window = DialogWindow(self)
        window.title("MIDI mixer • 16 channels")
        window.configure(bg=BG)
        window.transient(self)
        ttk.Label(window.content, text="มิกเซอร์ใช้กับเพลง MIDI ปัจจุบัน • Ch10 คือกลอง • ช่องไกด์ขึ้นกับไฟล์เพลง").grid(row=0, column=0, columnspan=4, padx=18, pady=14)
        devices = WinMidi.devices()
        ttk.Label(window.content, text="อุปกรณ์เสียง MIDI").grid(row=1, column=0, padx=12)
        selected_device = tk.StringVar()
        names = [name for _, name in devices]
        combo = ttk.Combobox(window.content, state="readonly", values=names, width=38, textvariable=selected_device)
        combo.grid(row=1, column=1, columnspan=3, sticky="w", pady=8)
        current = int(self.settings.get("midi_device", -1))
        if devices:
            combo.current(next((i for i, (number, _) in enumerate(devices) if number == current), 0))
        def save_device(_=None):
            if combo.current() >= 0:
                self.settings["midi_device"] = devices[combo.current()][0]
                self.save_settings()
                self.status_var.set("บันทึก MIDI output แล้ว มีผลเมื่อเริ่มเพลงครั้งถัดไป")
        combo.bind("<<ComboboxSelected>>", save_device)
        bound_engine = self.engine if isinstance(self.engine, MidiPlayer) else None
        for channel in range(16):
            row, col = channel % 8 + 2, channel // 8 * 2
            group = ttk.Frame(window.content, padding=(12, 3))
            group.grid(row=row, column=col, columnspan=2, sticky="ew")
            label = f"Ch {channel + 1:02}" + (" กลอง" if channel == 9 else "")
            ttk.Label(group, text=label, width=11).pack(side="left")
            mute = tk.BooleanVar(value=bool(bound_engine and channel in bound_engine.muted))
            gain = tk.DoubleVar(value=(bound_engine.channel_gain[channel] if bound_engine else 1.0) * 100)
            def update(_=None, channel=channel, mute=mute, gain=gain):
                if bound_engine and self.engine is bound_engine:
                    bound_engine.set_channel(channel, gain.get() / 100, mute.get())
                    if channel == 3:
                        self.melody_var.set(mute.get())
            ttk.Scale(group, from_=0, to=100, length=130, variable=gain, command=update).pack(side="left")
            ttk.Checkbutton(group, text="ปิด", variable=mute, command=update).pack(side="left", padx=5)
        ttk.Button(window.content, text="ปิดหน้าต่าง", command=window.destroy).grid(row=11, column=0, columnspan=4, pady=16)

    def toggle_stage(self):
        if self.stage and self.stage.winfo_exists():
            self.stage_fullscreen = not self.stage_fullscreen
            if self.stage_fullscreen:self.stage.overrideredirect(False)
            self.stage.attributes("-fullscreen", self.stage_fullscreen)
            if not self.stage_fullscreen:self.stage.overrideredirect(True)
            self.stage.lift()
            return
        self.stage = tk.Toplevel(self)
        self.stage.overrideredirect(True)
        self.stage.title(DISPLAY_NAME+" — จอร้องเพลง (ลากไปจอที่ 2 แล้วกด F11)")
        self.stage.geometry("1000x600+100+80")
        self.stage.configure(bg="black")
        self.stage_canvas = self.canvas_class(self.stage)
        self.stage_canvas.pack(fill="both", expand=True)
        self.stage_video = tk.Frame(self.stage, bg="black")
        self.stage_video.bind("<Configure>", lambda _: self.resize_video())
        self.stage.bind("<F11>", lambda _: self.toggle_stage())
        self.stage.bind("<Escape>", lambda _: self.exit_stage_fullscreen())
        self.stage.protocol("WM_DELETE_WINDOW", self.close_stage)
        self.stage.update_idletasks()
        self.update_stage_mode()
        self.paint_lyrics()

    def exit_stage_fullscreen(self):
        if self.stage:
            self.stage.attributes("-fullscreen", False)
            self.stage.overrideredirect(True)
            self.stage_fullscreen = False

    def close_stage(self):
        if isinstance(self.engine, MediaPlayer) and self.engine.has_video:
            try:
                self.engine.set_window(self.video_frame.winfo_id())
            except OSError as error:
                self.show_error(error)
        if self.stage:
            self.stage.destroy()
        self.stage = self.stage_canvas = self.stage_video = None
        self.stage_fullscreen = False
        self.resize_video()

    def update_stage_mode(self):
        if not self.stage or not self.stage.winfo_exists():
            return
        video = isinstance(self.engine, MediaPlayer) and self.engine.has_video
        if video:
            self.stage_canvas.pack_forget()
            self.stage_video.pack(fill="both", expand=True)
            self.stage.update_idletasks()
            self.engine.set_window(self.stage_video.winfo_id())
        else:
            self.stage_video.pack_forget()
            self.stage_canvas.pack(fill="both", expand=True)

    def resize_video(self):
        if isinstance(self.engine, MediaPlayer) and self.engine.has_video:
            frame = self.stage_video if self.stage and self.stage.winfo_exists() else self.video_frame
            try:
                self.engine.resize(frame.winfo_width(), frame.winfo_height())
            except OSError:
                logging.debug("Video resize unsupported", exc_info=True)

    def paint_lyrics(self):
        title = self.now_var.get()
        current, following, prefix = None, None, ""
        if self.engine:
            try:
                offset = self.offset_var.get()
            except tk.TclError:
                offset = 0
            current, following, prefix = self.lyrics.at(self.engine.position, offset)
        if current:
            state = (current.text, following.text if following else "", prefix, title)
        elif following:
            state = ("♪", following.text, "", title)
        else:
            state = ("พร้อมร้องเพลง" if not self.current_song else "♪  " + self.current_song["title"],
                     "เพิ่มเพลงเข้าคิว แล้วกดเล่น" if not self.current_song else "เพลงนี้ไม่มีเนื้อร้องแบบจับเวลา", "", title)
        self.preview.show(*state)
        if self.stage_canvas and self.stage_canvas.winfo_exists():
            self.stage_canvas.show(*state)

    def tick(self):
        try:return KaraokeApp._tick_once(self)
        except Exception as error:
            logging.exception('UI_TICK_FAILED')
            if not getattr(self,'closing',False):
                try:self.tick_after=self.after(80,self.tick)
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
                if kind == "progress":
                    self.status_var.set(f"กำลังค้นหา… พบ {data:,} ไฟล์")
                elif kind == "scan_done":
                    self.scanning = False
                    count, skipped, errors = data
                    self.refresh_library()
                    self.status_var.set(f'ตรวจแล้ว {count:,} เพลง · ข้าม {skipped:,} · ข้อสังเกต {len(errors):,} — ดูรายงานตรวจเพลงในเมนูคลิกขวา')
                elif kind == "job_progress":
                    self.handle_job_progress(data)
                elif kind == "job_note":
                    self.status_var.set(data)
                elif kind == "scan_error":
                    self.scanning = False
                    self.refresh_library();self.refresh_queue()
                    self.show_error(data)
        except queue.Empty:
            pass
        except Exception as error:
            logging.exception('UI_MESSAGE_FAILED kind=%s',locals().get('kind'))
            try:self.show_error('งานบางส่วนบันทึกไม่สำเร็จ: '+str(error))
            except Exception:logging.exception('UI_ERROR_REPORT_FAILED')
        try:
            if self.engine:
                self.engine.pump()
                position = self.engine.position
                self.time_var.set(f"{timestamp(position)} / {timestamp(self.engine.duration)}")
                if not self.dragging:
                    self.seek_var.set(position)
                if self.engine.ended:
                    self.engine.ended = False
                    self.on_song_ended()
            self.paint_lyrics()
        except Exception as error:
            logging.exception("Playback error")
            if self.engine:
                try:
                    self.engine.close()
                except OSError:
                    pass
                self.engine = None
            self.show_error(error)
        self.tick_after = self.after(10 if isinstance(self.engine, MidiPlayer) else 80, self.tick)

    def show_error(self, error):
        self.status_var.set(str(error).splitlines()[0])
        messagebox.showerror("X-Stage Karaoke", str(error), parent=self)

    def save_settings(self):
        self.settings.update(volume=self.volume_var.get(), auto_next=self.auto_var.get())
        self._settings_revision = write_json(self.settings_path, self.settings, expected_revision=getattr(self,'_settings_revision',JSON_UNSET))

    def help(self):
        messagebox.showinfo("วิธีใช้ X-Stage Karaoke", "1. เพิ่มไฟล์หรือโฟลเดอร์เพลง แล้วค้นหาชื่อ/ศิลปิน/รหัส\n"
            "2. ดับเบิลคลิกเพลงเพื่อเข้าคิว กดเล่นเพื่อเริ่มคิว\n"
            "3. MIDI/KAR ใช้ตัวสังเคราะห์เสียงของระบบ ปรับคีย์และมิกเซอร์ 16 ช่องได้\n"
            "4. MP3/WAV และวิดีโอใช้ codec ที่ Windows มี ความเร็วของสื่ออาจเปลี่ยนระดับเสียงด้วย\n"
            "5. วาง .lrc ชื่อเดียวกับเพลงไว้ข้างกัน หรือกดเลือกเนื้อร้อง\n"
            "6. เปิดจอร้องเพลง ลากไปจอที่ 2 แล้วกด F11 เพื่อเต็มจอ; Esc ออกเต็มจอ\n\n"
            "Ctrl+F ค้นหา | Enter ในคลัง = เพิ่มคิว | F5 เล่น/พัก | F6 ถัดไป | F8 หยุด\n\n"
            "ไม่รองรับ EMK/XMK/XAK, NCN .cur/.lyr, SoundFont, แยกเสียงร้องจากสเตอริโอ, "
            "บันทึกไมค์ หรือเอฟเฟกต์ ASIO/VST ในรุ่นนี้\n"
            "โปรแกรมเขียนใหม่เป็นอิสระ ไม่ใช้ KaraPlayer.exe หรือ DLL ของ eXtreme", parent=self)

    def close_app(self):
        from .shutdown import step,finish
        if self.__dict__.get('_shutdown_done'):return
        from .shutdown import wait_for_index
        if wait_for_index(self):return
        self.closing=True
        step(self,'ยกเลิกสแกน',lambda:self.cancel_scan.set())
        if self.tick_after:step(self,'หยุด tick',lambda:self.after_cancel(self.tick_after))
        if self.search_after:step(self,'หยุดค้นหา',lambda:self.after_cancel(self.search_after))
        job=self.__dict__.get('job_window')
        if job is not None and hasattr(job,'workspace'):step(self,'ปิดงานค้นหน้าคลัง',job.workspace.close)
        step(self,'บันทึกตั้งค่า',self.save_settings)
        step(self,'บันทึกคิว',self.song_queue.save)
        if self.engine:step(self,'ปิดระบบเล่นเสียง',self.engine.close)
        finish(self)
