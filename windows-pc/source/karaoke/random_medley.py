"""Read-only candidate preview for a finite shuffled medley in the song queue."""
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import queue
import random
import sqlite3
import stat
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from tkinter.font import Font

from .dialog_layout import ActionBar, DialogWindow, scrollable_tree
from .library import QueueItem, SUPPORTED, SearchCancelled, SearchReader, normalize, parse_json
from .name_duplicates import identity


SOURCE_LABELS = {
    'library': 'คลังเพลงทั้งหมด',
    'rhythm': 'แนว / จังหวะเพลง',
    'playlist': 'ไฟล์เพลย์ลิสต์',
    'favorites': 'เพลงโปรด',
    'popular': 'เพลงฮิตจากประวัติ',
}
MAX_SONGS = 200
MAX_PLAYLIST_BYTES = 64 * 1024 * 1024
SAMPLE_THRESHOLD = 2000
SAMPLE_CAP = 8000
ACTIVE = "duplicate_state NOT IN ('moved','recycled','deleted','excluded','invalid','missing')"
VISIBLE = f"playable = 1 AND duplicate_of = 0 AND {ACTIVE}"
FIELDS = 'id,path,title,artist,key_signature,rhythm'
BG = '#10192d'
PANEL = '#172740'
TEAL = '#78e4ea'
INK = '#eef5ff'
MUTED = '#b4c5dc'


def rhythm_key(value):
    return ' '.join(normalize(str(value or '')).split())


def read_rhythms(library_path):
    with closing(SearchReader(library_path)) as reader:
        rows = reader.db.execute(f'SELECT DISTINCT rhythm FROM songs WHERE {VISIBLE} ORDER BY rhythm')
        names = {}
        for (name,) in rows:
            names.setdefault(rhythm_key(name), ' '.join(str(name or '').split()))
    return tuple((key, names[key]) for key in sorted(names, key=lambda key: (not key, key)))


def _path_key(path, base=None):
    # Compare against indexed paths without probing arbitrary paths from a playlist.
    path = Path(path)
    if base is not None and not path.is_absolute():
        path = base / path
    # SongLibrary stores canonical Path.resolve() paths.  On Windows the
    # working folder may be reached through a junction, a symlink, or an
    # 8.3 alias: abspath() does not resolve these aliases, so comparing an
    # imported playlist/history path to the SQLite path silently fails.
    return os.path.normcase(str(path.resolve()))


def read_playlist(path, cancelled):
    path = Path(path)
    with path.open('rb') as stream:
        raw = stream.read(MAX_PLAYLIST_BYTES + 1)
    if len(raw) > MAX_PLAYLIST_BYTES:
        raise ValueError('ไฟล์เพลย์ลิสต์ใหญ่เกิน 64 MB')
    data = parse_json(raw.decode('utf-8-sig'))
    if (not isinstance(data, dict) or data.get('format') not in ('xstage.playlist', 'newKaraoke.playlist')
            or not isinstance(data.get('tracks'), list)):
        raise ValueError('กรุณาเลือกไฟล์เพลย์ลิสต์ที่ส่งออกจาก X-Stage Karaoke')
    version = data.get('version', 1)
    if type(version) is not int or version != 1:
        raise ValueError('ไม่รองรับรุ่นไฟล์เพลย์ลิสต์นี้')
    result = []
    for number, track in enumerate(data['tracks'], 1):
        if cancelled():
            raise SearchCancelled()
        name = track.get('path') if isinstance(track, dict) else None
        if not isinstance(name, str) or not name.strip() or '\x00' in name:
            raise ValueError(f'ตำแหน่งเพลงในเพลย์ลิสต์ลำดับที่ {number} ไม่ถูกต้อง')
        try:
            item = QueueItem.from_dict({**track, 'song_id': 0, 'request_id': '', 'medley_session': ''})
            result.append((_path_key(name, path.parent), item))
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(f'ค่าเพลงในเพลย์ลิสต์ลำดับที่ {number} ไม่ถูกต้อง') from error
    return result


@dataclass
class Candidate:
    item: QueueItem
    title: str
    artist: str
    key: str
    rhythm: str
    plays: int = 0


@dataclass
class Preview:
    rows: list[Candidate]
    matched: int
    queued: int
    duplicates: int
    unavailable: int


