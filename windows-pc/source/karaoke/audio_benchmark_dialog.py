"""Background calibration; all Tk calls stay on the GUI thread."""
from __future__ import annotations
import json
import queue
import threading
import time
from datetime import datetime
from tkinter import ttk, messagebox
from .dialog_layout import DialogWindow, ActionBar
import tkinter as tk
from .audio_benchmark import run, Cancelled


class BenchmarkWindow(DialogWindow):
    def __init__(self, parent, options):
        super().__init__(parent)
        self.owner = parent
        self.options = options
        self.result = None
        self.running = True
        self.started = time.monotonic()
        self.closing = False
        self.cancel = threading.Event()
        self.messages = queue.Queue()
        self.title('ทดสอบประสิทธิภาพสังเคราะห์เสียงจริง')
        self.geometry('820x540')
        self.minsize(700, 480)
        self.transient(parent)
        self.protocol('WM_DELETE_WINDOW', self.close)
        body = ttk.Frame(self.content, padding=18)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='ทดสอบด้วย SoundFont ที่เลือก', font=('Leelawadee UI',16,'bold')).pack(anchor='w')
        ttk.Label(body, text='สร้าง PCM จริงแบบไม่ส่งเสียงออกลำโพง • ทดสอบ 3 ระดับคุณภาพ\n'
                  'ไม่ใช่การวัดไดรเวอร์เสียงหรือการรับรองว่าทุกเพลงจะไม่กระตุก', wraplength=740).pack(anchor='w', pady=8)
        self.status = tk.StringVar(value='กำลังเตรียมระบบเสียง…')
        ttk.Label(body, textvariable=self.status, wraplength=740).pack(anchor='w', pady=5)
        self.elapsed = tk.StringVar(value='เริ่มทดสอบ…')
        ttk.Label(body, textvariable=self.elapsed).pack(anchor='w')
        self.bar = ttk.Progressbar(body, maximum=100)
        self.bar.pack(fill='x', pady=8)
        self.table = ttk.Treeview(body, columns=('quality','mean','p95','worst','cold','pass'),
                                  show='headings', height=4)
        for name, title in zip(self.table['columns'],
                ('คุณภาพ/เสียง','เฉลี่ย ms','95% ms','สูงสุด ms','แรกโหลด ms','ผล')):
            self.table.heading(name, text=title)
            self.table.column(name, width=110, anchor='center')
        self.table.pack(fill='both', expand=True)
        ttk.Label(body, text='วัดต่อเสียง 10 ms: ผ่านเมื่อเฉลี่ย ≤ 3.5, ช่วง 95% ≤ 5, สูงสุด ≤ 9 ms\n'
                  'เผื่อกำลังประมวลผลให้โปรแกรม • คอลัมน์แรกโหลดแยกจากเกณฑ์ช่วงต่อเนื่อง\n'
                  'ค่าบัฟเฟอร์เป็นค่าตั้งต้น ไม่ได้วัด latency ของอุปกรณ์', wraplength=740).pack(anchor='w', pady=8)
        self.report_path = tk.StringVar()
        ttk.Label(body, textvariable=self.report_path, wraplength=740).pack(anchor='w')
        buttons = ActionBar(self.footer, padding=(16, 10))
        buttons.pack(fill='x', pady=8)
        self.apply_button = ttk.Button(buttons, text='ใช้ค่าที่ผ่านการทดสอบ', command=self.apply, state='disabled')
        self.apply_button.pack(side='right')
        self.close_button = ttk.Button(buttons, text='ยกเลิกการทดสอบ', command=self.close)
        self.close_button.pack(side='right', padx=8)
        # Snapshot UI values and paths before starting the worker.
        native = parent.app.home/'native'/'x64'
        report_dir = parent.app.data_dir/'audio-reports'
        def work():
            try:
                result = run(native, options, self.cancel,
                             lambda value: self.messages.put(('progress', value)))
                path = None
                save_error = None
                try:
                    report_dir.mkdir(parents=True, exist_ok=True)
                    path = report_dir/('benchmark-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.json')
                    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                except OSError as error:
                    save_error = str(error)
                self.messages.put(('result',(result, path, save_error)))
            except Cancelled:
                self.messages.put(('cancelled', None))
            except Exception as error:
                self.messages.put(('error', str(error)))
        self.worker = threading.Thread(target=work, daemon=True, name='soundfont-benchmark')
        self.worker.start()
        self.grab_set()
        self.after(100, self.poll)

    def poll(self):
        seconds = int(time.monotonic()-self.started)
        self.elapsed.set(f'ใช้เวลา {seconds} วินาที • '+('กำลังทำงาน '+'.'*(seconds%3+1) if self.running else 'เสร็จสิ้น'))
        try:
            while True:
                kind, value = self.messages.get_nowait()
                if kind == 'progress':
                    self.bar['value'] = value['percent']
                    if not self.closing:
                        self.status.set(f"{value['percent']:.0f}% • "+value['text'])
                else:
                    self.running = False
                    self.close_button.configure(text='ปิด')
                    if kind == 'result':
                        self.result, path, save_error = value
                        self.bar['value'] = 100
                        for row in self.result['rows']:
                            s = row['settings']
                            self.table.insert('', 'end', values=(f"{s['quality']} / {s['voices']}",
                                *(f"{row[k]:.2f}" for k in ('mean_ms','p95_ms','worst_ms','initial_worst_ms')),
                                'ผ่าน' if row['passed'] else 'ไม่ผ่าน'))
                        if self.result['recommended']:
                            self.status.set('เสร็จแล้ว • เลือกคุณภาพสูงสุดที่ผ่านใน 3 ระดับที่ทดสอบ')
                            self.apply_button.configure(state='normal')
                        else:
                            self.status.set('ไม่มีระดับที่ผ่านเกณฑ์ • ไม่เปลี่ยนการตั้งค่าเดิม')
                        self.report_path.set('รายงาน: '+str(path) if not save_error else 'บันทึกรายงานไม่ได้: '+save_error)
                    elif kind == 'cancelled':
                        self.status.set('ยกเลิกแล้ว • ไม่เปลี่ยนการตั้งค่า')
                    else:
                        self.status.set('ทดสอบไม่สำเร็จ: '+value)
        except queue.Empty:
            pass
        if self.closing and not self.running:
            self.destroy()
            self.owner.grab_set()
        elif self.running:
            self.after(100, self.poll)

    def apply(self):
        if self.running or not self.result or not self.result['recommended']:
            return
        # Keep measured values in manual mode, so the spec heuristic cannot
        # overwrite them at the next song. Saving remains the user's action.
        settings = self.result['recommended']
        self.owner.quality_mode.set('manual')
        self.owner.update_auto()
        for name in ('quality','voices','buffer_ms'):
            getattr(self.owner, name).set(str(settings[name]))
        self.owner.auto_detail.set('ใช้ผลทดสอบ PCM • ค่าคงที่ • กดบันทึกสำหรับเพลงถัดไป')
        self.owner.status.set('นำค่าทดสอบมาใส่แล้ว กรุณาบันทึกสำหรับเพลงถัดไป')
        self.close()

    def close(self):
        if self.running:
            self.closing = True
            self.cancel.set()
            self.status.set('กำลังยกเลิก… รอคำสั่งโหลด/ประมวลผลเสียงปัจจุบันเสร็จ')
            self.close_button.configure(state='disabled')
            return
        self.destroy()
        self.owner.grab_set()
