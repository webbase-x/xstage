"""Nonblocking static coverage report for a selected MIDI file."""
import csv
import queue
import threading
from copy import deepcopy
from pathlib import Path
from tkinter import ttk,filedialog
from .dialog_layout import ActionBar,scrollable_tree

class CoveragePanel:
    def __init__(self,owner,parent):
        self.owner=owner;self.timer=None;self.closed=False;self.rows=[];self.results=queue.Queue();self.busy=False
        ttk.Label(parent,text='ตรวจเสียงที่เพลงเรียกใช้',style='Sound.TLabel',font=('Leelawadee UI',15,'bold')).pack(anchor='w')
        ttk.Label(parent,text='เทียบ Bank / Program กับชุดเสียงที่ตั้งไว้ในหน้าต่างนี้ • ไม่ต้องเริ่มเล่นเพลง',style='Sound.Muted.TLabel',wraplength=780).pack(anchor='w',pady=6)
        bar=ActionBar(parent);bar.pack(fill='x')
        self.pick=ttk.Button(bar,text='เลือกไฟล์ MIDI…',command=self.choose);self.pick.pack(side='left')
        self.current=ttk.Button(bar,text='ตรวจเพลงปัจจุบัน',command=self.current_song);self.current.pack(side='left')
        self.export=ttk.Button(bar,text='ส่งออกรายงาน CSV…',state='disabled',command=self.save_report);self.export.pack(side='left')
        self.status=ttk.Label(parent,text='เลือกเพลงเพื่อเริ่มตรวจ',style='Sound.Muted.TLabel',wraplength=780);self.status.pack(anchor='w',pady=8)
        self.progress=ttk.Progressbar(parent,mode='indeterminate');self.progress.pack(fill='x',pady=4)
        box,self.tree=scrollable_tree(parent,columns=('ch','bank','lsb','preset','status','name','file'),show='headings',height=7,style='Sound.Treeview')
        for key,name,width in [('ch','ช่อง',50),('bank','Bank',60),('lsb','LSB',50),('preset','Program',95),('status','ผลตรวจ',140),('name','ชื่อเสียง / ข้อสังเกต',320),('file','SoundFont',160)]:
            self.tree.heading(key,text=name);self.tree.column(key,width=width,minwidth=40,stretch=key in ('name','file'))
        box.pack(fill='both',expand=True)
        self.note=ttk.Label(parent,text='',style='Sound.Muted.TLabel',wraplength=780);self.note.pack(anchor='w',pady=8)

    def choose(self):
        path=filedialog.askopenfilename(parent=self.owner,title='เลือกเพลงเพื่อตรวจเสียง',filetypes=[('MIDI / EMK','*.mid *.midi *.kar *.emk')])
        if path:self.start(path)

    def current_song(self):
        song=getattr(self.owner.app,'current_song',None)
        if song:self.start(song['path'])
        else:self.status.configure(text='ยังไม่มีเพลงปัจจุบัน • ใช้ปุ่มเลือกไฟล์ MIDI')

    def start(self,path):
        if self.busy:return
        if Path(path).suffix.lower() not in ('.mid','.midi','.kar','.emk'):
            self.status.configure(text='ตรวจได้เฉพาะไฟล์ MIDI / EMK ที่รองรับ');return
        try:
            options=self.owner.collect(validate_files=False)
            if not options['fonts']:raise ValueError('เพิ่ม SoundFont ในแท็บชุดเสียงก่อนตรวจ')
            settings={'soundfont_audio':options,'instrument_fonts':deepcopy(self.owner.app.settings.get('instrument_fonts',{})),
                      'soundfont_follow_song':self.owner.follow_song.get()}
        except ValueError as error:self.status.configure(text=str(error));return
        self.rows=[];self.tree.delete(*self.tree.get_children());self.path=path
        self.busy=True;self.pick.configure(state='disabled');self.current.configure(state='disabled');self.export.configure(state='disabled')
        self.status.configure(text='กำลังตรวจข้อมูลเบื้องหลัง: '+Path(path).name);self.progress.configure(mode='indeterminate');self.progress.start(20)
        def work():
            from .soundfont_coverage import check_song
            try:self.results.put((check_song(path,settings),None))
            except Exception as error:self.results.put((None,str(error)))
        threading.Thread(target=work,daemon=True,name='soundfont-coverage').start();self.poll()

    def poll(self):
        self.timer=None
        if self.closed:return
        try:result,error=self.results.get_nowait()
        except queue.Empty:self.timer=self.owner.after(100,self.poll);return
        self.busy=False;self.progress.stop();self.pick.configure(state='normal');self.current.configure(state='normal')
        if error:self.status.configure(text='ตรวจไม่สำเร็จ: '+error);return
        self.progress.configure(mode='determinate',value=100)
        self.rows,warnings=result
        for row in self.rows[:1000]:self.tree.insert('','end',values=row)
        found=sum(r[4].startswith('พบ') for r in self.rows)
        self.status.configure(text=f'{Path(self.path).name} • ต้องใช้ {len(self.rows)} รายการเสียง • พบ {found} • ต้องตรวจเพิ่ม {len(self.rows)-found}')
        self.note.configure(text='\n'.join(warnings)+('\nแสดง 1,000 รายการแรก ส่งออก CSV เพื่อดูครบ' if len(self.rows)>1000 else ''))
        self.export.configure(state='normal')

    def save_report(self):
        path=filedialog.asksaveasfilename(parent=self.owner,defaultextension='.csv',initialfile='SoundFont-coverage.csv',filetypes=[('CSV','*.csv')])
        if path:
            try:
                with open(path,'w',encoding='utf-8-sig',newline='') as f:
                    writer=csv.writer(f);writer.writerow(['MIDI',self.path]);writer.writerow(['หมายเหตุ',self.note.cget('text')]);writer.writerow(['ช่อง','Bank','LSB','Program','ผลตรวจ','ชื่อเสียง/ข้อสังเกต','SoundFont']);writer.writerows(self.rows)
                self.status.configure(text='ส่งออกรายงานแล้ว')
            except OSError as error:self.status.configure(text='บันทึกไม่ได้: '+str(error))

    def close(self):
        self.closed=True
        if self.timer is not None:self.owner.after_cancel(self.timer);self.timer=None
        try:self.progress.stop()
        except Exception:pass
