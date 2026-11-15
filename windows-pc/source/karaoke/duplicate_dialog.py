"""v0.9.43 user-controlled duplicate review. No auto-hide or quarantine."""
import json
import sqlite3
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from pathlib import Path
from .dialog_layout import DialogWindow, scrollable_tree
from . import duplicate_actions as actions
from .duplicate_review import create_review, read_review
from .duplicates import prepare_action

CATEGORY = {'all':'ทุกประเภท', 'exact':'เนื้อหาเหมือน 100%',
            'code':'รหัสเพลงซ้ำ', 'metadata':'ชื่อ/ศิลปิน/คีย์ซ้ำ', 'title':'ชื่อเพลงซ้ำ', 'incomplete':'ไฟล์ไม่ครบ/เล่นไม่ได้'}
FORMAT = {'all':'ทุกชนิดไฟล์', 'midi':'MIDI/NCN', 'audio':'Audio', 'video':'Video'}
PAGE = 150


def protected_ids(app):
    ids = {item.song_id for item in app.song_queue.items}
    if app.current_song:
        ids.add(app.current_song['id'])
    return ids


class DuplicateReviewWindow:
    def __init__(self, app):
        self.app = app
        self.folder = None
        self.future = None
        self.page = 0
        self.records = {}
        self.window = DialogWindow(app)
        self.window.title('เพลงซ้ำ — ตรวจรายงานและจัดการเอง (v0.9.43)')
        self.window.geometry('1150x790')
        self.window.transient(app)
        body = ttk.Frame(self.window.content, padding=12)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='การตรวจไม่ซ่อน ไม่ย้าย ไม่ลบไฟล์ · 1 เพลงอาจมี MID/LYR/CUR หลายไฟล์',
                  wraplength=1060).pack(anchor='w')
        ttk.Label(body, text='ลบไฟล์จริงได้เฉพาะกลุ่มที่ยืนยันเหมือนกันทั้ง Song Bundle; ประเภทอื่นตรวจสอบได้ แต่ไม่ลบไฟล์จากการเดาชื่อ/รหัส',
                  wraplength=1060).pack(anchor='w', pady=(4,8))
        row = ttk.Frame(body);row.pack(fill='x')
        ttk.Button(row,text='สร้างรายงานเพลงซ้ำ',command=lambda:self.start_report(False)).pack(side='left')
        ttk.Button(row,text='ยืนยัน SHA-256 ทุกชุด',command=lambda:self.start_report(True)).pack(side='left',padx=6)
        ttk.Button(row,text='เปิด CSV',command=self.open_csv).pack(side='left')
        ttk.Label(row,text='ประเภท:').pack(side='left',padx=(16,3))
        self.category = tk.StringVar(value='all')
        categories = {value:key for key,value in CATEGORY.items()}
        cat=ttk.Combobox(row,state='readonly',width=24,values=list(categories))
        cat.set(CATEGORY['all']);cat.pack(side='left')
        cat.bind('<<ComboboxSelected>>',lambda e:(self.category.set(categories[cat.get()]),self.reset()))
        self.format = tk.StringVar(value='all')
        formats = {value:key for key,value in FORMAT.items()}
        ttk.Label(row,text='ไฟล์:').pack(side='left',padx=(12,3))
        ft=ttk.Combobox(row,state='readonly',width=15,values=list(formats));ft.set(FORMAT['all']);ft.pack(side='left')
        ft.bind('<<ComboboxSelected>>',lambda e:(self.format.set(formats[ft.get()]),self.reset()))
        self.summary = tk.StringVar(value='ยังไม่ได้ตรวจ กรุณาสร้างรายงานก่อน')
        ttk.Label(body,textvariable=self.summary,wraplength=1080).pack(anchor='w',pady=(9,6))
        frame,self.tree=scrollable_tree(body,columns=('id','type','format','song','keeper','path'),
                show='headings',height=12,selectmode='extended')
        for name,label,width in [('id','ID',65),('type','สาเหตุซ้ำ',150),('format','รูปแบบ',85),
                                 ('song','ชื่อเพลง / ศิลปิน',260),('keeper','ชุดหลัก ID',80),('path','ต้นทางไฟล์',390)]:
            self.tree.heading(name,text=label);self.tree.column(name,width=width,minwidth=45)
        frame.pack(fill='both',expand=True,pady=5)
        self.detail=tk.StringVar(value='เลือกเพลงเพื่อดูชุดหลักและตำแหน่งไฟล์')
        ttk.Label(body,textvariable=self.detail,wraplength=1060).pack(anchor='w',pady=5)
        self.tree.bind('<<TreeviewSelect>>',self.show_details)
        pager=ttk.Frame(body);pager.pack(fill='x')
        ttk.Button(pager,text='‹ ก่อนหน้า',command=lambda:self.turn(-1)).pack(side='left')
        ttk.Button(pager,text='ถัดไป ›',command=lambda:self.turn(1)).pack(side='left',padx=6)
        ttk.Button(pager,text='ล้างการเลือก',command=lambda:self.tree.selection_remove(*self.tree.selection())).pack(side='right')
        actions_bar=ttk.Frame(self.window.footer,padding=10);actions_bar.pack(fill='x')
        for label,action in [('ซ่อนรายการที่เลือก',self.hide),('นำออกจากฐาน',self.exclude),
            ('ส่งเข้าถังรีไซเคิล',lambda:self.delete(False)),('ลบไฟล์ถาวร…',lambda:self.delete(True)),
            ('เลิกซ่อน',self.unhide),('คืนรายการด้วย ID',self.restore_by_id),('ปิด',self.window.destroy)]:
            ttk.Button(actions_bar,text=label,command=action).pack(side='left',padx=3)
        self.timer=None;self.busy=False
        existing=sorted((app.data_dir/'duplicate-reviews').glob('*/summary.json'))
        if existing:self.load(existing[-1].parent)
        self.poll()
        self.window.bind('<Destroy>',self.destroy,add='+')

    def destroy(self,event):
        if event.widget is self.window and self.timer:
            try:self.window.after_cancel(self.timer)
            except tk.TclError:pass
            self.timer=None

    def poll(self):
        if not self.window.winfo_exists():return
        future=self.future
        if future and not future.is_alive():
            self.future=None;self.busy=False
            if getattr(self,'error',None):
                self.app.show_error(self.error)
            elif self.folder:
                self.load(self.folder)
        self.timer=self.window.after(150,self.poll)

    def start_report(self,exact):
        if self.busy or self.app.scanning:return
        self.busy=True;self.error=None
        self.summary.set('กำลังตรวจ Song Bundle แบบอ่านอย่างเดียว…')
        def worker():
            try:self.folder=create_review(self.app.library,
                        self.app.data_dir/'duplicate-reviews',verify_exact=exact)
            except Exception as e:self.error=e
        self.future=threading.Thread(target=worker,daemon=True,name='duplicate-review')
        self.future.start()

    def load(self,folder):
        self.folder=Path(folder)
        summary=json.loads((self.folder/'summary.json').read_text(encoding='utf-8'))
        if summary.get('library')!=str(self.app.library.path.resolve()):
            raise ValueError('รายงานเพลงซ้ำเป็นของฐานอื่น')
        self.info=summary;self.page=0
        self.summary.set('ตรวจ '+str(summary['scanned_songs'])+' เพลง · เสนอ '+str(summary['suggestions'])+
                         ' รายการ · '+('ตรวจ SHA-256 แล้ว' if summary['exact_verified'] else 'ยังไม่ตรวจ SHA-256')+
                         ' · ไฟล์ไม่ครบ '+str(summary['categories'].get('incomplete',0))+' · ไม่เปลี่ยนไฟล์/ผลค้นหา')
        self.render()

    def render(self):
        if not self.folder:return
        total,rows=read_review(self.folder,category=self.category.get(),file_format=self.format.get(),
                               limit=PAGE,offset=self.page*PAGE)
        self.tree.delete(*self.tree.get_children());self.records.clear()
        for r in rows:
            iid=str(r['song_id'])+'-'+str(r['keeper_id']);self.records[iid]=r
            self.tree.insert('','end',iid=iid,values=(r['song_id'],CATEGORY[r['category']],
                        FORMAT[r['file_format']],r['title']+' / '+r['artist'],r['keeper_id'],r['path']))
        self.detail.set(f'แสดง {len(rows)} จาก {total} รายการ · หน้า {self.page+1}/{max(1,(total+PAGE-1)//PAGE)}')

    def reset(self):self.page=0;self.render()
    def turn(self,delta):self.page=max(0,self.page+delta);self.render()
    def show_details(self,_=None):
        keys=self.tree.selection()
        if keys:
            r=self.records.get(keys[0]);
            if r:self.detail.set(f"#{r['song_id']} {r['path']}\nเก็บ #{r['keeper_id']} {r['keeper_path']}")
    def selected(self):return [self.records[k] for k in self.tree.selection() if k in self.records]
    def open_csv(self):
        if self.folder:
            import os
            os.startfile(self.folder/'report.csv')

    def run_actions(self,operation,notes):
        if self.app.scanning or self.busy:return
        def work():
            success = failed = 0
            messages = []
            with actions.action_batch(self.app.library):
                for item in notes:
                    try:
                        self._validate_report_row(item)
                        outcome = operation(item)
                        if isinstance(outcome, Path) and outcome.suffix.lower()=='.json':
                            result = json.loads(outcome.read_text(encoding='utf-8'))
                            if result.get('status') in ('partial','blocked'):
                                raise RuntimeError('ผลบางส่วน/ถูกปิดกั้น: '+str(outcome))
                        messages.append(str(outcome))
                        success += 1
                    except Exception as exc:
                        failed += 1
                        messages.append(f"#{item['song_id']} ไม่สำเร็จ: {exc}")
            return success,failed,messages or ['ไม่มีการเปลี่ยนแปลง']
        self.app.start_index_job(work,deduplicate=False)

    def _validate_report_row(self, item):
        # Reports are snapshots: never act on a changed/replaced song ID or path.
        checks=[(item['song_id'],item['path'])]
        if item['keeper_id']:
            checks.append((item['keeper_id'],item['keeper_path']))
        for ident, expected in checks:
            row = self.app.library.get(ident)
            if row is None or str(row['path']) != expected:
                raise ValueError('รายงานล้าสมัย: รายการเพลงหรือพาธเปลี่ยน กรุณาสร้างรายงานใหม่')


    def hide(self):
        rows=self.selected()
        if not rows:return
        if any(r['category']!='exact' for r in rows):
            return messagebox.showwarning('ยังยืนยันไม่ครบ','ซ่อนจากรายการซ้ำได้เมื่อยืนยัน SHA-256 ทั้งชุดแล้ว',parent=self.window)
        if not messagebox.askyesno('ซ่อนรายการ','ซ่อนเฉพาะ '+str(len(rows))+' รายการที่เลือก? ไฟล์ยังอยู่ที่เดิม',parent=self.window):return
        self.run_actions(lambda r:actions.hide_exact(self.app.library,r['song_id'],r['keeper_id'],
                                                    protected=lambda:protected_ids(self.app)),rows)

    def exclude(self):
        rows=self.selected()
        if not rows:return
        if not messagebox.askyesno('เอารายการออกจากฐาน',
          f'นำออกจากผลค้นหา {len(rows)} รายการ โดยไฟล์ยังอยู่ตำแหน่งเดิม?\nสแกนรอบถัดไปจะไม่เพิ่มรายการกลับเอง',
          parent=self.window,default='no'):return
        self.run_actions(lambda r:actions.exclude_from_index(self.app.library,r['song_id'],
                                                         protected=lambda:protected_ids(self.app)),rows)

    def delete(self,permanent):
        rows=self.selected()
        if not rows:return
        if any(r['category']!='exact' for r in rows):
            return messagebox.showwarning('ต้องตรวจ SHA-256',
                'ลบไฟล์จริงได้เฉพาะชุดที่ยืนยันเหมือนกัน 100% ให้กดตรวจ SHA-256 ก่อน',parent=self.window)
        # Inspect all bundles and display actual file counts and bytes before
        # asking for confirmation; execution repeats the content verification.
        files=0;bytes_=0
        try:
            for r in rows:
                _,parts,_=prepare_action(self.app.library,r['song_id'],
                        protected=protected_ids(self.app),keeper_id=r['keeper_id'])
                files+=len(parts);bytes_+=sum(Path(p).stat().st_size for p in parts.values())
        except Exception as error:
            return self.app.show_error(error)
        action='ลบถาวร' if permanent else 'ส่งเข้าถังรีไซเคิล'
        summary=f'{action} {len(rows)} เพลง / {files} ไฟล์ ({bytes_/1024**2:.1f} MB)\n'+ \
               'ระบบตรวจชุดเพลงหลักก่อนเสมอ ไม่กักแยก และไม่สำรองเนื้อหาไฟล์เพลง\n'+ \
               'การลบถาวรกู้คืนจากโปรแกรมไม่ได้'
        if not messagebox.askyesno(action,summary+'\n\nต้องการดำเนินการหรือไม่?',parent=self.window,default='no'):return
        if permanent and simpledialog.askstring('ยืนยันลบถาวร','พิมพ์ ลบถาวร เพื่อยืนยัน\n'+summary,parent=self.window)!='ลบถาวร':return
        self.run_actions(lambda r:actions.delete_permanently(self.app.library,r['song_id'],r['keeper_id'],
                                   protected=lambda:protected_ids(self.app),confirmation='ลบถาวร') if permanent else
                                   actions.send_to_recycle_bin(self.app.library,r['song_id'],r['keeper_id'],
                                   protected=lambda:protected_ids(self.app)),rows)

    def unhide(self):
        rows=self.selected()
        if not rows:return
        self.run_actions(lambda r:actions.show_song(self.app.library,r['song_id']),rows)

    def restore_by_id(self):
        """Restore excluded/hidden records omitted from visible duplicate reports."""
        raw = simpledialog.askinteger('คืนรายการจากฐาน',
            'ใส่ ID เพลงที่เคยซ่อนหรือนำออกจากฐาน (ไฟล์ต้นทางต้องอยู่)',
            parent=self.window, minvalue=1)
        if raw is None:return
        row = self.app.library.get(raw)
        if not row or row['duplicate_state'] not in ('excluded','manual_hidden'):
            return messagebox.showwarning('ไม่พบรายการ',
                'ID นี้ไม่ใช่รายการที่เคยซ่อนหรือนำออกจากฐาน',parent=self.window)
        if not messagebox.askyesno('คืนรายการ',f"คืนเพลง #{raw}: {row['title']} เข้าผลค้นหา?",
                                   parent=self.window,default='no'):return
        def restore():
            if row['duplicate_state']=='excluded':actions.restore_to_index(self.app.library,raw)
            else:actions.show_song(self.app.library,raw)
            return 'คืนรายการ #' + str(raw)
        def work():
            try:return 1,0,[restore()]
            except Exception as error:return 0,1,[str(error)]
        self.app.start_index_job(work,deduplicate=False)


def open_exact_duplicates(app):
    previous=getattr(app,'duplicate_review_window',None)
    if previous and previous.window.winfo_exists():
        previous.window.lift();return previous
    manager=DuplicateReviewWindow(app)
    app.duplicate_review_window=manager
    return manager


def open_duplicates(app):
    return open_exact_duplicates(app)
