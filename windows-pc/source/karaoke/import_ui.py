"""Import choices on the Tk thread; cancellable request bridge for workers."""
import copy
import threading
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from .dialog_layout import DialogWindow, ActionBar
from .library import SearchCancelled


def choose_copy(app):
    """v0.9.43 always imports by reference; media placement is the user's choice."""
    if getattr(app, 'import_copy_var', None) is not None:
        app.import_copy_var.set(False)
    return False

def duplicate_choice(app,record,keeper,exact):
    window=DialogWindow(app);window.title('พบเพลงซ้ำ');window.transient(app)
    choice=tk.StringVar(value='existing');result=['cancel']
    text=('ไฟล์เพลงและชุดเนื้อร้องเหมือนเดิม จะใช้รายการเดิมและไม่คัดลอกซ้ำ' if exact else 'ชื่อเพลง + นักร้อง + คีย์ซ้ำ กรุณาเลือกไฟล์ที่ต้องการ')
    ttk.Label(window.content,text=text,padding=12,wraplength=680).pack(anchor='w')
    for title,row in [('รายการเดิม #'+str(keeper['id']),keeper),('ไฟล์ที่เลือกใหม่',record)]:
        ttk.Label(window.content,text=title+': '+row.get('title','')+' — '+row.get('artist','')+'\n'+row['path'],padding=12,wraplength=680).pack(anchor='w')
    for value,label in [('existing','ใช้รายการเดิม (ค่าเริ่มต้น)'),('new','ใช้ไฟล์ใหม่แทนรายการเดิม — รักษาคิว เพลงโปรด และข้อมูลที่แก้ไว้'),('both','ชื่อ นักร้อง คีย์ตรงกัน — ไม่เพิ่มรายการซ้ำ')]:
        ttk.Radiobutton(window.content,text=label,value=value,variable=choice,state='disabled' if value=='both' or exact and value!='existing' else 'normal').pack(anchor='w',padx=12,pady=4)
    bar=ActionBar(window.content);bar.pack(fill='x',padx=12,pady=12)
    def accept():result[0]=choice.get();window.destroy()
    ttk.Button(bar,text='ยืนยัน',command=accept).pack(side='left')
    ttk.Button(bar,text='ยกเลิก',command=window.destroy).pack(side='left')
    window.grab_set();app.wait_window(window)
    return result[0]


class ChoiceRequest:
    def __init__(self,record,keeper,exact):
        self.record=record;self.keeper=keeper;self.exact=exact;self.event=threading.Event();self.result='cancel'


def request_choice(app,record,keeper,exact):
    request=ChoiceRequest(record,keeper,exact);app.messages.put(('import_choice',request))
    while not request.event.wait(.1):
        if app.cancel_scan.is_set() or app.closing:raise SearchCancelled()
    return request.result


def options(app,copy_files):
    return dict(songs_root=Path(app.data_dir).parent/'Songs',copy_files=copy_files,
                decide=lambda record,keeper,exact:request_choice(app,record,keeper,exact),
                replaced=lambda old,new:app.messages.put(('song_replaced',(old,new))),
                selected=lambda sid:app.messages.put(('import_selected',sid)))


def handle_message(app,kind,data):
    if kind in ('catalog_progress', 'catalog_finished', 'catalog_report_finished'):
        app.handle_catalog_message(kind, data)
        return True
    from .playlist_ui import handle_message as playlist_message
    if playlist_message(app,kind,data):return True
    from .hygiene_ui import handle_message as hygiene_message
    if hygiene_message(app,kind,data):return True
    if kind=='import_choice':
        try:
            if not app.cancel_scan.is_set() and not app.closing:data.result=duplicate_choice(app,data.record,data.keeper,data.exact)
        finally:data.event.set()
        return True
    if kind=='song_replaced':
        from .song_eq import key
        old,new=(key({'path':p}) for p in data)
        values=app.settings.get('song_eq',{})
        if isinstance(values,dict) and old in values and new not in values:
            values[new]=copy.deepcopy(values[old]);app.save_settings()
        return True
    if kind=='import_selected':
        app._import_selected_id=data
        workspace=getattr(getattr(app,'job_window',None),'workspace',None)
        if workspace is not None and workspace.catalog.winfo_exists():workspace.pending_selection=data;workspace.search()
        return True
    return False
