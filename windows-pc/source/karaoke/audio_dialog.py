"""Right-click audio settings and an isolated short SoundFont audition."""
from __future__ import annotations
from .dialog_layout import DialogWindow, ActionBar, scrollable_tree
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from copy import deepcopy
import queue
import logging
import threading
from .soundfont import normalize_audio, inspect_font, PROFILES, PROFILE_NAMES


class AudioSettings(DialogWindow):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title('X-Stage • ระบบเสียง SoundFont')
        self.geometry('940x760')
        self.minsize(420, 360)
        self.configure(bg='#0d172b')
        self.transient(app)
        self.benchmark = None
        self.preview = None
        from .soundfont_preview import Audition
        self.audition_worker=Audition()
        self._preview_poll=None
        self._gain_row=None
        self.timers = []
        from .font_metadata import MetadataLoader
        self._detail_loader=MetadataLoader();self._detail_poll=None;self._detail_token=0
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.bind('<Destroy>', self.on_destroy, add='+')
        try:
            self.options = normalize_audio(app.settings)
        except ValueError as error:
            messagebox.showerror('การตั้งค่าระบบเสียง', str(error), parent=self)
            self.options = normalize_audio({})
        self.fonts = [dict(row) for row in self.options['fonts']]
        style=ttk.Style(self)
        style.configure('Sound.TFrame',background='#10192d')
        style.configure('Sound.TLabel',background='#10192d',foreground='#edf4ff',font=('Tahoma',12))
        style.configure('Sound.Muted.TLabel',background='#10192d',foreground='#a5b6d5',font=('Leelawadee UI',10))
        style.configure('Sound.TNotebook',background='#10192d',borderwidth=0)
        style.map('Sound.TNotebook.Tab',background=[('selected','#22324e')],foreground=[('selected','#78e4ea')])
        style.configure('Sound.TButton',font=('Tahoma',12),padding=(10,7))
        style.configure('SoundAccent.TButton',font=('Tahoma',12,'bold'),padding=(10,7),background='#78e4ea',foreground='#081321')
        style.map('SoundAccent.TButton',background=[('active','#a5f4f5')])
        style.configure('Sound.TCheckbutton',background='#10192d',foreground='#edf4ff',font=('Tahoma',12),padding=6)
        style.configure('Sound.TRadiobutton',background='#10192d',foreground='#edf4ff',font=('Tahoma',12),padding=6)
        style.configure('Sound.TNotebook.Tab',font=('Tahoma',12),padding=(10,8))
        from tkinter.font import Font
        line=Font(self,family='Tahoma',size=11).metrics('linespace')
        style.configure('Sound.Treeview',font=('Tahoma',11),rowheight=max(30,line+12))
        style.configure('Sound.Treeview.Heading',font=('Tahoma',11,'bold'))
        body = ttk.Frame(self.content,style='Sound.TFrame', padding=16)
        body.pack(fill='both', expand=True)
        header=ttk.Frame(body,style='Sound.TFrame');header.pack(fill='x',pady=(0,4))
        try:
            from PIL import Image,ImageTk
            from .branding import asset
            with Image.open(asset('xstage-logo.jpg')) as image:self.logo=ImageTk.PhotoImage(image.resize((52,52)),master=self)
            ttk.Label(header,image=self.logo,style='Sound.TLabel').pack(side='left',padx=(0,12))
        except (OSError,ImportError):pass
        ttk.Label(header,style='Sound.TLabel', text='X-STAGE  •  SOUND STUDIO', font=('Leelawadee UI',18,'bold')).pack(anchor='w')
        ttk.Label(header,style='Sound.Muted.TLabel',text='ชุดเสียงเดียว • ทุกเครื่องดนตรี • เลือกเสียงตามเพลง').pack(anchor='w',pady=4)

        self.mode = tk.StringVar(value=app.settings.get('synth_backend', 'winmm'))
        modes = ttk.Frame(body,style='Sound.TFrame')
        modes.pack(fill='x')
        ttk.Radiobutton(modes,style='Sound.TRadiobutton', text='SoundFont', variable=self.mode, value='bass').pack(side='left', padx=(0, 20))
        ttk.Radiobutton(modes,style='Sound.TRadiobutton', text='Windows MIDI', variable=self.mode, value='winmm').pack(side='left')
        self.backend_note=tk.StringVar()
        def backend_note(*_):
            self.backend_note.set('ใช้เสียงในไฟล์ SoundFont' if self.mode.get()=='bass' else 'Windows MIDI • ยังไม่ใช้ไฟล์ SoundFont')
        self.mode.trace_add('write',backend_note);backend_note()
        ttk.Label(modes,textvariable=self.backend_note,style='Sound.Muted.TLabel').pack(side='right')
        book = self.book = ttk.Notebook(body,style='Sound.TNotebook')
        book.pack(fill='both', expand=True, pady=12)
        fonts_tab = ttk.Frame(book,style='Sound.TFrame', padding=12)
        quality_tab = ttk.Frame(book,style='Sound.TFrame',padding=12)
        effects_tab = ttk.Frame(book,style='Sound.TFrame',padding=12)
        test_tab = ttk.Frame(book,style='Sound.TFrame',padding=12)
        book.add(fonts_tab,text='ชุดเสียง')
        browser_tab=ttk.Frame(book,style='Sound.TFrame',padding=12)
        book.add(browser_tab,text='เสียงทั้งหมดในไฟล์')
        book.add(quality_tab,text='คุณภาพ')
        book.add(effects_tab,text='เอฟเฟกต์')
        book.add(test_tab,text='ทดสอบ')
        # Tab switches preserve user geometry; fit only when opening the dialog.
        book.bind('<<NotebookTabChanged>>',
                  lambda event: logging.info('SOUNDFONT_TAB selected=%s', book.index(book.select())))
        ttk.Label(fonts_tab,style='Sound.TLabel', text='ไฟล์บนมีความสำคัญก่อน • เสียงที่ไม่มีจะค้นจากไฟล์ถัดไป', wraplength=690).pack(anchor='w', pady=(0, 8))
        font_table, self.tree = scrollable_tree(fonts_tab, columns=('name', 'gain'), show='headings', height=4, style='Sound.Treeview', selectmode='browse')
        self.tree.heading('name', text='SoundFont')
        self.tree.heading('gain', text='ระดับเสียง (dB)')
        self.tree.column('name', width=320,minwidth=160)
        self.tree.column('gain', width=150, stretch=False, anchor='center')
        font_table.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', self.selected)
        bar = ActionBar(fonts_tab)
        bar.pack(fill='x', pady=8)
        for label, command in [('เพิ่มไฟล์…', self.add_fonts), ('นำออก', self.remove), ('ขึ้น ↑', lambda: self.move(-1)), ('ลง ↓', lambda: self.move(1))]:
            ttk.Button(bar,style='Sound.TButton', text=label, command=command).pack(side='left', padx=(0, 5))
        self.gain = tk.StringVar(value='-6')
        gainbar = ttk.Frame(fonts_tab,style='Sound.TFrame')
        gainbar.pack(fill='x', pady=4)
        ttk.Label(gainbar,style='Sound.TLabel', text='ระดับไฟล์ (−24 ถึง 0 dB)').pack(side='left')
        ttk.Spinbox(gainbar, from_=-24, to=0, increment=1, textvariable=self.gain, width=6).pack(side='left', padx=8)
        ttk.Button(gainbar,style='Sound.TButton', text='ใช้ระดับนี้', command=self.set_gain).pack(side='left')
        self.detail = tk.StringVar(value='เพิ่มไฟล์ SoundFont แล้วดูทุกเสียงได้ในแท็บเสียงทั้งหมดในไฟล์')
        ttk.Label(fonts_tab,style='Sound.TLabel', textvariable=self.detail, wraplength=680).pack(anchor='w', pady=8)
        self.follow_song=tk.BooleanVar(value=app.settings.get('soundfont_follow_song',not bool(app.settings.get('instrument_fonts'))))
        ttk.Checkbutton(fonts_tab,style='Sound.TCheckbutton',text='ใช้ทุกเสียงในไฟล์ตาม Bank / Program ของเพลง (แนะนำ)',variable=self.follow_song).pack(anchor='w',pady=6)
        ttk.Label(fonts_tab,style='Sound.Muted.TLabel',text='เมื่อเปิดตัวเลือกนี้ จะไม่ใช้การจับคู่เครื่องดนตรีเดิม • ไม่ต้องแยกไฟล์สำหรับดนตรีไทย',wraplength=780).pack(anchor='w')
        self.quality = tk.StringVar(value=str(self.options['quality']))
        self.voices = tk.StringVar(value=str(self.options['voices']))
        self.buffer_ms = tk.StringVar(value=str(self.options['buffer_ms']))
        self.quality_mode = tk.StringVar(value=self.options['quality_mode'])
        automatic = ttk.Frame(quality_tab,style='Sound.TFrame')
        automatic.pack(fill='x', pady=(0, 6))
        ttk.Checkbutton(automatic,style='Sound.TCheckbutton', text='เลือกคุณภาพอัตโนมัติตามเครื่อง (แนะนำ)',
                        variable=self.quality_mode, onvalue='auto', offvalue='manual',
                        command=self.update_auto).pack(anchor='w')
        ttk.Button(automatic,style='Sound.TButton', text='ตรวจสเปกใหม่', command=self.detect_auto).pack(anchor='w',pady=6)
        self.auto_detail = tk.StringVar(value='เปิดอัตโนมัติเพื่อประเมิน CPU, RAM ว่าง และขนาดชุดเสียง')
        ttk.Label(quality_tab,style='Sound.TLabel', textvariable=self.auto_detail, wraplength=590).pack(anchor='w', pady=(0, 8))
        ttk.Button(test_tab,style='Sound.TButton', text='วัดประสิทธิภาพสังเคราะห์เสียง…', command=self.start_benchmark).pack(anchor='w', pady=(0, 8))
        self.quality_controls = []
        profiles = ActionBar(quality_tab)
        profiles.pack(fill='x', pady=(0, 14))
        for key, label in PROFILE_NAMES.items():
            ttk.Button(profiles,style='Sound.TButton', text=label, command=lambda k=key: self.profile(k)).pack(side='left', padx=(0, 8))
        for label, variable, values in [
                ('คุณภาพการแปลงเสียง (0–2)', self.quality, ('0', '1', '2')),
                ('จำนวนเสียงพร้อมกัน', self.voices, ('64', '128', '256', '512', '1024')),
                ('บัฟเฟอร์เสียง (มิลลิวินาที)', self.buffer_ms, ('40', '60', '80', '100', '150', '200'))]:
            row = ttk.Frame(quality_tab,style='Sound.TFrame')
            row.pack(fill='x', pady=6)
            ttk.Label(row,style='Sound.TLabel', text=label).pack(side='left',padx=(0,8))
            control = ttk.Combobox(row, textvariable=variable, values=values, state='readonly', width=9,font=('Tahoma',12))
            control.pack(side='right')
            self.quality_controls.append(control)
        ttk.Label(quality_tab,style='Sound.TLabel', text='สังเคราะห์ที่ 48 kHz / float32 • หากเสียงสะดุด เลือก “เน้นเสียงต่อเนื่อง” (150 ms) • บัฟเฟอร์มากขึ้น เสียงตอบสนองช้าลงเล็กน้อย', wraplength=680).pack(anchor='w', pady=12)
        self.effects_mode = tk.StringVar(value=self.options['effects_mode'])
        ttk.Radiobutton(effects_tab,style='Sound.TRadiobutton', text='รีเวิร์บ/คอรัสตามข้อมูลเพลง', value='song', variable=self.effects_mode).pack(anchor='w')
        ttk.Radiobutton(effects_tab,style='Sound.TRadiobutton', text='กำหนดรีเวิร์บ/คอรัสเองทุกแชนเนล', value='custom', variable=self.effects_mode).pack(anchor='w', pady=5)
        self.reverb = tk.StringVar(value=str(self.options['reverb']))
        self.chorus = tk.StringVar(value=str(self.options['chorus']))
        for label, variable in [('รีเวิร์บ (0–127)', self.reverb), ('คอรัส (0–127)', self.chorus)]:
            row = ttk.Frame(effects_tab,style='Sound.TFrame')
            row.pack(fill='x', pady=5)
            ttk.Label(row,style='Sound.TLabel', text=label).pack(side='left',padx=(0,8))
            ttk.Spinbox(row, from_=0, to=127, textvariable=variable, width=9,font=('Tahoma',12)).pack(side='right')
        ttk.Label(effects_tab,style='Sound.TLabel', text='เริ่มที่ −6 dB ต่อไฟล์เพื่อเผื่อระดับเสียง • ถ้าเสียงแตกให้ลดระดับ SoundFont หรือมาสเตอร์', wraplength=680).pack(anchor='w', pady=12)
        ttk.Label(test_tab,style='Sound.TLabel',text='ทดลองเสียงออกลำโพง',font=('Tahoma',13,'bold')).pack(anchor='w',pady=8)
        previewbar = ttk.Frame(test_tab,style='Sound.TFrame')
        previewbar.pack(fill='x')
        self.note_mode=tk.StringVar(value='ไล่ช่วงโน้ต')
        self.note_first=tk.StringVar(value='48');self.note_last=tk.StringVar(value='72')
        self.build_note_controls(test_tab)
        self.instrument = tk.StringVar(value='เปียโน')
        ttk.Combobox(previewbar, textvariable=self.instrument, values=('เปียโน', 'กีตาร์', 'เบส', 'กลอง'), state='readonly', width=12).pack(side='left',padx=(0,10))
        ttk.Button(previewbar,style='Sound.TButton', text='▶ ทดลองเสียง', command=self.audition).pack(side='left',padx=(0,8))
        ttk.Button(previewbar,style='Sound.TButton', text='■ หยุดทดลอง', command=self.stop_preview).pack(side='left')
        self.status = tk.StringVar(value='บันทึกแล้วใช้กับเพลงถัดไป • ทดลองเสียงเมื่อยกเลิกเพลงปัจจุบันแล้ว (F7)')
        ttk.Label(test_tab,style='Sound.TLabel', textvariable=self.status, wraplength=540).pack(anchor='w', pady=10)
        from .preset_browser import PresetBrowser
        self.browser=PresetBrowser(self,browser_tab)
        self.build_note_controls(browser_tab)
        from .soundfont_check_ui import CoveragePanel
        check_tab=ttk.Frame(book,style='Sound.TFrame',padding=12)
        book.add(check_tab,text='ตรวจเสียงเพลง')
        self.coverage=CoveragePanel(self,check_tab)
        ttk.Label(self.footer,textvariable=self.status,style='Sound.Muted.TLabel',wraplength=840).pack(anchor='w',padx=16,pady=(6,0))
        buttons = ActionBar(self.footer, padding=(16, 10))
        buttons.pack(fill='x')
        ttk.Button(buttons,style='Sound.TButton', text='ดู Log', command=self.open_logs).pack(side='left')
        ttk.Button(buttons,style='Sound.TButton', text='ปิด', command=self.close).pack(side='right')
        ttk.Button(buttons,style='SoundAccent.TButton', text='บันทึกสำหรับเพลงถัดไป', command=self.save).pack(side='right', padx=8)
        self.refresh()
        self.selected()
        self.update_idletasks()
        self.geometry('940x760');self.fit()
        self.restore_view()
        self._initial_state=self.edit_state()
        self.grab_set()
        self.bind('<Unmap>', self.release_hidden_grab, add='+')
        self.bind('<Map>', self.log_visible, add='+')

    def release_hidden_grab(self, event):
        if event.widget is self:
            logging.warning('SOUNDFONT_WINDOW unmapped state=%s', self.state())
            # A withdrawn/iconified modal must not lock the main player's input.
            if self.grab_current() is self:
                self.grab_release()
                logging.info('SOUNDFONT_WINDOW hidden grab released')

    def log_visible(self, event):
        if event.widget is self:
            logging.info('SOUNDFONT_WINDOW mapped state=%s', self.state())

    def open_logs(self):
        from .log_viewer import open_window
        if self.grab_current() is self:self.grab_release()
        open_window(self.app)

    def refresh(self, index=0):
        if hasattr(self,'browser'):self.browser.refresh()
        self.update_auto()
        self.tree.delete(*self.tree.get_children())
        for i, row in enumerate(self.fonts):
            self.tree.insert('', 'end', iid=str(i), values=(Path(row['path']).name, f"{row['gain_db']:g}"))
        if self.fonts:
            self.tree.selection_set(str(min(index, len(self.fonts)-1)))
        else:
            self.cancel_detail()
            self.detail.set('ยังไม่มี SoundFont • กดเพิ่มไฟล์เพื่อเริ่มใช้งาน')

    def index(self):
        selected = self.tree.selection()
        return int(selected[0]) if selected else None

    def selected(self, event=None):
        index=self.index()
        if index is None:return
        row=self.fonts[index]
        if self._gain_row is not row:
            try:self.commit_gain()
            except ValueError as error:
                if self._gain_row in self.fonts:self.tree.selection_set(str(self.fonts.index(self._gain_row)))
                messagebox.showerror('ระดับเสียง',str(error),parent=self);return
            self._gain_row=row
            self.gain.set(f"{row['gain_db']:g}")
        self.request_detail(row['path'])

    def cancel_detail(self):
        poll=self.__dict__.get('_detail_poll')
        if poll is not None:
            self.after_cancel(poll);self._detail_poll=None
        loader=self.__dict__.get('_detail_loader')
        if loader is not None:self._detail_token=loader.cancel()

    def request_detail(self,path):
        self.cancel_detail()
        self.detail.set('กำลังอ่านข้อมูล SoundFont… เลือกไฟล์อื่นหรือปิดหน้าต่างเพื่อยกเลิก')
        self._detail_token=self._detail_loader.submit(path)
        token=self._detail_token
        self._detail_poll=self.after(50,lambda:self.poll_detail(token))

    def poll_detail(self,token):
        if token!=self._detail_token or not self.winfo_exists():return
        self._detail_poll=None
        result=self._detail_loader.take()
        if result is None:
            self._detail_poll=self.after(50,lambda:self.poll_detail(token));return
        current,path,info,error=result
        if current!=token:return
        if error:self.detail.set(str(error));return
        self.detail.set(f"{info['summary']} • {info['size']/1048576:.1f} MB\n{path}")

    def commit_gain(self):
        from .soundfont import bounded
        row=self.__dict__.get('_gain_row')
        if row is not None and any(row is item for item in self.fonts):
            row['gain_db']=bounded(self.gain.get(),-24,0,'ระดับเสียง SoundFont')

    def add_fonts(self):
        try:self.commit_gain()
        except ValueError as error:
            messagebox.showerror('ระดับเสียง',str(error),parent=self);return
        paths = filedialog.askopenfilenames(parent=self, title='เลือก SoundFont', filetypes=[('SoundFont', '*.sf2 *.sfz')])
        candidate = self.fonts + [{'path': path, 'gain_db': -6.0} for path in paths]
        try:
            candidate = normalize_audio({'soundfont_audio': {'fonts': candidate}}, require_files=True)['fonts'] if paths else self.fonts
        except (OSError, ValueError) as error:
            return messagebox.showerror('เพิ่ม SoundFont', str(error), parent=self)
        self.fonts = candidate
        self.refresh(len(self.fonts)-1)
        if paths:
            self.mode.set('bass')

    def remove(self):
        index = self.index()
        if index is not None:
            self.fonts.pop(index)
            self._gain_row=None
            self.refresh(max(0, index-1))

    def move(self, delta):
        try:self.commit_gain()
        except ValueError as error:
            messagebox.showerror('ระดับเสียง',str(error),parent=self);return
        index = self.index()
        if index is not None and 0 <= index+delta < len(self.fonts):
            self.fonts[index], self.fonts[index+delta] = self.fonts[index+delta], self.fonts[index]
            self.refresh(index+delta)

    def set_gain(self):
        from .soundfont import bounded
        index = self.index()
        if index is not None:
            try:
                self.fonts[index]['gain_db'] = bounded(self.gain.get(), -24, 0, 'ระดับเสียง SoundFont')
                self.refresh(index)
            except ValueError as error:
                messagebox.showerror('ระดับเสียง', str(error), parent=self)

    def profile(self, name):
        self.quality_mode.set('manual')
        self.update_auto()
        profile = PROFILES[name]
        self.quality.set(str(profile['quality']))
        self.voices.set(str(profile['voices']))
        self.buffer_ms.set(str(profile['buffer_ms']))

    def benchmark_busy(self):
        return self.benchmark is not None and self.benchmark.running

    def start_benchmark(self):
        if self.audition_worker.busy():
            self.stop_preview();self.status.set('กำลังปิดเสียงทดลอง กรุณารอสักครู่แล้วกดวัดประสิทธิภาพอีกครั้ง');return
        if self.benchmark is not None and self.benchmark.winfo_exists():
            self.benchmark.lift()
            return
        if self.app.engine is not None:
            self.status.set('กด F7 ยกเลิกเพลงปัจจุบันก่อนทดสอบประสิทธิภาพ')
            return
        try:
            self.stop_preview()
            options = self.collect()
            from .soundfont import normalize_audio
            options = normalize_audio({'soundfont_audio': options}, require_files=True)
            from .audio_benchmark_dialog import BenchmarkWindow
            self.benchmark = BenchmarkWindow(self, options)
        except (OSError, ValueError) as error:
            messagebox.showerror('ทดสอบเสียง', str(error), parent=self)

    def detect_auto(self):
        self.quality_mode.set('auto')
        self.update_auto()

    def update_auto(self):
        from .audio_auto import recommend, summary
        auto = self.quality_mode.get() == 'auto'
        for control in self.quality_controls:
            control.configure(state='disabled' if auto else 'readonly')
        if auto:
            result = recommend(self.fonts)
            self.quality.set(str(result['quality']))
            self.voices.set(str(result['voices']))
            self.buffer_ms.set(str(result['buffer_ms']))
            self.auto_detail.set(summary(result))
        else:
            self.auto_detail.set('กำหนดเอง • โปรไฟล์สำเร็จรูปจะปิดโหมดอัตโนมัติ')

    def collect(self, validate_files=True):
        self.commit_gain()
        if self.quality_mode.get() == 'auto':
            self.update_auto()
        return normalize_audio({'soundfont_audio': {
            'quality_mode': self.quality_mode.get(),
            'fonts': self.fonts, 'quality': self.quality.get(), 'voices': self.voices.get(),
            'buffer_ms': self.buffer_ms.get(), 'effects_mode': self.effects_mode.get(),
            'reverb': self.reverb.get(), 'chorus': self.chorus.get(),
        }}, require_files=validate_files and self.mode.get() == 'bass')

    def save(self):
        if self.benchmark_busy():
            return
        previous=dict(self.app.settings)
        try:
            options = self.collect()
            if self.mode.get() == 'bass':
                from .bass import BassSynth
                for name in ('bass.dll', 'bassmidi.dll'):
                    BassSynth.validate_dll(self.app.home/'native'/'x64'/name)
            self.stop_preview()
            from .font_mapping import retained_mapping
            self.app.settings['instrument_fonts']=retained_mapping(self.app.settings.get('instrument_fonts',{}),options['fonts'])
            if hasattr(self,'follow_song'):self.app.settings['soundfont_follow_song']=self.follow_song.get()
            self.app.settings.update(synth_backend=self.mode.get(), soundfont_audio=options,
                                     soundfont=options['fonts'][0]['path'] if options['fonts'] else '')
            self.app.save_settings()
            from .font_mapping import refresh_waiting_audio
            refresh_waiting_audio(self.app)
        except (OSError, ValueError) as error:
            self.app.settings.clear();self.app.settings.update(previous)
            return messagebox.showerror('บันทึกระบบเสียง', str(error), parent=self)
        if hasattr(self,'remember_view'):self.remember_view()
        self.app.status_var.set('บันทึกระบบเสียงแล้ว ใช้กับเพลงถัดไป')
        self.destroy()

    def build_note_controls(self,parent):
        row=ttk.Frame(parent,style='Sound.TFrame');row.pack(fill='x',pady=6)
        ttk.Label(row,text='ทดลอง',style='Sound.Muted.TLabel').pack(side='left',padx=(0,6))
        ttk.Combobox(row,textvariable=self.note_mode,values=('โน้ตเดียว','ไล่ช่วงโน้ต','คอร์ดเมเจอร์'),state='readonly',width=14).pack(side='left')
        for label,var in [('เริ่ม',self.note_first),('ถึง',self.note_last)]:
            ttk.Label(row,text=label,style='Sound.Muted.TLabel').pack(side='left',padx=6)
            ttk.Spinbox(row,from_=0,to=127,textvariable=var,width=5).pack(side='left')
        ttk.Label(row,text='MIDI 0–127 • 60 = C4',style='Sound.Muted.TLabel').pack(side='left',padx=8)

    def audition(self,preset=None):
        if self.benchmark_busy():return
        if self.app.engine is not None:
            self.status.set('หยุดเพลงปัจจุบันก่อนทดลองเสียง');return
        try:
            from .soundfont_preview import note_groups
            groups=note_groups(self.note_mode.get(),self.note_first.get(),self.note_last.get())
            options=self.collect(validate_files=False)
            from .font_mapping import retained_mapping
            settings={'soundfont_audio':options,'instrument_fonts':retained_mapping(self.app.settings.get('instrument_fonts',{}),options['fonts']),
                      'soundfont_follow_song':self.follow_song.get()}
            instrument=self.instrument.get();channel=9 if instrument=='กลอง' else 0
            program={'เปียโน':0,'กีตาร์':24,'เบส':32,'กลอง':0}[instrument]
            if preset:channel=9 if preset[1]==128 else 0;program=0;instrument=preset[3]
            self.stop_preview();self._preview_error=False
            self._preview_name=instrument
            self.audition_worker.start(self.app.home/'native'/'x64',deepcopy(settings),preset,channel,program,groups)
            self.status.set('กำลังโหลดเสียงทดลองเบื้องหลัง… กดหยุดได้')
            self._poll_preview()
        except (OSError,ValueError) as error:
            self.status.set(str(error))

    def _poll_preview(self):
        self._preview_poll=None
        if not self.winfo_exists():return
        if self.app.engine is not None:self.stop_preview();return
        finished=False
        while True:
            try:token,state,detail=self.audition_worker.events.get_nowait()
            except queue.Empty:break
            if token!=self.audition_worker.serial:continue
            if state=='error':self._preview_error=True;self.status.set('ทดลองเสียงไม่สำเร็จ: '+detail)
            elif state=='playing':self.status.set('กำลังทดลอง: '+self._preview_name)
            elif state=='finished':
                finished=True
                if not self._preview_error:self.status.set('ทดลองเสร็จแล้ว • ยังไม่เปลี่ยนการตั้งค่าของเพลง')
        if not finished:self._preview_poll=self.after(50,self._poll_preview)

    def stop_preview(self):
        self.audition_worker.stop()
        if self._preview_poll is not None:
            self.after_cancel(self._preview_poll);self._preview_poll=None
        if self.winfo_exists() and hasattr(self,'status'):self.status.set('หยุดทดลองแล้ว • หากกำลังโหลด จะคืนทรัพยากรเมื่อโหลดสิ้นสุด')

    def edit_state(self):
        from .soundfont import bounded
        names=('mode','quality','voices','buffer_ms','quality_mode','effects_mode','reverb','chorus','follow_song')
        fonts=deepcopy(self.fonts);invalid=None
        for i,row in enumerate(self.fonts):
            if row is self._gain_row:
                try:fonts[i]['gain_db']=bounded(self.gain.get(),-24,0,'ระดับเสียง SoundFont')
                except ValueError:invalid=self.gain.get()
        return (fonts,tuple(getattr(self,n).get() for n in names),invalid)

    def remember_view(self):
        selected=self.browser.tree.selection()
        preset=self.browser.visible[int(selected[0])][:2] if selected else None
        self.app.__dict__['_soundfont_view']={'query':self.browser.query.get(),'path':self.browser.path,
            'bank':self.browser.bank.get(),'preset':preset,'tab':self.book.index(self.book.select()),
            'notes':(self.note_mode.get(),self.note_first.get(),self.note_last.get())}

    def restore_view(self):
        state=self.app.__dict__.get('_soundfont_view',{})
        if not state:return
        self.browser.path=state.get('path');self.browser.refresh()
        self.browser.query.set(state.get('query',''))
        self.browser.restore_selection(state)
        index=state.get('tab',0)
        if 0<=index<len(self.book.tabs()):self.book.select(index)
        for var,value in zip((self.note_mode,self.note_first,self.note_last),state.get('notes',())):var.set(value)

    def on_destroy(self, event):
        if event.widget is self:
            self.cancel_detail()
            loader=self.__dict__.get('_detail_loader')
            if loader is not None:loader.close()
            logging.info('SOUNDFONT_WINDOW destroyed')
            self.stop_preview()
            if hasattr(self,'coverage'):self.coverage.close()

    def close(self):
        logging.info('SOUNDFONT_WINDOW close requested')
        self.stop_preview()
        if self.benchmark_busy():
            self.benchmark.close()
            return
        if self.edit_state()!=self._initial_state:
            answer=messagebox.askyesnocancel('ยังไม่ได้บันทึก','บันทึกการตั้งค่าระบบเสียงก่อนปิดหรือไม่?',parent=self)
            if answer is None:return
            if answer:self.save();return
        self.remember_view()
        self.stop_preview()
        self.destroy()
