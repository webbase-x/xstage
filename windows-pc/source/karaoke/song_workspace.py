"""Unified library controls; independent read-only search never changes stage selection."""
import queue
import sqlite3
import threading
import ntpath
import copy
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from .dialog_layout import ActionBar, scrollable_tree
from .lister import TYPES, locations
from .library import SearchReader, SearchCancelled


class CatalogSearch:
    """One worker, latest query wins; no Tk calls or shared SQLite connection."""
    def __init__(self, path):
        self.path=path;self.requests=queue.Queue();self.results=queue.Queue()
        self.revision=0;self.closed=threading.Event()
        self._active_reader=None
        self.thread=threading.Thread(target=self.run,daemon=True,name='catalog-browser');self.thread.start()

    def submit(self, text):
        self.revision+=1
        self.requests.put((self.revision,text))
        return self.revision

    def run(self):
        reader=None
        from .name_duplicates import NameIndex
        names=NameIndex()
        try:
            while not self.closed.is_set():
                request=self.requests.get()
                if request is None:return
                while not self.requests.empty():
                    request=self.requests.get()
                    if request is None:return
                revision,text=request
                try:
                    if reader is None:reader=SearchReader(self.path);self._active_reader=reader
                    rows=reader.search(text,limit=5000,cancelled=lambda:self.closed.is_set() or revision!=self.revision)
                    names.refresh(reader.db,lambda:self.closed.is_set() or revision!=self.revision)
                    names.annotate(rows)
                    self.results.put((revision,rows,reader.count(),None))
                except SearchCancelled:pass
                except Exception as error:self.results.put((revision,[],0,str(error)))
        finally:
            self._active_reader=None
            if reader is not None:reader.close()
            names.close()

    def close(self):
        self.closed.set();self.requests.put(None)
        reader=self._active_reader
        if reader is not None:
            try:reader.interrupt()
            except sqlite3.Error:pass
        if self.thread is not threading.current_thread():self.thread.join(timeout=1)


