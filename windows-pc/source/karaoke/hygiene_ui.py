"""Review-only scan, explicit selection and typed confirmation before file deletion."""
import json
import os
from pathlib import Path
import sqlite3
import tkinter as tk
from tkinter import ttk,messagebox,simpledialog,filedialog
from .dialog_layout import DialogWindow,ActionBar,scrollable_tree
from . import library_hygiene as hygiene

LABELS=hygiene.STATUS_LABELS


def protected(app):
    ids={item.song_id for item in app.song_queue.items}
    if app.current_song:ids.add(app.current_song['id'])
    return ids


def handle_message(app,kind,data):
    if kind=='hygiene_report':
        app._last_hygiene_report=data
        manager=getattr(app,'hygiene_manager',None)
        if manager and manager.window.winfo_exists():manager.load(data)
        return True
    if kind=='hygiene_unlocked':
        app._cleanup_busy=False;app.song_queue._maintenance_locked=False
        return True
    return False


def open_hygiene(app):
    """Route old quality-menu entry to the v0.9.43 explicit Song Bundle UI.

    The old backup-and-delete screen is no longer opened for new actions;
    historical recovery data is retained on disk for manual inspection.
    """
    from .duplicate_dialog import open_exact_duplicates
    return open_exact_duplicates(app)


