"""Song catalog maintenance window and its read-only paged list."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import os
import sqlite3
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .dialog_layout import ActionBar, DialogWindow, scrollable_tree
from .library import SearchReader, normalize


PAGE_SIZE = 100
BG = '#101a2c'
PANEL = '#16253b'
ALT = '#1b2d46'
INK = '#eef5ff'
MUTED = '#aebed4'
TEAL = '#72dfdb'


def read_page(path, query, page, cancelled):
    """Read one ordered page without holding a connection across app jobs."""
    active = "duplicate_of = 0 AND duplicate_state NOT IN ('moved','recycled','deleted','invalid','missing','excluded')"
    with closing(SearchReader(path)) as reader:
        db = reader.db
        db.set_progress_handler(lambda: int(cancelled()), 1000)
        db.execute('BEGIN')
        where = [active]
        parameters = []
        for token in normalize(query).split():
            # Trigram FTS indexes Thai and long title/artist fragments; short
            # musical keys still use LIKE to preserve the original semantics.
            if reader.fts and len(token) >= 3 and any('\u0e00' <= char <= '\u0e7f' for char in token):
                where.append('id IN (SELECT rowid FROM song_fts WHERE song_fts MATCH ?)')
                parameters.append('"' + token.replace('"', '""') + '"')
            else:
                where.append("(search LIKE ? ESCAPE '\\' OR key_signature LIKE ? ESCAPE '\\')")
                escaped = token.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
                parameters.extend(('%' + escaped + '%', '%' + escaped + '%'))
        clause = ' WHERE ' + ' AND '.join(where)
        total = reader.count()
        found = db.execute('SELECT count(*) FROM songs' + clause, parameters).fetchone()[0] if parameters else total
        page = max(0, min(page, (found - 1) // PAGE_SIZE))
        rows = db.execute(
            'SELECT code,title,artist,key_signature FROM songs' + clause +
            ' ORDER BY title COLLATE NOCASE,id LIMIT ? OFFSET ?',
            [*parameters, PAGE_SIZE, page * PAGE_SIZE],
        ).fetchall()
        return rows, total, found, page


class CatalogWindow:
    """Choose a source, maintain the index, and browse the saved songs."""

    def __init__(self, app):
        self.app = app
        self.window = DialogWindow(app)
        self.window.title('สร้างรายการเพลง — X-Stage')
        self.window.transient(app)
        self.window.geometry('960x790')
        self.window.protocol('WM_DELETE_WINDOW', self.hide)
        self.window.bind('<Escape>', lambda _: self.hide())
        self.window.bind('<Destroy>', self._on_destroy, add='+')
        self.source = Path(app.managed_catalog_root())
        self.source_text = tk.StringVar(self.window, value=str(self.source))
        self.query = tk.StringVar(self.window)
        self.summary = tk.StringVar(self.window, value='กำลังอ่านรายการเพลง…')
        self.status = tk.StringVar(self.window, value='พร้อมจัดการรายการเพลง')
        self.progress_detail = tk.StringVar(self.window)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='catalog-pages')
        self._revision = 0
        self._future = None
        self._pending = None
        self._poll_timer = None
        self._closed = False
        self._active = False
        self._busy = None
        self._cancel_requested = False
        self._indeterminate = False
        self._phase_total = None
        self._page = 0
        self.mode = tk.StringVar(self.window, value='quick')
        self.duplicates = tk.StringVar(self.window, value='review')
        self.shutdown_after = tk.BooleanVar(self.window, value=False)
        self.duplicate_report_path = None
        self._build()
        self.refresh()
        self._poll()

    def _build(self):
        style = ttk.Style(self.window)
        style.configure('Catalog.Treeview', background=PANEL, fieldbackground=PANEL, foreground=INK,
                        rowheight=30, font=('Leelawadee UI', 10))
        style.map('Catalog.Treeview', background=[('selected', '#225064')], foreground=[('selected', INK)])
        style.configure('Catalog.Treeview.Heading', background=ALT, foreground=INK, padding=(8, 6),
                        font=('Leelawadee UI', 10, 'bold'))
        style.configure('Catalog.Horizontal.TProgressbar', background=TEAL, troughcolor=ALT, thickness=8)

        header = tk.Frame(self.window.content, bg='#152740', padx=22, pady=14)
        header.pack(fill='x')
        tk.Label(header, text='X-STAGE   /   SONG LIBRARY', bg='#152740', fg=TEAL,
                 font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        tk.Label(header, text='สร้างรายการเพลง', bg='#152740', fg=INK,
                 font=('Leelawadee UI', 20, 'bold')).pack(anchor='w', pady=(3, 0))
        tk.Label(header, text='ไม่คัดลอกไฟล์ · ไม่ซ่อนหรือลบเพลงซ้ำอัตโนมัติ · จัดการภายหลัง',
                 bg='#152740', fg=MUTED, font=('Leelawadee UI', 10),
                 wraplength=820, justify='left').pack(anchor='w', pady=(3, 0))

        body = tk.Frame(self.window.content, bg=BG, padx=20, pady=12)
        body.pack(fill='both', expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(3, weight=1)

        source_card = tk.Frame(body, bg=PANEL, padx=14, pady=10)
        source_card.grid(row=0, column=0, sticky='ew')
        source_card.columnconfigure(0, weight=1)
        tk.Label(source_card, text='โฟลเดอร์ต้นทาง', bg=PANEL, fg=INK,
                 font=('Leelawadee UI', 11, 'bold')).grid(row=0, column=0, columnspan=3, sticky='w', pady=(0, 4))
        ttk.Entry(source_card, textvariable=self.source_text, state='readonly', width=24).grid(
            row=1, column=0, sticky='ew', padx=(0, 8))
        self.pick_button = ttk.Button(source_card, text='เลือกโฟลเดอร์…', command=self._choose_folder)
        self.pick_button.grid(row=1, column=1, padx=(0, 6))
        self.songs_button = ttk.Button(source_card, text='ใช้ Songs', command=self._use_managed)
        self.songs_button.grid(row=1, column=2)

        search_row = tk.Frame(body, bg=BG)
        search_row.grid(row=1, column=0, sticky='ew', pady=(12, 6))
        search_row.columnconfigure(1, weight=1)
        tk.Label(search_row, text='รายการในคลัง', bg=BG, fg=INK,
                 font=('Leelawadee UI', 12, 'bold')).grid(row=0, column=0, sticky='w', padx=(0, 12))
        self.entry = ttk.Entry(search_row, textvariable=self.query, width=20)
        self.entry.grid(row=0, column=1, sticky='ew')
        self.entry.bind('<Return>', lambda _: self.refresh())
        self.window.bind('<Control-f>', self._focus_search)
        ttk.Button(search_row, text='ล้างคำค้น', command=lambda: self.query.set('')).grid(row=0, column=2, padx=(8, 0))
        tk.Label(body, text='ค้นหาชื่อเพลง นักร้อง รหัส หรือคีย์เพลง', bg=BG, fg=MUTED,
                 font=('Leelawadee UI', 9)).grid(row=2, column=0, sticky='w', pady=(0, 5))
        self.query.trace_add('write', self._schedule_search)

        table, self.catalog = scrollable_tree(
            body, style='Catalog.Treeview', columns=('code', 'title', 'artist', 'key'),
            show='headings', height=7, selectmode='browse',
        )
        table.grid(row=3, column=0, sticky='nsew')
        for field, title, width, minimum in (
            ('code', 'รหัส', 85, 58), ('title', 'ชื่อเพลง', 305, 130),
            ('artist', 'นักร้อง', 210, 105), ('key', 'คีย์', 70, 55),
        ):
            self.catalog.heading(field, text=title)
            self.catalog.column(field, width=width, minwidth=minimum, stretch=field in ('title', 'artist'))
        self.catalog.tag_configure('odd', background=ALT)
        pager = tk.Frame(body, bg=BG)
        pager.grid(row=4, column=0, sticky='ew', pady=(5, 0))
        tk.Label(pager, textvariable=self.summary, bg=BG, fg=MUTED,
                 font=('Leelawadee UI', 10)).pack(side='left')
        self.next_button = ttk.Button(pager, text='ถัดไป ›', command=lambda: self._load(self._page + 1))
        self.next_button.pack(side='right')
        self.previous_button = ttk.Button(pager, text='‹ ก่อนหน้า', command=lambda: self._load(self._page - 1))
        self.previous_button.pack(side='right', padx=(0, 6))

        work = tk.Frame(body, bg=PANEL, padx=12, pady=8)
        work.grid(row=5, column=0, sticky='ew', pady=(10, 0))
        work.columnconfigure(0, weight=1)
        tk.Label(work, textvariable=self.status, bg=PANEL, fg=INK, wraplength=790,
                 justify='left', font=('Leelawadee UI', 10, 'bold')).grid(row=0, column=0, sticky='w')
        self.cancel_button = ttk.Button(work, text='ยกเลิกงาน', command=self._cancel)
        self.cancel_button.grid(row=0, column=1, sticky='e')
        self.bar = ttk.Progressbar(work, style='Catalog.Horizontal.TProgressbar', maximum=100)
        self.bar.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(7, 0))
        self.detail_label = tk.Label(work, textvariable=self.progress_detail, bg=PANEL, fg=MUTED,
                                     wraplength=800, justify='left', font=('Leelawadee UI', 9))
        self.detail_label.grid(row=2, column=0, columnspan=2, sticky='w', pady=(4, 0))
        self.bar.grid_remove()
        self.detail_label.grid_remove()

        options = tk.Frame(body, bg=PANEL, padx=12, pady=8)
        options.grid(row=6, column=0, sticky='ew', pady=(8, 0))
        options.columnconfigure(1, weight=1)
        tk.Label(options, text='โหมดสร้างรายการ', bg=PANEL, fg=INK).grid(row=0, column=0, sticky='w', padx=(0, 12))
        self.mode_select = ttk.Combobox(options, state='readonly', width=55,
            values=('สร้างรายการด่วน — ค้นหาได้ก่อน ตรวจซ้ำภายหลัง (แนะนำ)',
                    'ตรวจเพลงซ้ำละเอียด — SHA-256 และรายงาน',
                    'ตรวจทุกไฟล์ — อ่านข้อมูลเพลงทั้งหมด',
                    'สร้างใหม่แบบปลอดภัย — เฉพาะโฟลเดอร์ที่เลือก'))
        self.mode_select.current(0)
        self.mode_select.grid(row=0, column=1, sticky='ew')
        self.mode_select.bind('<<ComboboxSelected>>', lambda _: self.mode.set(('quick', 'fast', 'full', 'safe_rebuild')[self.mode_select.current()]))
        tk.Label(options, text='เพลงที่สงสัยว่าซ้ำ: ระบบจะรายงานเท่านั้น ไม่ซ่อนหรือลบเอง',
                 bg=PANEL, fg=MUTED, wraplength=690, justify='left').grid(
                 row=1, column=0, columnspan=2, sticky='w', pady=(6, 0))
        self.duplicate_select = None  # Duplicate actions are in a separate review window.
        self.shutdown_check = ttk.Checkbutton(options, variable=self.shutdown_after,
            text='ปิดเครื่องเมื่อสำเร็จ — นับถอยหลัง 60 วินาทีและยกเลิกได้ (ค่าเริ่มต้นปิด)')
        self.shutdown_check.grid(row=2, column=0, columnspan=2, sticky='w', pady=(8, 0))

        actions = ActionBar(self.window.footer, padding=(12, 7))
        actions.pack(fill='x')
        self.update_button = ttk.Button(actions, text='เริ่มสร้างรายการ', style='Accent.TButton',
                                        command=lambda: self._start('run'))
        self.rebuild_button = self.update_button  # Backward-compatible widget reference.
        self.clear_button = ttk.Button(actions, text='ล้างรายการทั้งหมด…', command=lambda: self._start('clear'))
        self.report_button = ttk.Button(actions, text='รายงานเพลงซ้ำ', command=self._open_duplicate_report)
        self.repair_reports_button = ttk.Button(actions, text='สร้างรายงานใหม่', command=self._repair_reports)
        self.verify_button = ttk.Button(actions, text='ตรวจเพลงซ้ำละเอียด', command=self._verify_pending)
        self.report_button.state(['!disabled'])
        close_button = ttk.Button(actions, text='ปิด', command=self.hide)
        for button in (self.update_button, self.verify_button, self.clear_button, self.report_button, self.repair_reports_button, close_button):
            button.pack(side='left')
        self.action_buttons = (self.pick_button, self.songs_button, self.update_button,
                               self.clear_button, self.verify_button, self.mode_select,
                               self.shutdown_check, self.repair_reports_button)
        self._set_button_state()

    def _verify_pending(self):
        if self._active or self.app.scanning:
            return
        # Also works if there is no pending queue: a manual full duplicate
        # reconciliation may be useful after a restore or external import.
        self._start('fast')

    def _repair_reports(self):
        if self._active or self.app.scanning:
            return
        self._active = True
        self._cancel_requested = False
        self.app.cancel_scan.clear()
        self.status.set('กำลังสร้างรายงานใหม่จากฐานที่บันทึกไว้ (ไม่อ่านไฟล์เพลง)')
        self._set_button_state()
        self.app.start_catalog_report_repair(self.duplicates.get())

    def _open_duplicate_report(self):
        from .duplicate_dialog import open_exact_duplicates
        open_exact_duplicates(self.app)

    def _focus_search(self, _):
        self.entry.focus_set()
        self.entry.selection_range(0, 'end')
        return 'break'

    def _choose_folder(self):
        start = self.source if self.source.is_dir() else self.source.parent
        folder = filedialog.askdirectory(parent=self.window, initialdir=start, mustexist=True,
                                         title='เลือกโฟลเดอร์ต้นทางเพลง')
        if folder:
            self.source = Path(folder)
            self.source_text.set(str(self.source))

    def _use_managed(self):
        self.source = Path(self.app.managed_catalog_root())
        self.source_text.set(str(self.source))

    def _copy_choice(self, source, managed):
        """Compatibility entry point: v0.9.43 always references original files."""
        return False

    def _start(self, mode):
        if self._active or self.app.scanning:
            return
        if mode == 'run':
            mode = self.mode.get()
        parent = self.window
        try:
            source = self.source.resolve()
            managed = Path(self.app.managed_catalog_root()).resolve()
            copy_external = False
            if mode == 'clear':
                if not messagebox.askyesno('ล้างรายการทั้งหมด',
                        'ล้างรายชื่อเพลงทั้งหมดจากคลังหรือไม่?\nรายการในคิวที่อ้างถึงคลังนี้จะถูกล้างด้วย\n'
                        'ไฟล์เพลงต้นฉบับจะยังอยู่ในตำแหน่งเดิม',
                        parent=parent, default='no'):
                    return
            else:
                if not source.is_dir():
                    messagebox.showwarning('ไม่พบโฟลเดอร์เพลง', f'กรุณาเลือกโฟลเดอร์ที่มีเพลง\n\n{source}', parent=parent)
                    return
                # v0.9.43 never copies source media into Songs. The user may
                # manually place files there and run an index afterward.
                if mode == 'quick' and self.shutdown_after.get():
                    if not messagebox.askyesno('ใช้โหมดตรวจละเอียด',
                            'การปิดเครื่องอัตโนมัติต้องตรวจไฟล์ก่อน เปลี่ยนเป็นโหมดตรวจละเอียดหรือไม่?',
                            parent=parent, default='no'):
                        return
                    mode = 'fast'
                if mode in ('rebuild', 'safe_rebuild'):
                    sources = f'{managed}\n{source}' if copy_external else str(source)
                    if not messagebox.askyesno('สร้างรายการใหม่',
                            f'ตรวจข้อมูลเพลงใหม่เฉพาะแหล่งที่เลือกหรือไม่?\n\n{sources}\n\n'
                            'ระบบจะไม่ลบรายการจากโฟลเดอร์อื่น และจะเก็บประวัติไฟล์ที่หายไว้\n'
                            'ไฟล์เพลงต้นฉบับจะยังอยู่ในตำแหน่งเดิม',
                            parent=parent, default='no'):
                        return
            self._active = True
            self._cancel_requested = False
            self._set_button_state()
            self.update_progress({'phase': 'กำลังเตรียมงาน', 'total': None})
            self.app.start_catalog_maintenance(source, mode, copy_external,
                duplicate_policy=self.duplicates.get(),
                auto_shutdown=self.shutdown_after.get() if mode != 'clear' else False)
        except (OSError, RuntimeError, ValueError, tk.TclError) as error:
            self.finish(error=error)
            self.app.show_error(error)

    def _cancel(self):
        if self._active:
            self._cancel_requested = True
            self.app.cancel_scan.set()
            self.cancel_button.state(['disabled'])
            self.status.set('กำลังยกเลิกงาน…')

    def _set_button_state(self):
        busy = bool(self._active or self.app.scanning)
        if busy != self._busy:
            self._busy = busy
            for button in self.action_buttons:
                button.state(['disabled'] if busy else ['!disabled'])
        self.cancel_button.state(['!disabled'] if self._active and not self._cancel_requested else ['disabled'])

    def _schedule_search(self, *_):
        if self._pending is not None:
            self.window.after_cancel(self._pending)
        self._pending = self.window.after(200, self.refresh)

    def _load(self, page):
        if self._closed:
            return
        if self._pending is not None:
            self.window.after_cancel(self._pending)
            self._pending = None
        self._revision += 1
        revision = self._revision
        if self._future is not None:
            self._future.cancel()
        self._future = self._executor.submit(
            read_page, self.app.library.path, self.query.get(), page,
            lambda: self._closed or revision != self._revision,
        )
        self.previous_button.state(['disabled'])
        self.next_button.state(['disabled'])
        self.summary.set('กำลังอ่านรายการเพลง…')

    def refresh(self):
        self._load(0)

    def _poll(self):
        if self._closed:
            return
        self._set_button_state()
        future = self._future
        if future is not None and future.done():
            self._future = None
            try:
                self._render(*future.result())
            except (sqlite3.Error, OSError) as error:
                self.catalog.delete(*self.catalog.get_children())
                self.summary.set(f'อ่านรายการเพลงไม่ได้ · {error}')
        self._poll_timer = self.window.after(120, self._poll)

    def _render(self, rows, total, found, page):
        self._page = page
        self.catalog.delete(*self.catalog.get_children())
        for index, row in enumerate(rows):
            self.catalog.insert('', 'end', values=tuple(value or '—' for value in row),
                                tags=('odd',) if index % 2 else ())
        pages = max(1, (found + PAGE_SIZE - 1) // PAGE_SIZE)
        if not total:
            self.summary.set('คลังยังว่าง · เลือกโฟลเดอร์แล้วอัปเดตรายการ')
        elif not found:
            self.summary.set(f'ไม่พบเพลงที่ตรงกับคำค้น · คลัง {total:,} เพลง')
        else:
            self.summary.set(f'คลัง {total:,} เพลง · พบ {found:,} รายการ · หน้า {page + 1:,} / {pages:,}')
        self.previous_button.state(['!disabled'] if page else ['disabled'])
        self.next_button.state(['!disabled'] if page + 1 < pages else ['disabled'])

    def update_progress(self, event):
        if self._closed or self._cancel_requested:
            return
        state = event.get('state', event)
        phase = state.get('phase')
        if phase:
            self.status.set(phase)
        if 'total' in state:
            self._phase_total = state['total']
        total = self._phase_total
        done = state.get('done', 0)
        self.bar.grid()
        self.detail_label.grid()
        if total is None:
            if not self._indeterminate:
                self.bar.configure(mode='indeterminate')
                self.bar.start(20)
                self._indeterminate = True
            self.progress_detail.set('กำลังประมวลผล' if not done else f'ตรวจแล้ว {done:,} รายการ')
        else:
            if self._indeterminate:
                self.bar.stop()
                self._indeterminate = False
            value = min(100, max(0, done * 100 / total)) if total else 0
            self.bar.configure(mode='determinate', value=value)
            self.progress_detail.set(f'{value:.0f}% · {done:,} / {total:,} รายการ')

    def finish(self, result=None, error=None, cancelled=False):
        if self._closed:
            return
        self._active = False
        self._cancel_requested = False
        self.bar.stop()
        self._indeterminate = False
        self.bar.grid_remove()
        self._set_button_state()
        if error:
            self.status.set('ดำเนินการไม่สำเร็จ')
            self.progress_detail.set(str(error))
        elif cancelled:
            self.status.set('ยกเลิกงานแล้ว')
            self.progress_detail.set('')
        else:
            self.status.set('เสร็จบางส่วน — ตรวจรายการที่มีข้อผิดพลาด'
                            if getattr(result, 'metrics', {}).get('result_status') == 'partial'
                            else ('ค้นหาเพลงได้แล้ว — ยังรอตรวจเพลงซ้ำละเอียด'
                                  if getattr(result, 'metrics', {}).get('reports_deferred')
                                  else 'ดำเนินการเสร็จแล้ว'))
            if isinstance(result, dict):
                self.progress_detail.set(str(result.get('summary', '')))
            elif result:
                count, skipped, notes = result
                self.progress_detail.set(notes[0] if notes else f'บันทึก {count:,} รายการ · ข้าม {skipped:,} รายการ')
            else:
                self.progress_detail.set('')
        if self.progress_detail.get():
            self.detail_label.grid()
        else:
            self.detail_label.grid_remove()
        self._load(self._page)

    def show(self):
        self.window.deiconify()
        self.window.lift()
        if not self._active:
            self._load(self._page)

    def hide(self):
        self.window.withdraw()

    def _on_destroy(self, event):
        if event.widget is self.window:
            self.close()

    def close(self):
        if self._closed:
            return
        self._closed = True
        for timer in (self._poll_timer, self._pending):
            if timer is not None:
                self.window.after_cancel(timer)
        self._executor.shutdown(wait=False, cancel_futures=True)
