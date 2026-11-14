"""Bounded, read-only local logs; no uploads or file deletion."""
from pathlib import Path
import os
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText
from .dialog_layout import DialogWindow, ActionBar


def log_directory(app):
    diagnostics = getattr(app, '_diagnostics', None)
    if diagnostics: return diagnostics.directory
    from .runtime_diagnostics import log_base
    data=Path(getattr(app,'data_dir',Path.cwd()/'data'))
    primary=log_base(data);fallback=data/'Logs'
    return fallback if not primary.exists() and fallback.exists() else primary


def read_tail(path, limit=262144):
    with Path(path).open('rb') as stream:
        stream.seek(0,2);size=stream.tell();stream.seek(max(0,size-limit))
        data=stream.read(limit)
    if size>limit:
        data=data.split(b'\n',1)[-1]
    return ('[แสดงเฉพาะท้ายไฟล์ 256 KB]\n' if size>limit else '')+data.decode('utf-8',errors='replace')


def open_window(app):
    old=getattr(app,'_log_window',None)
    if old is not None and old.winfo_exists():old.deiconify();old.lift();return old
    win=DialogWindow(app);app._log_window=win
    win.title('X-Stage • บันทึกเหตุการณ์ / ข้อผิดพลาด');win.geometry('980x650')
    directory=log_directory(app)
    ttk.Label(win.content,text='บันทึกเหตุการณ์ทั้งระบบ',font=('Tahoma',17,'bold')).pack(anchor='w',padx=14,pady=10)
    ttk.Label(win.content,text='ไฟล์หลักรวมเหตุการณ์ทุกระบบ • ไฟล์ native เก็บรายละเอียดอาการค้าง',wraplength=850).pack(anchor='w',padx=14)
    combo=ttk.Combobox(win.content,state='readonly');combo.pack(fill='x',padx=14,pady=8)
    text=ScrolledText(win.content,wrap='word',height=19,font=('Consolas',10),bg='#10192d',fg='#e3eaf0',insertbackground='white')
    text.pack(fill='both',expand=True,padx=14,pady=(0,8));text.configure(state='disabled')
    status=tk.StringVar();ttk.Label(win.footer,textvariable=status,wraplength=850).pack(anchor='w',padx=14)
    files={}
    def show(*_):
        try: value=read_tail(files[combo.get()]) if combo.get() in files else 'ยังไม่มีไฟล์ Log'
        except OSError as error:value='อ่านไฟล์ไม่ได้: '+str(error)
        text.configure(state='normal');text.delete('1.0','end');text.insert('1.0',value);text.configure(state='disabled');text.see('end')
        status.set(str(directory))
    def refresh():
        selected=combo.get();files.clear()
        if directory.exists():
            paths=sorted((p for p in directory.iterdir() if p.is_file() and (p.suffix=='.log' or '.log.' in p.name)),key=lambda p:p.name)
            files.update((p.name,p) for p in paths)
        combo['values']=list(files)
        combo.set(selected if selected in files else ('XStageKaraoke.log' if 'XStageKaraoke.log' in files else next(iter(files),'')))
        show()
    def folder():
        try:
            directory.mkdir(parents=True,exist_ok=True)
            if os.name=='nt':os.startfile(str(directory))
            else:messagebox.showinfo('โฟลเดอร์ Log',str(directory),parent=win)
        except OSError as error:messagebox.showerror('เปิด Log',str(error),parent=win)
    combo.bind('<<ComboboxSelected>>',show)
    bar=ActionBar(win.footer);bar.pack(fill='x',padx=10,pady=8)
    for title,command in [('รีเฟรช',refresh),('เปิดโฟลเดอร์',folder),('ปิด',win.destroy)]:ttk.Button(bar,text=title,command=command).pack(side='left')
    refresh();return win
