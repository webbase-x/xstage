import queue
import subprocess
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from .dialog_layout import DialogWindow,ActionBar
from .support_report import MANUAL,manual_results
from .library import read_json,write_json

def command(home,data,destination,executable=None,frozen=None):
    executable=executable or sys.executable
    frozen=getattr(sys,'frozen',False) if frozen is None else frozen
    return [executable]+([] if frozen else [str(Path(home)/'main.py')])+['--system-report',str(destination),'--data-dir',str(data)]

def open_window(app):
    old=getattr(app,'_support_window',None)
    if old is not None and old.winfo_exists():old.lift();return old
    window=DialogWindow(app);app._support_window=window;window.title('รายงานตรวจระบบและผลทดสอบ Windows');window.geometry('820x600')
    ttk.Label(window.content,text='ผลด้านล่างให้ผู้ทดสอบเลือกตามที่ตรวจจริง • รายงานไม่เล่นเสียงและไม่เปลี่ยนระบบ',wraplength=740,padding=12).pack(fill='x')
    data=Path(app.data_dir);saved=manual_results(read_json(data/'manual-checks.json',{}));fields={}
    for name,label in MANUAL.items():
        frame=ttk.LabelFrame(window.content,text=label,padding=8);frame.pack(fill='x',padx=12,pady=6)
        state=tk.StringVar(value=saved[name]['status']);note=tk.StringVar(value=saved[name]['note'])
        ttk.Combobox(frame,textvariable=state,values=('ยังไม่ทดสอบ','ผ่าน','พบปัญหา'),state='readonly',width=18).pack(anchor='w')
        ttk.Label(frame,text='รายละเอียด เช่น ระยะเวลาทดสอบ รุ่นอุปกรณ์ อาการและขั้นตอนที่พบ').pack(anchor='w',pady=(4,0))
        ttk.Entry(frame,textvariable=note).pack(fill='x');fields[name]=(state,note)
    status=tk.StringVar(value='รายงานอาจมีชื่ออุปกรณ์และตำแหน่งติดตั้ง ไม่มีรหัสรีโมทหรือฐานรายการเพลง')
    ttk.Label(window.footer,textvariable=status,wraplength=740,padding=8).pack(fill='x')
    progress=ttk.Progressbar(window.footer,mode='indeterminate');progress.pack(fill='x',padx=12)
    results=queue.Queue();busy=False
    def save():
        value={name:{'status':state.get(),'note':note.get()} for name,(state,note) in fields.items()}
        write_json(data/'manual-checks.json',manual_results(value))
    def save_only():
        try:save();status.set('บันทึกผลที่ผู้ทดสอบระบุแล้ว')
        except Exception as error:messagebox.showerror('บันทึกไม่ได้',str(error),parent=window)
    def export():
        nonlocal busy
        if busy:return
        path=filedialog.asksaveasfilename(parent=window,defaultextension='.json',initialfile='XStage-system-report.json')
        if not path:return
        try:save()
        except Exception as error:messagebox.showerror('บันทึกไม่ได้',str(error),parent=window);return
        busy=True;button.configure(state='disabled');progress.start(12);status.set('กำลังตรวจส่วนประกอบและอุปกรณ์เสียง… ไม่เล่นเสียงทดสอบ')
        def worker():
            try:
                result=subprocess.run(command(app.home,data,path),capture_output=True,text=True,timeout=90,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if result.returncode!=0:raise RuntimeError(result.stderr or 'ตรวจระบบไม่สำเร็จ')
                if not Path(path).is_file():raise RuntimeError('ไม่พบไฟล์รายงาน')
                results.put('สร้างรายงานแล้ว: '+path)
            except Exception as error:results.put('สร้างรายงานไม่สำเร็จ: '+str(error))
        threading.Thread(target=worker,daemon=True).start()
    bar=ActionBar(window.footer);bar.pack(fill='x',padx=8,pady=8)
    ttk.Button(bar,text='บันทึกผลทดสอบ',command=save_only).pack()
    button=ttk.Button(bar,text='สร้างรายงานไฟล์เดียว…',command=export);button.pack()
    ttk.Button(bar,text='ปิด',command=window.destroy).pack()
    def poll():
        nonlocal busy
        try:text=results.get_nowait()
        except queue.Empty:pass
        else:busy=False;progress.stop();button.configure(state='normal');status.set(text)
        window._support_poll=window.after(100,poll)
    def cleanup(event):
        if event.widget is window:
            try:progress.stop()
            except tk.TclError:pass
            if getattr(window,'_support_poll',None):window.after_cancel(window._support_poll)
    window.bind('<Destroy>',cleanup,add='+');poll();return window
