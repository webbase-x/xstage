"""Read-only checks in a child process; repair runs only after this process exits."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from .dialog_layout import DialogWindow, ActionBar

def check_command(home, report, executable=None, frozen=None):
    executable=executable or sys.executable
    frozen=getattr(sys,'frozen',False) if frozen is None else frozen
    if frozen:return [executable,'--check-dependencies','--dependency-report',str(report)]
    return [executable,str(Path(home)/'tools/check_dependencies.py'),'--home',str(home),'--report',str(report)]

def open_window(app):
    existing=getattr(app,'_dependency_window',None)
    if existing is not None and existing.winfo_exists():existing.deiconify();existing.lift();return existing
    window=DialogWindow(app);app._dependency_window=window;window.title('ตรวจและซ่อมส่วนประกอบ');window.geometry('720x480')
    status=tk.StringVar(value='กำลังตรวจ…')
    ttk.Label(window.content,textvariable=status,padding=12,wraplength=660).pack(fill='x')
    output=tk.Text(window.content,height=15,width=70,wrap='word',bg='#0c1424',fg='#e4edf7')
    output.pack(fill='both',expand=True,padx=12,pady=8)
    report=Path(app.data_dir)/'dependency-report.json';results=queue.Queue();busy=False
    progress=ttk.Progressbar(window.footer,mode='indeterminate');progress.pack(fill='x',padx=12,pady=4)
    from .library import read_json
    last=read_json(Path(app.data_dir)/'repair-status.json',{})
    if last:
        ttk.Label(window.content,text='ผลซ่อมล่าสุด: '+str(last.get('stage',''))+' • '+str(last.get('status',''))+'\n'+str(last.get('error','')),wraplength=650).pack(fill='x',padx=12)
    def check():
        nonlocal busy
        if busy:return
        busy=True;progress.start(12);check_button.configure(state='disabled');repair_button.configure(state='disabled');status.set('กำลังตรวจส่วนประกอบ…')
        def worker():
            try:
                report.parent.mkdir(parents=True,exist_ok=True)
                report.unlink(missing_ok=True)
                run=subprocess.run(check_command(app.home,report),capture_output=True,text=True,timeout=90,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if not report.exists():raise RuntimeError(run.stderr or 'ไม่พบรายงานการตรวจ')
                if run.returncode not in (0,1):raise RuntimeError(run.stderr or 'ตัวตรวจระบบหยุดผิดปกติ')
                results.put(json.loads(report.read_text(encoding='utf-8')))
            except Exception as error:results.put({'ok':False,'checks':[{'name':'ตรวจส่วนประกอบ','ok':False,'detail':str(error)}]})
        threading.Thread(target=worker,daemon=True).start()
    def repair():
        if sys.platform!='win32':return
        script=Path(app.home)/'tools/Repair-Dependencies.ps1'
        if not script.exists():messagebox.showerror('ซ่อมไม่ได้','ไม่พบชุดซ่อม กรุณาติดตั้งจากชุดโปรแกรมครบชุด',parent=window);return
        # Save first; if saving fails, leave the running application untouched.
        try:
            app.save_settings();app.song_queue.save()
            command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-WaitPid',str(os.getpid()),'-AppDirectory',str(app.home),'-DataDirectory',str(app.data_dir)]
            if not getattr(sys,'frozen',False):command+=['-PythonExe',sys.executable]
            subprocess.Popen(command,creationflags=subprocess.CREATE_NEW_CONSOLE,cwd=str(app.home))
        except Exception as error:messagebox.showerror('เริ่มซ่อมไม่ได้',str(error),parent=window);return
        app.close_app()
    bar=ActionBar(window.footer);bar.pack(fill='x',padx=8,pady=8)
    check_button=ttk.Button(bar,text='ตรวจอีกครั้ง',command=check);check_button.pack()
    repair_button=ttk.Button(bar,text='ปิดโปรแกรมแล้วซ่อม',command=repair);repair_button.pack()
    def save_report():
        from .library import write_json
        path=filedialog.asksaveasfilename(parent=window,defaultextension='.json',initialfile='XStage-component-report.json')
        if not path:return
        try:write_json(Path(path),{'dependencies':read_json(report,{}),'repair':read_json(Path(app.data_dir)/'repair-status.json',{})})
        except Exception as error:messagebox.showerror('ส่งออกไม่ได้',str(error),parent=window)
    ttk.Button(bar,text='ส่งออกรายงาน…',command=save_report).pack()
    ttk.Button(bar,text='ปิดหน้าต่าง',command=window.destroy).pack()
    def poll():
        nonlocal busy
        try:item=results.get_nowait()
        except queue.Empty:pass
        else:
            busy=False;progress.stop();check_button.configure(state='normal')
            repair_button.configure(state='normal' if sys.platform=='win32' else 'disabled')
            status.set('ส่วนประกอบพร้อม • ยังไม่ใช่ผลทดสอบเสียงจริง' if item['ok'] else 'พบส่วนประกอบไม่พร้อม • การซ่อมจะปิดและเปิดโปรแกรมใหม่')
            output.configure(state='normal');output.delete('1.0','end')
            for entry in item['checks']:output.insert('end',('✓ ' if entry['ok'] else '✗ ')+entry['name']+' — '+entry['detail']+'\n')
            output.configure(state='disabled')
        window._repair_poll=window.after(100,poll)
    def cleanup(event):
        if event.widget is window:
            try:progress.stop()
            except tk.TclError:pass
            if getattr(window,'_repair_poll',None):window.after_cancel(window._repair_poll)
    window.bind('<Destroy>',cleanup,add='+');check();poll();return window
