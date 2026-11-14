"""One local setup window; a failed optional EQ never blocks karaoke playback."""
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
import webbrowser
from .dialog_layout import DialogWindow, ActionBar
from . import first_run, system_eq


class SetupWindow(DialogWindow):
    def __init__(self, app, reason='first_run'):
        super().__init__(app)
        self.app = app
        self.title('ตั้งค่า X-Stage · เลือกอุปกรณ์และทดสอบเสียง')
        self.geometry('780x680')
        self.rows = []
        self.jobs = queue.Queue()
        self.busy = False
        self.tested_device = None
        self.poll_id = None
        self.selector = None
        self.selector_job = None
        self.heard = tk.BooleanVar(value=False)
        self.use_eq = tk.BooleanVar(value=False)
        self.eq_checked = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value='กำลังตรวจอุปกรณ์เสียง')
        title = {'new_machine': 'พบว่ากำลังใช้เครื่องใหม่',
                 'default_changed': 'เอาต์พุตหลักของ Windows เปลี่ยนไป',
                 'missing_device': 'อุปกรณ์เสียงเดิมไม่พร้อมใช้งาน'}.get(reason, 'ตั้งค่าเสียงสำหรับเครื่องนี้')
        ttk.Label(self.content, text=title, font=('Leelawadee UI', 18, 'bold')).pack(anchor='w', padx=18, pady=14)
        ttk.Label(self.content, text='เลือกอุปกรณ์ → ทดสอบเสียง → พร้อมใช้', wraplength=680).pack(anchor='w', padx=18)
        ttk.Label(self.content, text='1. เลือกลำโพงหรือการ์ดเสียง', font=('Leelawadee UI', 13, 'bold')).pack(anchor='w', padx=18, pady=(18, 6))
        self.combo = ttk.Combobox(self.content, state='readonly', width=55)
        self.combo.pack(fill='x', padx=18)
        self.combo.bind('<<ComboboxSelected>>', self.changed)
        bar = ActionBar(self.content)
        bar.pack(fill='x', padx=12, pady=6)
        for label, command in [('ตรวจอุปกรณ์ใหม่', self.refresh), ('ทดสอบเสียง', self.tone),
                               ('เปิดการตั้งค่าเสียง Windows', self.windows_sound)]:
            ttk.Button(bar, text=label, command=command).pack(side='left')
        ttk.Label(self.content, text='เพลงจะใช้เอาต์พุตหลักของ Windows กรุณาเลือกอุปกรณ์เดียวกัน\nเสียงทดสอบสั้นและเบา โดยไม่เปลี่ยนระดับเสียง Windows', wraplength=680).pack(anchor='w', padx=18)
        ttk.Checkbutton(self.content, text='ได้ยินเสียงจากอุปกรณ์ที่เลือกแล้ว', variable=self.heard).pack(anchor='w', padx=18, pady=8)
        ttk.Label(self.content, text='EQ X-Stage พร้อมปรับจากเมนูเครื่องมือ → EQ X-Stage ไม่ต้องติดตั้ง Equalizer APO', wraplength=680).pack(anchor='w', padx=18, pady=12)
        ttk.Label(self.content, text='2. ย้ายข้อมูลจากเครื่องเดิม', font=('Leelawadee UI', 13, 'bold')).pack(anchor='w', padx=18, pady=(14, 5))
        transfer = ActionBar(self.content)
        transfer.pack(fill='x', padx=12)
        ttk.Button(transfer, text='สำรองคลังเพลง คิว และ Preset', command=app.backup_data).pack(side='left')
        ttk.Button(transfer, text='นำเข้าชุดสำรองเดิม', command=app.restore_data).pack(side='left')
        ttk.Button(transfer, text='เปิด Preset จากเครื่องเดิม', command=self.imported_preset).pack(side='left')
        ttk.Label(self.content, text='ชุดสำรองเก็บรายการเพลงและการตั้งค่า ไม่รวมไฟล์เพลงและ SoundFont\nย้ายเครื่องแล้วต้องเลือกอุปกรณ์ใหม่ ส่วน Preset เดิมเก็บไว้ให้เลือกนำเข้าเอง', wraplength=680).pack(anchor='w', padx=18, pady=6)
        ttk.Label(self.content, textvariable=self.status, wraplength=680).pack(anchor='w', padx=18, pady=12)
        actions = ActionBar(self.footer)
        actions.pack(fill='x', padx=12, pady=10)
        ttk.Button(actions, text='บันทึกและพร้อมใช้', command=self.finish).pack(side='left')
        ttk.Button(actions, text='ใช้คาราโอเกะก่อน', command=self.defer).pack(side='left')
        self.protocol('WM_DELETE_WINDOW', self.defer)
        self.bind('<Destroy>', self.cleanup_setup, add='+')
        self.after_idle(self.refresh)

    def run_job(self, action, done):
        if self.busy:
            self.status.set('กำลังดำเนินการ กรุณารอสักครู่')
            return
        self.busy = True
        def worker():
            try:
                self.jobs.put((True, action(), done))
            except Exception as error:
                self.jobs.put((False, str(error), done))
        threading.Thread(target=worker, daemon=True, name='xstage-audio-setup').start()
        self.poll_id = self.after(100, self.poll)

    def poll(self):
        self.poll_id = None
        try:
            ok, result, done = self.jobs.get_nowait()
        except queue.Empty:
            self.poll_id = self.after(100, self.poll)
            return
        self.busy = False
        if ok:
            done(result)
        else:
            self.status.set(result + '\nยังเล่นคาราโอเกะได้ โดยเลือก «ใช้คาราโอเกะก่อน»')

    def selected(self):
        index = self.combo.current()
        if not 0 <= index < len(self.rows):
            raise ValueError('กรุณาเลือกอุปกรณ์เสียงก่อน')
        return self.rows[index]

    def changed(self, event=None):
        self.heard.set(False)
        self.eq_checked.set(False)
        self.tested_device = None

    def refresh(self):
        def complete(rows):
            self.rows = rows
            self.combo.configure(values=[name + (' · ค่าเริ่มต้น Windows' if default else '') for _, name, default in rows])
            if rows:
                self.combo.current(next((i for i, row in enumerate(rows) if row[2]), 0))
            self.changed()
            try:
                installed = system_eq.installation()
                text = 'พบ Equalizer APO · ' + ('เชื่อมไฟล์ X-Stage แล้ว' if system_eq.linked(installed) else 'ยังไม่เชื่อม X-Stage')
            except OSError:
                text = 'ยังไม่ได้ติดตั้ง Equalizer APO · ใช้คาราโอเกะก่อนได้'
            self.status.set(text if rows else 'ไม่พบอุปกรณ์เสียง กรุณาต่ออุปกรณ์แล้วตรวจใหม่')
        self.run_job(first_run.enumerate_devices, complete)

    def tone(self):
        try:
            device = self.selected()[0]
        except ValueError as error:
            self.status.set(str(error)); return
        self.heard.set(False)
        self.tested_device = None
        self.status.set('กำลังส่งเสียงทดสอบไปยังอุปกรณ์ที่เลือก')
        def done(_):
            if self.selected()[0] == device:
                self.tested_device = device
                self.status.set('ส่งเสียงทดสอบแล้ว หากได้ยินให้ทำเครื่องหมายยืนยัน')
        self.run_job(lambda: first_run.test_tone(device), done)

    def windows_sound(self):
        import os
        try:
            os.startfile('ms-settings:sound')
        except OSError as error:
            self.status.set(str(error))

    def install_apo(self):
        from .offline_components import validate_component
        try:
            try:
                system_eq.installation()
            except OSError:
                pass
            else:
                self.status.set('มี Equalizer APO แล้ว เลือก «เลือกอุปกรณ์และทดสอบ EQ» ได้เลย'); return
            if self.selector is not None and self.selector.poll() is None:
                self.status.set('กรุณาปิดหน้าต่างตั้งค่าเสียงเดิมก่อน'); return
            package = validate_component(Path(self.app.home) / 'offline')
            script = Path(self.app.home) / 'tools' / 'Install-EqualizerAPO.ps1'
            self.selector = first_run.open_tool(self.app, script.name, ['-OfflineRoot', str(package.parent)])
            self.status.set('กำลังเปิดตัวติดตั้ง Equalizer APO กรุณายืนยัน UAC และทำตามหน้าต่างติดตั้ง')
            self.watch_process('ติดตั้งเสร็จแล้ว ให้ตรวจอุปกรณ์ใหม่')
        except (OSError, ValueError) as error:
            self.status.set(str(error))
            if messagebox.askyesno('ส่วนประกอบออฟไลน์ยังไม่พร้อม', 'เปิดเว็บไซต์ Equalizer APO เพื่อดาวน์โหลดจากโครงการทางการ?', parent=self):
                webbrowser.open('https://sourceforge.net/projects/equalizerapo/')

    def selector_open(self):
        try:
            if self.selector is not None and self.selector.poll() is None:
                self.status.set('กรุณาปิดหน้าต่างตั้งค่าเสียงเดิมก่อน'); return
            self.selector = system_eq.open_selector()
            self.eq_checked.set(False)
            self.status.set('เลือกอุปกรณ์ชื่อเดียวกับด้านบนใน Device Selector และทดสอบตามคำแนะนำ')
            self.watch_process('ปิด Device Selector แล้ว กรุณาทดสอบเสียงและยืนยันผล EQ')
        except (OSError, ValueError) as error:
            self.status.set(str(error))

    def connect(self):
        try:
            if self.selector is not None and self.selector.poll() is None:
                self.status.set('กรุณาปิดหน้าต่างตั้งค่าเสียงเดิมก่อน'); return
            self.selector = first_run.open_tool(self.app, 'Setup-System-EQ.ps1', ['-NoPause'])
            self.status.set('กำลังเชื่อม X-Stage กรุณายืนยันสิทธิ์ Windows เมื่อร้องขอ')
            self.watch_process('เชื่อมไฟล์แล้ว ยังต้องทดสอบ EQ ใน Device Selector ก่อนยืนยัน')
        except OSError as error:
            self.status.set(str(error))

    def watch_process(self, success):
        if self.selector_job is not None:
            self.after_cancel(self.selector_job)
        def poll():
            self.selector_job = None
            code = self.selector.poll()
            if code is None:
                self.selector_job = self.after(400, poll)
            else:
                self.status.set(success if code == 0 else ('ส่วน EQ ยังไม่พร้อม (รหัส '+str(code)+') · ยังใช้คาราโอเกะได้'))
        self.selector_job = self.after(400, poll)

    def imported_preset(self):
        from .eq_model import validate
        from .eq_ui import open_window
        curves = self.app.settings.get('imported_audio_presets', {})
        candidate = curves.get('system_eq') or curves.get('parametric_eq')
        if candidate is None:
            self.status.set('ไม่มี Preset EQ 8 ย่านจากเครื่องเดิมให้เปิด'); return
        try:
            state = validate(candidate)
            editor = open_window(self.app)
            editor.checkpoint()
            editor.state = state
            editor.load_band()
            editor.dirty()
            editor.status.set('Preset จากเครื่องเดิม · ยังไม่เปลี่ยนเสียง เลือกอุปกรณ์และตรวจค่าก่อนกดใช้ค่า')
        except (ValueError, OSError) as error:
            self.status.set(str(error))

    def finish(self):
        if self.busy:
            self.status.set('กรุณารอให้การทดสอบเสร็จก่อน'); return
        try:
            device, name, _ = self.selected()
            if self.tested_device != device:
                raise ValueError('กรุณากดทดสอบเสียงกับอุปกรณ์ที่เลือกก่อน')
            first_run.save_choice(self.app, device, name, self.use_eq.get(), self.heard.get(), self.eq_checked.get())
            self.app._audio_setup_needs_device = False
            self.app.status_var.set('ตั้งค่าเสียงแล้ว: ' + name + (' · EQ ต้องยืนยันด้วยการฟัง' if self.use_eq.get() else ' · ใช้คาราโอเกะได้'))
            self.destroy()
        except (OSError, ValueError) as error:
            self.status.set(str(error))

    def defer(self):
        # Do not persist a failed or untested setup as successful.
        self.app.status_var.set('เล่นคาราโอเกะได้ · ตั้งค่าเสียงให้เสร็จภายหลังจากเมนูตั้งค่าเสียง')
        self.destroy()

    def cleanup_setup(self, event):
        if event.widget is self:
            for timer in (self.poll_id, self.selector_job):
                if timer is not None:
                    self.after_cancel(timer)


