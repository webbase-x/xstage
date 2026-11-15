"""Explicit song-file reassignment, never fuzzy title matching."""
import copy
import queue
import threading
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from .dialog_layout import DialogWindow, ActionBar, scrollable_tree
from .song_eq import relocate, relocate_batch, key
from .path_probe import PathProbe

def open_manager(eq):
    app=eq.app
    window=DialogWindow(eq);window.title('จัดการ EQ ประจำเพลง');window.geometry('760x420')
    ttk.Label(window.content,text='ค้นหาชื่อไฟล์หรือตำแหน่งเพลง',padding=12).pack(anchor='w')
    search=tk.StringVar();ttk.Entry(window.content,textvariable=search).pack(fill='x',padx=12)
    notice=tk.StringVar(value='การนำเข้าไม่เปลี่ยนเสียงเพลงที่กำลังเล่น • เรียกใช้เมื่อเล่นครั้งถัดไป')
    ttk.Label(window.content,textvariable=notice,wraplength=700).pack(fill='x',padx=12,pady=6)
    checks={};results=queue.Queue();scanning=False;cancel=threading.Event();probe=None
    frame,tree=scrollable_tree(window.content,columns=('path','file_status'),show='headings',height=10)
    tree.heading('path',text='ไฟล์เพลงที่บันทึกค่า EQ');tree.column('path',width=540);tree.heading('file_status',text='ไฟล์');tree.column('file_status',width=130);frame.pack(fill='both',expand=True,padx=12)
    def refresh():
        tree.delete(*tree.get_children())
        query=search.get().casefold().strip()
        for path in sorted(app.settings.get('song_eq',{})):
            if query in path.casefold():tree.insert('','end',values=(path,checks.get(path,'ยังไม่ตรวจ')))
    search.trace_add('write',lambda *args:refresh())
    def move():
        selected=tree.selection()
        if not selected:return
        old=tree.item(selected[0],'values')[0]
        new=filedialog.askopenfilename(parent=window,title='เลือกไฟล์เพลงตำแหน่งใหม่')
        if not new:return
        target=key({'path':new});values=app.settings.get('song_eq',{})
        overwrite=target in values and target!=old
        if overwrite and not messagebox.askyesno('แทนที่ EQ','เพลงปลายทางมี EQ แล้ว ต้องการแทนที่หรือไม่?',parent=window):return
        backup=copy.deepcopy(values)
        try:
            relocate(app.settings,old,new,overwrite);app.save_settings()
        except Exception as error:
            app.settings['song_eq']=backup;messagebox.showerror('ย้ายค่าไม่สำเร็จ',str(error),parent=window);return
        refresh();eq.update_status()
    def move_batch():
        old=filedialog.askdirectory(parent=window,title='เลือกโฟลเดอร์ EQ เดิม')
        if not old:return
        new=filedialog.askdirectory(parent=window,title='เลือกโฟลเดอร์ EQ ใหม่')
        if not new:return
        values=app.settings.get('song_eq',{})
        old_key=key({'path':old});new_key=key({'path':new})
        mapping=[]
        for path in values:
            try: relative=Path(path).relative_to(old_key)
            except ValueError: continue
            mapping.append((path,str(Path(new_key)/relative)))
        if not mapping:
            messagebox.showinfo('ย้าย EQ แบบกลุ่ม','ไม่พบรายการ EQ ใต้โฟลเดอร์เดิม',parent=window);return
        overwrite=messagebox.askyesno('แทนที่ EQ ปลายทาง','หากปลายทางมีค่า EQ อยู่แล้ว ให้แทนที่หรือไม่?',parent=window)
        try:
            result=relocate_batch(app.settings,mapping,overwrite);app.save_settings();checks.clear();refresh();eq.update_status()
            notice.set(f"ย้าย EQ แล้ว {result['moved']:,} รายการ • ไม่พบต้นทาง {result['missing']:,} รายการ")
        except Exception as error:messagebox.showerror('ย้าย EQ ไม่สำเร็จ',str(error),parent=window)
    def export():
        from .song_eq_backup import encode
        from .library import write_json
        path=filedialog.asksaveasfilename(parent=window,defaultextension='.json',initialfile='XStage-song-EQ.json')
        if not path:return
        try:write_json(Path(path),encode(app.settings.get('song_eq',{})));notice.set('สำรองแล้ว • ไฟล์มีตำแหน่งเพลง ใช้ย้ายค่าได้ แต่ไม่ได้คัดลอกไฟล์เพลง')
        except Exception as error:messagebox.showerror('สำรองไม่สำเร็จ',str(error),parent=window)
    def import_file():
        from .song_eq_backup import load,merge,encode
        from .library import write_json
        path=filedialog.askopenfilename(parent=window,filetypes=[('Song EQ backup','*.json')])
        if not path:return
        old=copy.deepcopy(app.settings.get('song_eq',{}))
        try:
            incoming=load(path);collisions=len(set(old)&set(incoming))
            overwrite=False
            if collisions:
                answer=messagebox.askyesnocancel('รายการซ้ำ',f'พบค่าซ้ำ {collisions} เพลง\nใช่ = ใช้ค่าจากไฟล์นำเข้า\nไม่ = เก็บค่าเดิม\nยกเลิก = ไม่เปลี่ยนข้อมูล',parent=window,default='no')
                if answer is None:return
                overwrite=answer
            if not messagebox.askyesno('นำเข้า EQ',f'นำเข้า {len(incoming)} รายการ โดย'+('แทนที่ค่าซ้ำ' if overwrite else 'เก็บค่าซ้ำเดิม')+'?',parent=window):return
            backup=Path(app.data_dir)/'EQ-backups'/('before-import-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.json')
            write_json(backup,encode(old))
            app.settings['song_eq']=merge(old,incoming,overwrite);app.save_settings()
            checks.clear();refresh();eq.update_status();notice.set('นำเข้าแล้ว • สำรองค่าเดิมไว้ที่ '+str(backup))
        except Exception as error:
            app.settings['song_eq']=old;messagebox.showerror('นำเข้าไม่สำเร็จ',str(error),parent=window)
    def scan():
        nonlocal scanning,probe
        if scanning:return
        scanning=True;scan_button.configure(state='disabled');notice.set('กำลังตรวจตำแหน่งไฟล์… ไดรฟ์เครือข่ายอาจใช้เวลา')
        paths=list(app.settings.get('song_eq',{}))
        def completed(rows):
            for row in rows:
                state='พบไฟล์' if row['exists'] else ('ตรวจไม่ได้: '+row['error'] if row['error'] else 'ไม่พบ / ไดรฟ์ไม่พร้อม')
                results.put((row['path'],state))
            results.put(None)
        probe=PathProbe(paths,completed).start()
    def poll():
        nonlocal scanning
        changed=False
        for _ in range(200):
            try:item=results.get_nowait()
            except queue.Empty:break
            if item is None:
                scanning=False;scan_button.configure(state='normal');notice.set('ตรวจเสร็จ • ไม่พบไฟล์อาจเกิดจากไดรฟ์ไม่ได้เชื่อมต่อ ไม่มีการลบค่า')
            else:checks[item[0]]=item[1];changed=True
        if changed:refresh()
        window._song_poll=window.after(150,poll)
    def cleanup(event):
        if event.widget is window:
            cancel.set()
            if probe:probe.cancel()
            if getattr(window,'_song_poll',None):window.after_cancel(window._song_poll)
    window.bind('<Destroy>',cleanup,add='+')
    bar=ActionBar(window.footer);bar.pack(fill='x',padx=8,pady=8)
    ttk.Button(bar,text='เลือกไฟล์ตำแหน่งใหม่…',command=move).pack()
    ttk.Button(bar,text='สำรองทั้งหมด…',command=export).pack()
    ttk.Button(bar,text='นำเข้าค่า…',command=import_file).pack()
    ttk.Button(bar,text='ย้ายโฟลเดอร์ EQ แบบกลุ่ม…',command=move_batch).pack()
    scan_button=ttk.Button(bar,text='ตรวจตำแหน่งไฟล์',command=scan);scan_button.pack()
    ttk.Button(bar,text='ปิด',command=window.destroy).pack()
    refresh();poll();return window