def build_preview(library_path, source, count, *, rhythm='', playlist=None,
                  excluded_ids=(), cancelled=lambda: False, rng=None, history_path=None,
                  popular_period='all'):
    if type(count) is not int or not 1 <= count <= MAX_SONGS:
        raise ValueError(f'ระบุจำนวนเพลงตั้งแต่ 1 ถึง {MAX_SONGS}')
    if source not in SOURCE_LABELS:
        raise ValueError('แหล่งเพลงไม่ถูกต้อง')
    if source == 'playlist' and not playlist:
        raise ValueError('กรุณาเลือกไฟล์เพลย์ลิสต์')
    if source == 'popular' and history_path is None:
        raise ValueError('ไม่พบตำแหน่งบันทึกประวัติการเล่น')
    rng = rng if rng is not None else random
    tracks = read_playlist(playlist, cancelled) if source == 'playlist' else None
    if source == 'popular':
        from .popular_medley import history_hits
        hits = history_hits(history_path, popular_period, cancelled=cancelled)
    else:
        hits = None
    excluded_ids = {song_id for song_id in excluded_ids if type(song_id) is int and 0 < song_id < 2**63}
    excluded_keys = set()
    unavailable = queued = duplicates = 0
    groups = defaultdict(list)
    seen_ids = set()
    popular_plays = {}

    def check_cancelled():
        if cancelled():
            raise SearchCancelled()

    def add(row, item):
        nonlocal unavailable, queued, duplicates
        check_cancelled()
        song_id = row['id']
        key = identity(row['title'], row['artist'], row['key_signature'])
        if song_id in excluded_ids or (key is not None and key in excluded_keys):
            queued += 1
            return
        if Path(row['path']).suffix.lower() not in SUPPORTED:
            unavailable += 1
            return
        if song_id in seen_ids:
            duplicates += 1
            return
        seen_ids.add(song_id)
        group = groups[key if key is not None else song_id]
        duplicates += bool(group)
        group.append((row, item))

    try:
        with closing(SearchReader(library_path)) as reader:
            db = reader.db
            db.set_progress_handler(lambda: int(cancelled()), 1000)
            db.execute('BEGIN')
            protected_ids = tuple(excluded_ids)
            for offset in range(0, len(protected_ids), 500):
                subset = protected_ids[offset:offset + 500]
                placeholders = ','.join('?' for _ in subset)
                protected = db.execute(
                    'SELECT title,artist,key_signature,duplicate_of FROM songs WHERE id IN (' + placeholders + ')',
                    subset,
                )
                for row in protected:
                    key = identity(row['title'], row['artist'], row['key_signature'])
                    if key is not None:
                        excluded_keys.add(key)
                    if row['duplicate_of']:
                        excluded_ids.add(row['duplicate_of'])
            if hits is not None:
                # Read at most 500 recently played IDs, instead of traversing the whole library.
                history_ids = tuple(dict.fromkeys(song_id for song_id, _, _, _ in hits))
                indexed = {}
                for offset in range(0, len(history_ids), 400):
                    subset = history_ids[offset:offset + 400]
                    placeholders = ','.join('?' for _ in subset)
                    for row in db.execute(
                            f'SELECT {FIELDS},duplicate_of,duplicate_state,playable FROM songs '
                            f'WHERE id IN ({placeholders})', subset):
                        indexed[row['id']] = row
                keeper_ids = tuple({row['duplicate_of'] for row in indexed.values() if row['duplicate_of']})
                for offset in range(0, len(keeper_ids), 400):
                    subset = keeper_ids[offset:offset + 400]
                    placeholders = ','.join('?' for _ in subset)
                    for row in db.execute(
                            f'SELECT {FIELDS},duplicate_of,duplicate_state,playable FROM songs '
                            f'WHERE id IN ({placeholders})', subset):
                        indexed[row['id']] = row
                ranked = {}
                for song_id, recorded_path, plays, latest in hits:
                    check_cancelled()
                    historical = indexed.get(song_id)
                    if historical is None or _path_key(historical['path']) != _path_key(recorded_path):
                        unavailable += 1
                        continue
                    row = indexed.get(historical['duplicate_of'] or song_id)
                    if (row is None or not row['playable'] or row['duplicate_of']
                            or row['duplicate_state'] in ('moved', 'recycled', 'deleted', 'excluded', 'invalid', 'missing')):
                        unavailable += 1
                        continue
                    group_key = identity(row['title'], row['artist'], row['key_signature'])
                    group_key = group_key if group_key is not None else ('id', row['id'])
                    group = ranked.setdefault(group_key, {'plays': 0, 'latest': latest, 'candidates': []})
                    group['plays'] += plays
                    if latest > group['latest']:
                        group['latest'] = latest
                    group['candidates'].append((plays, latest, row))
                matched = len(ranked)
                ranking = sorted(ranked.values(), key=lambda group: (-group['plays'],
                                -group['latest'].timestamp()))
                for group in ranking:
                    for _plays, _latest, row in group['candidates']:
                        rank_key = identity(row['title'], row['artist'], row['key_signature'])
                        popular_plays[rank_key if rank_key is not None else row['id']] = group['plays']
                    # Keep multiple candidates in a group for file-availability fallback.
                    for _plays, _latest, row in sorted(group['candidates'],
                            key=lambda hit: (-hit[0], -hit[1].timestamp())):
                        add(row, QueueItem(row['id']))
            elif tracks is None:
                where = VISIBLE
                if source == 'favorites':
                    where += (' AND (favorite = 1 OR EXISTS (SELECT 1 FROM songs AS alias'
                              f' WHERE alias.duplicate_of = songs.id AND alias.favorite = 1 AND alias.{ACTIVE}))')
                wanted_rhythm = rhythm_key(rhythm)
                available = db.execute(f'SELECT COUNT(*) FROM songs WHERE {where}').fetchone()[0]
                if available <= SAMPLE_THRESHOLD:
                    matched = 0
                    for row in db.execute(f'SELECT {FIELDS} FROM songs WHERE {where} ORDER BY id'):
                        check_cancelled()
                        if source == 'rhythm' and rhythm_key(row['rhythm']) != wanted_rhythm:
                            continue
                        matched += 1
                        add(row, QueueItem(row['id']))
                elif source != 'rhythm':
                    # SQLite samples a bounded set directly; Python no longer
                    # builds a list/dictionary for every row of a huge catalog.
                    # ORDER BY RANDOM may scan the index, but memory usage stays
                    # proportional to the preview size, not catalog size.
                    matched = available
                    cap = min(SAMPLE_CAP, max(300, count * 30))
                    for row in db.execute(f'SELECT {FIELDS} FROM songs WHERE {where}'
                                          ' ORDER BY RANDOM() LIMIT ?', (cap,)):
                        check_cancelled()
                        add(row, QueueItem(row['id']))
                else:
                    # Rhythm labels need normalization (e.g. 'Rock  Pop');
                    # stream them with fixed-memory reservoir sampling.
                    from .bounded_sample import reservoir
                    cap = min(SAMPLE_CAP, max(300, count * 30))
                    selected, matched = reservoir(
                        db.execute(f'SELECT {FIELDS} FROM songs WHERE {where} ORDER BY id'),
                        cap, rng, lambda row: rhythm_key(row['rhythm']) == wanted_rhythm,
                        cancelled,
                    )
                    for row in selected:
                        add(row, QueueItem(row['id']))
            else:
                wanted = {path for path, _ in tracks}
                by_id = {}
                aliases = {}
                by_path = {}
                for row in db.execute(f'SELECT {FIELDS},duplicate_of,playable FROM songs WHERE {ACTIVE} ORDER BY id'):
                    check_cancelled()
                    song_id = row['id']
                    if row['playable'] and not row['duplicate_of']:
                        by_id[song_id] = row
                    path = _path_key(row['path'])
                    if path in wanted:
                        if row['duplicate_of']:
                            aliases[path] = row['duplicate_of']
                        elif row['playable']:
                            by_path[path] = row
                matched = len(tracks)
                for path, item in tracks:
                    check_cancelled()
                    row = by_path.get(path) or by_id.get(aliases.get(path))
                    if row is None:
                        unavailable += 1
                        continue
                    item.song_id = row['id']
                    add(row, item)
    except sqlite3.OperationalError:
        check_cancelled()
        raise

    groups = list(groups.values())
    if source != 'popular':
        rng.shuffle(groups)
    result = []
    for group in groups:
        for row, item in group:
            check_cancelled()
            try:
                file = Path(row['path']).stat()
                available = stat.S_ISREG(file.st_mode) and file.st_size > 0
            except OSError:
                available = False
            if not available:
                unavailable += 1
                continue
            score_key = identity(row['title'], row['artist'], row['key_signature'])
            result.append(Candidate(item, row['title'], row['artist'], row['key_signature'],
                                    row['rhythm'], popular_plays.get(score_key if score_key is not None
                                                                     else row['id'], 0)))
            break
        if len(result) == count:
            break
    check_cancelled()
    return Preview(result, matched, queued, duplicates, unavailable)