class WorkspaceControls:
    def __init__(self, job):
        self.job=job;self.app=job.app;self.pending=None;self.last_roots=None
        self.reader=CatalogSearch(self.app.library.path)
        self.rows={};self.page=0;self.revision=0;self.ready_revision=-1
        section=ttk.Frame(job.window.content)
        section.pack(fill='x',padx=20,pady=(8,0))
        self.sources_open=True
        self.sources_button=ttk.Button(section,text='▾ แหล่งเพลง',command=self.toggle_sources)
        self.sources_button.pack(anchor='w')
        frame=self.sources=ttk.Frame(section,padding=(0,6))
        frame.pack(fill='x')
        row=ttk.Frame(frame);row.pack(fill='x')
        self.app.song_folder_type=tk.StringVar(value='ทุกประเภท')
        ttk.Label(row,text='ประเภท').pack(side='left',padx=(0,8))
        ttk.Combobox(row,textvariable=self.app.song_folder_type,values=list(TYPES),state='readonly',width=24).pack(side='left')
        ttk.Button(row,text='+ เพิ่มโฟลเดอร์…',command=lambda:self.invoke(self.app.add_folder)).pack(side='left',padx=8)
        ttk.Button(row,text='นำออก',command=self.remove_folder).pack(side='left')
        ttk.Button(row,text='ย้ายโฟลเดอร์คลังเพลง…',command=self.relocate_catalog).pack(side='left',padx=8)
        box,self.folders=scrollable_tree(frame,columns=('type','path'),show='headings',height=1)
        box.pack(fill='x',pady=(6,0))
        for key,title,width in [('type','ประเภท',150),('path','ตำแหน่งไฟล์เพลง',700)]:
            self.folders.heading(key,text=title);self.folders.column(key,width=width,minwidth=80)
        options=ActionBar(frame,padding=(0,4));options.pack(fill='x')
        self.app.import_copy_var=tk.BooleanVar(value=False)
        # Import always references original media; users move files to Songs themselves.
        # Keep import_copy_var for compatibility with existing callbacks, but no UI toggle.
        self.force=tk.BooleanVar(value=False)
        ttk.Checkbutton(options,text='อ่านรายละเอียดใหม่ทั้งคลัง',variable=self.force).pack(side='left')
        self.busy_buttons=[]
        for title,callback in [('เพิ่มไฟล์…',self.app.add_files),('นำเข้าคลังเดิม…',self.app.connect_catalog),('จัดการเพลงซ้ำ…',self.duplicates)]:
            b=ttk.Button(options,text=title,command=lambda cb=callback:self.invoke(cb));b.pack(side='left');self.busy_buttons.append(b)

    def toggle_sources(self):
        self.set_sources_open(not self.sources_open)

    def set_sources_open(self, opened):
        self.sources_open=opened
        if opened:self.sources.pack(fill='x')
        else:self.sources.pack_forget()
        self.sources_button.configure(text=('▾' if opened else '▸')+f' แหล่งเพลง ({len(locations(self.app.settings))} โฟลเดอร์)')

    def build_actions(self, parent):
        self.start=ttk.Button(parent,text='เริ่มสร้างรายการ',style='Accent.TButton',command=lambda:self.invoke(lambda:self.app.rebuild_library(force=self.force.get())))
        self.start.pack(side='left');self.busy_buttons.append(self.start)

    def build_catalog(self, book):
        frame=ttk.Frame(book,padding=8);book.add(frame,text='รายชื่อเพลงในคลัง')
        row=ttk.Frame(frame);row.pack(fill='x')
        ttk.Label(row,text='ค้นหาเพลง / ศิลปิน / รหัส').pack(side='left',padx=(0,8))
        self.query=tk.StringVar()
        entry=ttk.Entry(row,textvariable=self.query,font=('Leelawadee UI',12));entry.pack(side='left',fill='x',expand=True)
        entry.bind('<Return>',lambda event:self.search())
        self.query.trace_add('write',self.schedule)
        ttk.Button(row,text='ล้าง',command=lambda:self.query.set('')).pack(side='left',padx=6)
        ttk.Button(row,text='รีเฟรช',command=self.search).pack(side='left')
        box,self.catalog=scrollable_tree(frame,style='Job.Treeview',columns=('code','title','artist','key','type','status'),show='headings',height=4,selectmode='browse')
        box.pack(fill='both',expand=True,pady=6)
        for key,title,width in [('code','รหัส',90),('title','ชื่อเพลง',390),('artist','นักร้อง',190),('key','คีย์',60),('type','ชนิด',80),('status','สถานะ',180)]:
            self.catalog.heading(key,text=title);self.catalog.column(key,width=width,minwidth=60)
        self.catalog.tag_configure('duplicate',foreground='#e5ae56')
        self.catalog.bind('<<TreeviewSelect>>',self.select)
        self.catalog.bind('<Double-1>',lambda event:self.details())
        self.summary=tk.StringVar(value='กำลังอ่านรายชื่อเพลง…')
        ttk.Label(frame,textvariable=self.summary).pack(anchor='w')
        self.selection=tk.StringVar(value='เลือกเพลงเพื่อดูตำแหน่งไฟล์หรือแก้ไขข้อมูล')
        self.path_label=ttk.Label(frame,textvariable=self.selection,wraplength=900)
        buttons=ActionBar(frame);buttons.pack(fill='x')
        self.prev=ttk.Button(buttons,text='‹ ก่อนหน้า',command=lambda:self.turn(-1));self.prev.pack(side='left')
        self.next=ttk.Button(buttons,text='ถัดไป ›',command=lambda:self.turn(1));self.next.pack(side='left')
        self.song_buttons=[]
        for title,callback in [('รายละเอียด',self.details),('แก้ข้อมูล',self.edit),('เพลงโปรด ★',self.favorite)]:
            b=ttk.Button(buttons,text=title,command=callback,state='disabled');b.pack(side='left');self.song_buttons.append(b)
        self.search()

    def invoke(self, callback):
        try:callback()
        except Exception as error:self.app.show_error(error)

    def duplicates(self):
        from .duplicate_dialog import open_duplicates
        open_duplicates(self.app)

    def relocate_catalog(self):
        from .path_relocate import preview, apply
        old=filedialog.askdirectory(parent=self.job.window,title='เลือกโฟลเดอร์คลังเพลงเดิม')
        if not old:return
        new=filedialog.askdirectory(parent=self.job.window,title='เลือกโฟลเดอร์คลังเพลงใหม่')
        if not new:return
        self.app.status_var.set('กำลังตรวจสอบพาธคลังเพลง…')
        def worker():
            try:
                rows=preview(self.app.library.path,old,new)
                self.app.after(0, lambda rows=rows: finish(rows,None))
            except Exception as error:self.app.after(0,lambda: finish(None,error))
        def finish(rows,error):
            if error:self.app.show_error(error);return
            if not rows:
                messagebox.showinfo('ย้ายโฟลเดอร์คลังเพลง','ไม่พบเพลงใต้โฟลเดอร์เดิม',parent=self.job.window);return
            missing=sum(not row['exists'] for row in rows)
            detail=f'พบ {len(rows):,} เพลง จะอัปเดตพาธแบบธุรกรรมเดียว'
            if missing:detail+=f' • ไม่พบไฟล์ปลายทาง {missing:,} รายการ'
            detail+=' • ไฟล์เพลงจริงจะไม่ถูกย้าย'
            if not messagebox.askyesno('ยืนยันการย้ายพาธ',detail,parent=self.job.window):return
            settings_before=copy.deepcopy(self.app.settings);result=None
            try:
                result=apply(self.app.library.path,old,new)
                from .path_relocate import remap_path_settings
                remap_path_settings(self.app.settings,{row['old']:row['new'] for row in result['preview']})
                old_norm=ntpath.normcase(ntpath.normpath(old));new_norm=ntpath.normpath(new)
                for folder in self.app.settings.get('song_folders',[]):
                    current=ntpath.normcase(ntpath.normpath(str(folder.get('path',''))))
                    if current==old_norm or current.startswith(old_norm+ntpath.sep):
                        suffix=current[len(old_norm):].lstrip('\\/')
                        folder['path']=ntpath.join(new_norm,suffix) if suffix else new_norm
                legacy=self.app.settings.get('legacy_root')
                if isinstance(legacy,str):
                    legacy_norm=ntpath.normcase(ntpath.normpath(legacy))
                    if legacy_norm==old_norm or legacy_norm.startswith(old_norm+ntpath.sep):
                        suffix=legacy_norm[len(old_norm):].lstrip('\\/')
                        self.app.settings['legacy_root']=ntpath.join(new_norm,suffix) if suffix else new_norm
                self.app.settings['song_folders']=locations(self.app.settings)
                self.app.save_settings();self.app.refresh_library();self.app.refresh_queue()
                self.last_roots=None;self.search()
                messagebox.showinfo('ย้ายสำเร็จ',f"อัปเดต {result['updated']:,} รายการ",parent=self.job.window)
            except Exception as error:
                try:
                    if result is not None:apply(self.app.library.path,new,old)
                    self.app.settings.clear();self.app.settings.update(settings_before);self.app.save_settings()
                except Exception as rollback_error:self.app.show_error(f'กู้คืนไม่สมบูรณ์: {rollback_error}')
                self.app.show_error(error)
        threading.Thread(target=worker,daemon=True,name='relocate-preview').start()

    def remove_folder(self):
        selected=set(self.folders.selection())
        self.app.settings['song_folders']=[r for i,r in enumerate(locations(self.app.settings)) if str(i) not in selected]
        self.app.save_settings()

    def schedule(self,*_):
        if self.pending is not None:self.app.after_cancel(self.pending)
        self.pending=self.app.after(200,self.search)

    def search(self):
        if self.pending is not None:self.app.after_cancel(self.pending);self.pending=None
        self.revision=self.reader.submit(self.query.get())
        self.summary.set('กำลังค้นหา…')
        self.catalog.selection_remove(*self.catalog.selection())
        for b in self.song_buttons:b.configure(state='disabled')

    def poll(self):
        roots=locations(self.app.settings)
        if roots!=self.last_roots:
            self.folders.delete(*self.folders.get_children())
            for i,r in enumerate(roots):self.folders.insert('','end',iid=str(i),values=(r['type'],r['path']))
            first=self.last_roots is None
            self.last_roots=roots
            self.set_sources_open(False if first and roots else self.sources_open)
        for b in self.busy_buttons:b.configure(state='disabled' if self.app.scanning else 'normal')
        self.select()
        while True:
            try:revision,rows,total,error=self.reader.results.get_nowait()
            except queue.Empty:break
            if revision!=self.revision:continue
            self.ready_revision=revision
            self.rows={str(r['id']):r for r in rows};self.items=rows;self.total=total;self.page=0
            target=getattr(self,'pending_selection',getattr(self.app,'_import_selected_id',None))
            if target is None and rows:target=rows[0].get('name_keeper_id')
            for i,row in enumerate(rows):
                if row['id']==target:self.page=i//100;break
            self.render()
            if error:self.summary.set('อ่านคลังเพลงไม่ได้: '+error)

    def render(self):
        self.catalog.delete(*self.catalog.get_children())
        for r in self.items[self.page*100:(self.page+1)*100]:
            duplicate=r.get('name_duplicate_count',0)>1
            status=('ซ้ำ • รายการแรก #'+str(r['name_keeper_id'])) if duplicate else ''
            self.catalog.insert('','end',iid=str(r['id']),values=(r['code'],('★ ' if r.get('favorite') else '')+r['title'],r['artist'],r.get('key_signature',''),r.get('kind',''),status),tags=('duplicate',) if duplicate else ())
        children=self.catalog.get_children()
        target=str(getattr(self,'pending_selection',getattr(self.app,'_import_selected_id','')))
        if target not in children and children:
            first=self.rows[children[0]]
            keeper=str(first.get('name_keeper_id') or first['id'])
            target=keeper if keeper in children else children[0]
        if target in children:self.catalog.selection_set(target);self.catalog.focus(target);self.catalog.see(target)
        pages=max(1,(len(self.items)+99)//100)
        self.summary.set(f'คลัง {self.total:,} เพลง • พบ {len(self.items):,} รายการ • หน้า {self.page+1} / {pages}'+(' • แสดงสูงสุด 5,000 รายการ กรุณาระบุคำค้นเพิ่ม' if len(self.items)>=5000 else ''))
        self.prev.configure(state='normal' if self.page else 'disabled')
        self.next.configure(state='normal' if self.page+1<pages else 'disabled')
        self.select()

    def turn(self, delta):
        if hasattr(self,'items'):
            self.page=max(0,min((max(1,len(self.items))-1)//100,self.page+delta));self.render()

    def selected(self):
        if self.ready_revision!=self.revision:return None
        ids=self.catalog.selection()
        return self.rows.get(ids[0]) if ids else None

    def select(self,*_):
        row=self.selected()
        self.selection.set(row['path'] if row else '')
        if row:self.path_label.pack(anchor='w',pady=(4,0))
        else:self.path_label.pack_forget()
        for b in self.song_buttons:b.configure(state='normal' if row and not self.app.scanning else 'disabled')

    def details(self):
        row=self.selected()
        if row:messagebox.showinfo('รายละเอียดเพลง',f"{row['code']}  {row['title']}\nนักร้อง: {row['artist']} • คีย์: {row.get('key_signature','')}\n\n{row['path']}",parent=self.job.window)

    def edit(self):
        row=self.selected()
        if not row or self.app.scanning:return
        values=self.app.edit_dialog('แก้ข้อมูลเพลง',[("รหัส",row['code']),("ชื่อเพลง",row['title']),("ศิลปิน",row['artist']),("คีย์ เช่น C, Am",row.get('key_signature',''))])
        if values and values[1].strip():
            self.app.library.edit(row['id'],*values);self.app.refresh_library();self.app.refresh_queue();self.search()

    def favorite(self):
        row=self.selected()
        if row and not self.app.scanning:
            self.app.library.favorite(row['id']);self.app.refresh_library();self.search()

    def close(self):
        self.reader.close()
        if self.pending is not None:self.app.after_cancel(self.pending);self.pending=None