def open_setup(app, reason='first_run'):
    window = getattr(app, '_first_run_window', None)
    if window is not None and window.winfo_exists():
        window.lift()
        return window
    app._first_run_window = SetupWindow(app, reason)
    return app._first_run_window


def schedule_startup(app, force=False):
    results = queue.Queue()
    warned = set()
    first_check = True
    def worker():
        try:
            rows = first_run.enumerate_devices()
            state = first_run.read_state(app.data_dir)
            reason = first_run.setup_reason(state, [r[0] for r in rows])
            default = next((row[0] for row in rows if row[2]), None)
            if reason is None and state.get('device') and default != state['device']:
                reason = 'default_changed'
            results.put((reason, state.get('device'), None))
        except Exception as error:
            results.put((None, None, str(error)))
    def start_check():
        if app.closing:
            return
        threading.Thread(target=worker, daemon=True, name='xstage-check-device').start()
        app.after(100, poll)
    def poll():
        nonlocal first_check
        if app.closing:
            return
        try:
            reason, device, error = results.get_nowait()
        except queue.Empty:
            app.after(100, poll); return
        forced = force and first_check
        first_check = False
        app._audio_setup_needs_device = reason in ('new_machine', 'missing_device', 'default_changed')
        if error:
            app.status_var.set('ยังตรวจอุปกรณ์เสียงไม่ได้: ' + error + ' · เล่นคาราโอเกะก่อนได้')
        if forced:
            open_setup(app, reason or 'first_run')
            warned.add((reason or 'first_run', device))
        elif reason and (reason, device) not in warned:
            warned.add((reason, device))
            open_setup(app, reason)
        elif not reason and not error:
            warned.clear()
        app.after(8000, start_check)
    app.after(350, start_check)