class RandomMedleyWindow:
    def __init__(self, app, source):
        self.app = app
        self.window = DialogWindow(app)
        self.window.title('เมดเล่ย์ — X-Stage')
        self.window.transient(app)
        self.window.geometry('970x650')
        self.window.bind('<Escape>', lambda _event: self.window.destroy())
        self.window.bind('<Destroy>', self._destroy, add='+')
        self.closed = threading.Event()
        self.timer = None
        self.busy = False
        self.preview = None
        self.playlist_path = None
        self.rhythms = None
        self.source = tk.StringVar(self.window, SOURCE_LABELS[source])
        self.count = tk.StringVar(self.window, '10')
        self.rhythm = tk.StringVar(self.window)
        self.popular_period = tk.StringVar(self.window, 'ทั้งหมดที่บันทึกไว้')
        self.playlist_text = tk.StringVar(self.window, 'ยังไม่ได้เลือกไฟล์')
        self.summary = tk.StringVar(self.window)
        self._build()
        for variable in (self.count, self.rhythm, self.popular_period):
            variable.trace_add('write', self._invalidate_preview)
        self._source_changed()

    def _build(self):
        style = ttk.Style(self.window)
        height = Font(self.window, family='Leelawadee UI', size=11).metrics('linespace') + 12
        style.configure('Medley.Treeview', background=PANEL, fieldbackground=PANEL, foreground=INK, rowheight=height)
        style.map('Medley.Treeview', background=[('selected', '#285771')], foreground=[('selected', INK)])
        style.configure('Medley.Treeview.Heading', background='#223750', foreground=INK,
                        font=('Leelawadee UI', 10, 'bold'))

        header = tk.Frame(self.window.content, bg='#152740', padx=22, pady=14)
        header.pack(fill='x')
        tk.Label(header, text='X-STAGE   /   MEDLEY', bg='#152740', fg=TEAL,
                 font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        self.header_title = tk.Label(header, text='สุ่มเมดเล่ย์', bg='#152740', fg=INK,
                                     font=('Leelawadee UI', 20, 'bold'))
        self.header_title.pack(anchor='w')
        tk.Label(header, text='เลือกแหล่งเพลง จัดลำดับในตัวอย่าง แล้วค่อยเพิ่มเข้าคิว',
                 bg='#152740', fg=MUTED, font=('Leelawadee UI', 10),
                 wraplength=760, justify='left').pack(anchor='w', pady=(4, 0))

        body = tk.Frame(self.window.content, bg=BG, padx=20, pady=12)
        body.pack(fill='both', expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(3, weight=1)
        form = ttk.Frame(body, padding=(8, 8))
        form.grid(row=0, column=0, sticky='ew')
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text='แหล่งเพลง').grid(row=0, column=0, sticky='w', padx=(0, 10))
        self.source_combo = ttk.Combobox(form, textvariable=self.source, values=tuple(SOURCE_LABELS.values()),
                                         state='readonly', width=24)
        self.source_combo.grid(row=0, column=1, sticky='ew')
        self.source_combo.bind('<<ComboboxSelected>>', self._source_changed)
        ttk.Label(form, text='จำนวนเพลง').grid(row=0, column=2, padx=(14, 8))
        self.count_box = ttk.Spinbox(form, from_=1, to=MAX_SONGS, textvariable=self.count, width=5)
        self.count_box.grid(row=0, column=3, sticky='w')
        self.count_box.bind('<Return>', lambda _event: self.generate())
        self.rhythm_row = ttk.Frame(form)
        self.rhythm_row.grid(row=1, column=0, columnspan=4, sticky='ew', pady=(8, 0))
        ttk.Label(self.rhythm_row, text='จังหวะจากคลัง').pack(side='left', padx=(0, 8))
        self.rhythm_combo = ttk.Combobox(self.rhythm_row, textvariable=self.rhythm, state='readonly', width=24)
        self.rhythm_combo.pack(side='left', fill='x', expand=True)
        self.popular_row = ttk.Frame(form)
        self.popular_row.grid(row=3, column=0, columnspan=4, sticky='ew', pady=(8, 0))
        ttk.Label(self.popular_row, text='จัดอันดับจากประวัติ').pack(side='left', padx=(0, 8))
        self.popular_combo = ttk.Combobox(
            self.popular_row, textvariable=self.popular_period, state='readonly', width=35,
            values=('ทั้งหมดที่บันทึกไว้', 'ย้อนหลัง 7 วัน', 'ย้อนหลัง 30 วัน', 'ย้อนหลัง 90 วัน'))
        self.popular_combo.pack(side='left', fill='x', expand=True)
        self.playlist_row = ttk.Frame(form)
        self.playlist_row.grid(row=2, column=0, columnspan=4, sticky='ew', pady=(8, 0))
        self.file_button = ttk.Button(self.playlist_row, text='เลือกเพลย์ลิสต์…', command=self._choose_playlist)
        self.file_button.pack(side='left', padx=(0, 8))
        ttk.Entry(self.playlist_row, textvariable=self.playlist_text, state='readonly').pack(side='left', fill='x', expand=True)

        title = ttk.Frame(body, padding=(0, 5))
        title.grid(row=1, column=0, sticky='ew', pady=(5, 0))
        ttk.Label(title, text='ตัวอย่างชุดเพลง', font=('Leelawadee UI', 12, 'bold')).pack(side='left')
        self.generate_button = ttk.Button(title, text='สุ่มตัวอย่าง', command=self.generate)
        self.generate_button.pack(side='right')
        tk.Label(body, textvariable=self.summary, bg=BG, fg=MUTED, wraplength=840,
                 justify='left').grid(row=2, column=0, sticky='w', pady=(0, 6))

        table, self.table = scrollable_tree(
            body, style='Medley.Treeview', columns=('number', 'song', 'artist', 'key', 'rhythm', 'plays', 'speed', 'singer'),
            show='headings', height=8, selectmode='browse',
        )
        table.grid(row=3, column=0, sticky='nsew')
        for field, label, width, stretch in (
            ('number', 'ลำดับ', 60, False), ('song', 'ชื่อเพลง', 270, True), ('artist', 'ศิลปิน', 145, True),
            ('key', 'คีย์', 80, False), ('rhythm', 'จังหวะ', 95, False),
            ('plays', 'เล่น (ครั้ง)', 90, False), ('speed', 'ความเร็ว', 75, False),
            ('singer', 'ผู้ร้อง', 110, True),
        ):
            self.table.heading(field, text=label)
            self.table.column(field, width=width, minwidth=min(width, 54), stretch=stretch)
        self.table.tag_configure('odd', background='#1c304a')
        self.table.bind('<<TreeviewSelect>>', lambda _event: self._button_state())
        self.table.bind('<Alt-Up>', lambda _event: self._move(-1))
        self.table.bind('<Alt-Down>', lambda _event: self._move(1))
        reorder = ttk.Frame(body, padding=(0, 5))
        reorder.grid(row=4, column=0, sticky='ew')
        self.up_button = ttk.Button(reorder, text='เลื่อนขึ้น ↑', command=lambda: self._move(-1))
        self.up_button.pack(side='left', padx=(0, 8))
        self.down_button = ttk.Button(reorder, text='เลื่อนลง ↓', command=lambda: self._move(1))
        self.down_button.pack(side='left')

        footer = ActionBar(self.window.footer, padding=(12, 7))
        footer.pack(fill='x')
        self.add_button = ttk.Button(footer, text='เพิ่มท้ายคิว', style='Accent.TButton',
                                     command=lambda: self._enqueue(False))
        self.next_button = ttk.Button(footer, text='เล่นถัดไป', command=lambda: self._enqueue(True))
        close_button = ttk.Button(footer, text='ปิด', command=self.window.destroy)
        for button in (self.add_button, self.next_button, close_button):
            button.pack(side='left')

    def _source_key(self):
        return next(key for key, label in SOURCE_LABELS.items() if label == self.source.get())

    def show(self, source=None):
        self.window.deiconify()
        self.window.lift()
        if source is not None and not self.busy and source != self._source_key():
            self.source.set(SOURCE_LABELS[source])
            self._source_changed()

    def _source_changed(self, _event=None):
        source = self._source_key()
        self.header_title.configure(text='เมดเล่ย์เพลงฮิต' if source == 'popular' else 'สุ่มเมดเล่ย์')
        for key, row in (('rhythm', self.rhythm_row), ('playlist', self.playlist_row),
                         ('popular', self.popular_row)):
            if key == source:
                row.grid()
            else:
                row.grid_remove()
        self._invalidate_preview()
        if source == 'rhythm' and self.rhythms is None and not self.busy:
            path = self.app.library.path
            self._work(lambda: read_rhythms(path), self._show_rhythms, 'กำลังอ่านจังหวะจากคลัง…')

    def _show_rhythms(self, rhythms):
        self.rhythms = dict(rhythms)
        labels = tuple(name if key else '(จังหวะว่างในคลัง)' for key, name in rhythms)
        self.rhythm_combo.configure(values=labels)
        if labels:
            self.rhythm_combo.current(0)
        else:
            self.summary.set('ยังไม่มีเพลงพร้อมเล่นในคลัง')

    def _choose_playlist(self):
        path = filedialog.askopenfilename(parent=self.window, title='เลือกเพลย์ลิสต์ X-Stage',
                                         filetypes=[('เพลย์ลิสต์ X-Stage Karaoke', '*.json')])
        if path:
            self.playlist_path = Path(path)
            self.playlist_text.set(str(self.playlist_path))
            self._invalidate_preview()

    def _invalidate_preview(self, *_):
        self.preview = None
        self.table.delete(*self.table.get_children())
        self.summary.set('กดสุ่มตัวอย่างเพื่อดูเพลงก่อนเพิ่มเข้าคิว')
        self._button_state()

    def _button_state(self):
        ready = bool(self.preview and self.preview.rows and not self.busy)
        selected = self.table.selection()
        index = int(selected[0]) if selected else -1
        rhythm_ready = self.rhythm_combo.current() >= 0 if self._source_key() == 'rhythm' else True
        states = (
            (self.generate_button, not self.busy and rhythm_ready),
            (self.add_button, ready), (self.next_button, ready),
            (self.up_button, ready and index > 0),
            (self.down_button, ready and 0 <= index < len(self.preview.rows) - 1),
            (self.count_box, not self.busy), (self.file_button, not self.busy),
            (self.source_combo, not self.busy), (self.rhythm_combo, not self.busy),
            (self.popular_combo, not self.busy),
        )
        for button, enabled in states:
            button.state(['!disabled'] if enabled else ['disabled'])
        if self._source_key() == 'popular':
            self.generate_button.configure(text='จัดอันดับใหม่' if self.preview else 'จัดอันดับเพลงฮิต')
        else:
            self.generate_button.configure(text='สุ่มใหม่' if self.preview else 'สุ่มตัวอย่าง')

    def _work(self, run, success, label):
        self.busy = True
        self.summary.set(label)
        self._button_state()
        result = queue.Queue(maxsize=1)

        def worker():
            try:
                result.put((run(), None))
            except SearchCancelled:
                return
            except (OSError, ValueError, sqlite3.Error) as error:
                result.put((None, error))
            except Exception:
                logging.exception('RANDOM_MEDLEY_PREVIEW_FAILED')
                result.put((None, ValueError('อ่านข้อมูลชุดเมดเล่ย์ไม่สำเร็จ กรุณาลองใหม่')))

        def poll():
            self.timer = None
            try:
                value, error = result.get_nowait()
            except queue.Empty:
                self.timer = self.window.after(100, poll)
                return
            self.busy = False
            if error:
                self.summary.set(str(error))
            else:
                success(value)
            self._button_state()

        threading.Thread(target=worker, daemon=True, name='random-medley-preview').start()
        self.timer = self.window.after(100, poll)

    def generate(self):
        if self.busy:
            return
        self._invalidate_preview()
        try:
            count = int(self.count.get())
        except ValueError:
            count = 0
        if not 1 <= count <= MAX_SONGS:
            self.summary.set(f'ระบุจำนวนเพลงตั้งแต่ 1 ถึง {MAX_SONGS}')
            return
        source = self._source_key()
        rhythm = ''
        if source == 'rhythm':
            index = self.rhythm_combo.current()
            if index < 0:
                return
            rhythm = tuple(self.rhythms)[index]
        path = self.app.library.path
        playlist = self.playlist_path
        popular_period = {'ย้อนหลัง 7 วัน': '7', 'ย้อนหลัง 30 วัน': '30', 'ย้อนหลัง 90 วัน': '90'}.get(
            self.popular_period.get(), 'all')
        history_path = self.app.data_dir / 'history.json' if source == 'popular' else None
        excluded = {item.song_id for item in self.app.song_queue.items}
        current = getattr(self.app, 'current_item', None)
        if current is not None:
            excluded.add(current.song_id)
        self._work(
            lambda: build_preview(path, source, count, rhythm=rhythm, playlist=playlist,
                                  excluded_ids=excluded, cancelled=self.closed.is_set,
                                  history_path=history_path, popular_period=popular_period),
            self._show_preview, ('กำลังจัดอันดับเพลงจากประวัติ…' if source == 'popular'
                                 else 'กำลังสุ่มเพลงและตรวจไฟล์ที่เลือก…'),
        )

    def _show_preview(self, preview):
        self.preview = preview
        self._render()
        if self._source_key() == 'popular' and not preview.rows:
            self.summary.set('ยังไม่พบเพลงฮิตที่พร้อมเล่นในช่วงเวลานี้ · ตรวจประวัติการเล่นหรือเลือกช่วงเวลาอื่น')
            return
        short = ' · เพลงพร้อมเล่นมีไม่ถึงจำนวนที่ขอ' if len(preview.rows) < int(self.count.get()) else ''
        action = 'เลือกเพลงฮิตได้' if self._source_key() == 'popular' else 'สุ่มได้'
        self.summary.set(
            f'พบ {preview.matched:,} รายการ · {action} {len(preview.rows):,} เพลง · '
            f'ซ้ำ {preview.duplicates:,} · อยู่ในคิว/กำลังเล่น {preview.queued:,} · '
            f'อ่านไม่ได้หรือไม่อยู่ในคลัง {preview.unavailable:,}{short}'
        )

    def _render(self, selection=None):
        self.table.delete(*self.table.get_children())
        for index, row in enumerate(self.preview.rows):
            key = row.key or '—'
            if row.item.key:
                key += f' ({row.item.key:+d})'
            values = (index + 1, row.title, row.artist or '—', key, row.rhythm or '—',
                      row.plays if row.plays else '—', f'{row.item.speed}%', row.item.singer or '—')
            self.table.insert('', 'end', iid=str(index), values=values, tags=('odd',) if index % 2 else ())
        if selection is not None:
            self.table.selection_set(str(selection))
            self.table.focus(str(selection))
            self.table.see(str(selection))
        self._button_state()

    def _move(self, direction):
        selected = self.table.selection()
        if selected and self.preview and not self.busy:
            index = int(selected[0])
            target = index + direction
            rows = self.preview.rows
            if 0 <= target < len(rows):
                rows[index], rows[target] = rows[target], rows[index]
                self._render(target)
        return 'break'

    def _enqueue(self, play_next):
        if self.preview and self.preview.rows and not self.busy:
            try:
                accepted = self.app.enqueue_random_medley([row.item for row in self.preview.rows],
                                                          play_next=play_next)
            except (OSError, ValueError) as error:
                self.summary.set(str(error))
                return
            if accepted:
                self.window.destroy()
            else:
                self._invalidate_preview()
                self.summary.set('เพิ่มชุดเพลงไม่ได้ คิวหรือคลังอาจเปลี่ยนแล้ว กรุณาสร้างตัวอย่างอีกครั้ง')

    def _destroy(self, event):
        if event.widget is self.window:
            self.closed.set()
            if self.timer is not None:
                self.window.after_cancel(self.timer)
                self.timer = None
            if getattr(self.app, '_random_medley_window', None) is self:
                self.app._random_medley_window = None


def open_window(app, source='library'):
    dialog = getattr(app, '_random_medley_window', None)
    if dialog is None or not dialog.window.winfo_exists():
        dialog = app._random_medley_window = RandomMedleyWindow(app, source)
    else:
        dialog.show(source)
    return dialog