class HygieneWindow:
    def __init__(self,app):
        self.app=app;self.folder=None;self.page=0;self.selected_ids=set();self.rendering=False
        self.window=DialogWindow(app);self.window.title('ตรวจคุณภาพเพลง / ป้องกันและลบเพลงซ้ำ');self.window.geometry('1160x780')
        body=ttk.Frame(self.window.content,padding=14);body.pack(fill='both',expand=True)
        ttk.Label(body,text='ซ้ำ = ชื่อเพลง + นักร้อง + คีย์ตรงกัน (แยก Major/Minor) • เก็บชุดที่สมบูรณ์ก่อน • การตรวจไม่ลบไฟล์',wraplength=1080).pack(anchor='w')
        ttk.Label(body,text='MIDI/NCN/EMK และเพลงเสียงต้องมีเนื้อร้องพร้อมเวลา • วิดีโอไม่บังคับ LRC • ข้อมูล/codec ที่ยังยืนยันไม่ได้แยกตรวจเพิ่มและไม่ให้ลบรวม',wraplength=1080).pack(anchor='w',pady=6)
        bar=ActionBar(body);bar.pack(fill='x')
        ttk.Button(bar,text='ตรวจคลัง (ยังไม่ลบ)',command=lambda:self.invoke(self.scan)).pack(side='left')
        ttk.Button(bar,text='เปิดรายงานเดิม…',command=lambda:self.invoke(self.open_report)).pack(side='left')
        ttk.Button(bar,text='เปิด CSV รายละเอียด',command=lambda:self.invoke(self.open_csv)).pack(side='left')
        self.summary=tk.StringVar(value='เริ่มตรวจหรือเปิด summary.json เพื่ออ่านรายงาน');ttk.Label(body,textvariable=self.summary,wraplength=1080).pack(anchor='w',pady=6)
        filters=ttk.Frame(body);filters.pack(fill='x')
        self.filter=tk.StringVar(value='ทุกรายการที่ต้องจัดการ');self.query=tk.StringVar()
        combo=ttk.Combobox(filters,textvariable=self.filter,values=['ทุกรายการที่ต้องจัดการ',*LABELS.values()],state='readonly',width=28);combo.pack(side='left');combo.bind('<<ComboboxSelected>>',lambda _:self.filter_changed())
        ttk.Entry(filters,textvariable=self.query,width=35).pack(side='left',padx=6);ttk.Button(filters,text='ค้นหา',command=self.filter_changed).pack(side='left')
        box,self.tree=scrollable_tree(body,columns=('id','status','title','artist','key','keeper','reason'),show='headings',selectmode='extended',height=10);box.pack(fill='both',expand=True,pady=8)
        for name,label,width in [('id','ID',70),('status','ผลตรวจ',150),('title','ชื่อเพลง',210),('artist','นักร้อง',160),('key','คีย์',60),('keeper','เก็บ ID',70),('reason','เหตุผล / เส้นทาง',420)]:self.tree.heading(name,text=label);self.tree.column(name,width=width,minwidth=40)
        self.tree.bind('<<TreeviewSelect>>',self.select)
        self.detail=tk.StringVar();ttk.Label(body,textvariable=self.detail,wraplength=1080).pack(anchor='w')
        self.selection_text=tk.StringVar(value='ยังไม่เลือกรายการลบ');ttk.Label(body,textvariable=self.selection_text).pack(anchor='w',pady=4)
        actions=ActionBar(self.window.footer,padding=12);actions.pack(fill='x')
        for label,callback in [('‹ ก่อนหน้า',lambda:self.turn(-1)),('ถัดไป ›',lambda:self.turn(1)),('เลือกทุกรายการที่ลบได้',self.select_all),('ล้างการเลือก',self.clear),('แก้ชื่อ/นักร้อง/คีย์',self.edit),('ลบไฟล์ถาวรที่เลือก…',self.delete),('กู้คืนจากสำรองงานลบ…',self.restore)]:ttk.Button(actions,text=label,command=lambda cb=callback:self.invoke(cb)).pack(side='left',padx=2)
        ttk.Label(self.window.footer,textvariable=app.status_var,wraplength=1080).pack(anchor='w',padx=12,pady=4)
        previous=getattr(app,'_last_hygiene_report',None)
        if previous:self.load(previous)
    def invoke(self,action):
        try:action()
        except Exception as error:self.app.show_error(error)
    def connect(self):
        db=hygiene.readonly(self.folder/'plan.sqlite3');db.row_factory=sqlite3.Row;return db
    def load(self,folder):
        folder=Path(folder);summary=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
        if summary.get('library')!=hygiene.canonical(self.app.library.path):raise ValueError('รายงานเป็นของฐานข้อมูลอื่น')
        self.folder=folder;self.plan_summary=summary;self.page=0;self.selected_ids.clear()
        counts=summary['counts'];self.summary.set(('ตรวจครบ' if summary['complete'] else 'รายงานไม่ครบ ห้ามลบ')+' • '+' • '.join(LABELS.get(k,k)+' '+str(v) for k,v in counts.items())+'\n'+str(folder))
        self.render()
    def scan(self):
        if self.app.scanning:return
        frozen=protected(self.app)
        def work():
            folder=hygiene.scan(self.app.library.path,self.app.data_dir/'quality-reports',self.app.cancel_scan,self.app.job_event,frozen,workers=min(4,os.cpu_count() or 1))
            self.app.messages.put(('hygiene_report',str(folder)))
            summary=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
            return 0,0,['ตรวจคุณภาพแล้ว ยังไม่ลบไฟล์ • '+' • '.join(LABELS[key]+' '+str(value) for key,value in summary['counts'].items())+' • '+str(folder/'report.csv')]
        self.app.start_index_job(work)
    def open_report(self):
        path=filedialog.askopenfilename(parent=self.window,title='เลือก summary.json ของรายงาน',filetypes=[('รายงาน','summary.json')])
        if path:self.load(Path(path).parent)
    def open_csv(self):
        if self.folder:os.startfile(self.folder/'report.csv')
    def where(self):
        status=next((k for k,v in LABELS.items() if v==self.filter.get()),None)
        clauses=['status=?'] if status else ["status<>'valid'"];args=[status] if status else []
        if self.query.get().strip():clauses.append('(old LIKE ? OR reason LIKE ?)');args.extend(['%'+self.query.get().strip()+'%']*2)
        return ' AND '.join(clauses),args
    def render(self):
        if not self.folder:return
        where,args=self.where();self.rendering=True
        db=self.connect()
        try:
            self.total=db.execute('SELECT count(*) FROM rows WHERE '+where,args).fetchone()[0]
            self.page=min(self.page,max(0,(self.total-1)//200));items=db.execute('SELECT * FROM rows WHERE '+where+' ORDER BY id LIMIT 200 OFFSET ?',args+[self.page*200]).fetchall()
        finally:db.close()
        self.tree.delete(*self.tree.get_children());self.records={}
        for item in items:
            row=json.loads(item['old']);measured=json.loads(item['quality']).get('metadata',{});row={**row,**{k:v for k,v in measured.items() if not row.get(k)}};self.records[str(row['id'])]=dict(item)
            self.tree.insert('','end',iid=str(row['id']),values=(row['id'],LABELS[item['status']],row['title'],row['artist'],row.get('key_signature',''),item['keeper'] or '',item['reason']+' • '+row['path']))
        self.rendering=False;self.selection_text.set(f'เลือก {len(self.selected_ids):,} รายการ • หน้า {self.page+1} / {max(1,(self.total+199)//200)}')
    def filter_changed(self):self.page=0;self.selected_ids.clear();self.render()
    def turn(self,delta):self.page=max(0,self.page+delta);self.render()
    def select(self,_=None):
        if self.rendering:return
        self.selected_ids={int(i) for i in self.tree.selection()}
        ids=self.tree.selection()
        if ids:
            row=json.loads(self.records[ids[0]]['old']);self.detail.set(row['path'])
        self.selection_text.set('เลือก '+str(len(self.selected_ids))+' รายการ')
    def select_all(self):
        if not self.folder:return
        db=self.connect()
        try:self.selected_ids={row[0] for row in db.execute("SELECT id FROM rows WHERE status IN ('duplicate','invalid')")}
        finally:db.close()
        self.selection_text.set('เลือกทุกรายการที่ลบได้ '+str(len(self.selected_ids))+' รายการ — ต้องตรวจรายงานและยืนยันก่อนลบ')
    def clear(self):self.selected_ids.clear();self.tree.selection_remove(*self.tree.selection());self.selection_text.set('ยังไม่เลือกรายการลบ')
    def edit(self):
        if self.app.scanning:return
        selected=self.tree.selection()
        if not selected:return
        row=json.loads(self.records[selected[0]]['old']);current=self.app.library.get(row['id'])
        if not current or current['duplicate_state']=='deleted':return
        values=self.app.edit_dialog('แก้ข้อมูลเพื่อให้ตรวจใหม่',[('รหัส',current['code']),('ชื่อเพลง',current['title']),('นักร้อง',current['artist']),('คีย์ เช่น C, Am, F#',current['key_signature'])])
        if values:
            self.app.library.edit(row['id'],*values);self.app.refresh_library();self.detail.set('บันทึกข้อมูลแล้ว ต้องตรวจคลังใหม่ก่อนลบตามรายงาน')
    def delete(self):
        if self.app.scanning or not self.folder:return
        ids=sorted(self.selected_ids)
        if not ids:return messagebox.showinfo('ยังไม่เลือก','เลือกรายการที่ตรวจรายงานแล้วก่อน',parent=self.window)
        hygiene.validate_plan(self.folder,self.plan_summary['plan_sha256'])
        db=self.connect()
        try:
            samples=[];files=0;size=0
            for sid in ids:
                row=db.execute("SELECT * FROM rows WHERE id=? AND status IN ('duplicate','invalid')",(sid,)).fetchone()
                if not row:raise ValueError('การเลือกมีรายการที่ต้องตรวจเพิ่ม/ป้องกันไว้ ห้ามลบรวม')
                old=json.loads(row['old']);parts=json.loads(row['files']);files+=sum(not p.get('shared') for p in parts);size+=sum(p['size'] for p in parts if not p.get('shared'))
                if len(samples)<4:samples.append('#'+str(sid)+' '+old['title'][:80]+' • '+old['path'][:140])
        finally:db.close()
        text=f'ลบออกจากคลัง {len(ids):,} รายการ ไฟล์ส่วนตัวไม่เกิน {files:,} ไฟล์ ({size/1024/1024:.1f} MB)\nไฟล์ร่วมจะเก็บไว้ มีสำรองที่ตรวจเนื้อหาแล้วและบันทึกกู้คืนทุกงาน\n\n'+ '\n'.join(samples)+'\n\nตรวจ CSV แล้ว พิมพ์คำว่า ลบ เพื่อยืนยันการลบไฟล์ถาวร'
        if simpledialog.askstring('ยืนยันลบถาวรตามรายงาน',text,parent=self.window)!='ลบ':return
        frozen=protected(self.app)
        if frozen.intersection(ids):return messagebox.showwarning('ยังลบไม่ได้','มีรายการที่เลือกอยู่ในคิวหรือกำลังเล่น ให้นำออกจากคิว/หยุดก่อน',parent=self.window)
        self.app._cleanup_busy=True;self.app.song_queue._maintenance_locked=True
        def work():
            try:
                result=hygiene.apply(self.app.library,self.folder,ids,self.plan_summary['plan_sha256'],lambda:protected(self.app),self.app.cancel_scan,self.app.job_event,data_lock=getattr(self.app,'data_lock',None))
                return 0,result['blocked'],['ลบตามรายงาน '+str(result['applied'])+' รายการ • ระงับ '+str(result['blocked'])+' • สำรอง '+result['backup']+' • บันทึกกู้คืน '+result['journal']]
            finally:self.app.messages.put(('hygiene_unlocked',None))
        self.app.start_index_job(work)
    def restore(self):
        if self.app.scanning or not self.folder:return
        sid=simpledialog.askinteger('กู้คืนงานลบ','ID เพลงในรายงานที่ต้องการกู้คืนจากสำรอง',parent=self.window,minvalue=1)
        if sid and messagebox.askyesno('ยืนยันกู้คืน','คืนเฉพาะไฟล์ที่ขาดและไม่เขียนทับไฟล์ที่มีอยู่?',parent=self.window):
            def work():
                hygiene.restore_action(self.app.library,self.folder,sid,data_lock=getattr(self.app,'data_lock',None))
                return 0,0,['กู้คืนจากสำรองแล้ว ID '+str(sid)]
            self.app.start_index_job(work)
