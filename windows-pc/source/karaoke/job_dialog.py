"""Responsive song-job dashboard. UI updates only on the Tk main thread."""
import os
import time
from .dialog_layout import DialogWindow, ActionBar
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from .jobs import percent,timing

BG='#10192d';INK='#ecf2ff';MUTED='#9eacc7';TEAL='#73dadd'

def duration(seconds):
    if seconds is None:return 'กำลังคำนวณ'
    seconds=max(0,int(seconds));hours,rest=divmod(seconds,3600);minutes,seconds=divmod(rest,60)
    return f'{hours:d}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes:02d}:{seconds:02d}'

class JobWindow:
    def __init__(self,app):
        self.app=app
        self.window=DialogWindow(app)
        self.window.title('ศูนย์การนำเข้าและสร้างรายการเพลง — X-Stage')
        self.window.geometry('1120x820');self.window.minsize(680,480)
        self.window.configure(bg=BG);self.window.transient(app)
        self.window.protocol('WM_DELETE_WINDOW',self.hide)
        app.song_manager = self.window
        self.state={};self.last_update=time.monotonic();self.last_elapsed=0;self.timer=None
        self.stage_start=time.monotonic();self.log_path=None;self.cancel_requested=False
        style=ttk.Style(self.window)
        style.configure('Job.Horizontal.TProgressbar',background=TEAL,troughcolor='#22324e',thickness=14)
        from tkinter.font import Font
        row_height=max(28,Font(self.window,family='Leelawadee UI',size=10).metrics('linespace')+12)
        style.configure('Job.Treeview',background='#18253d',fieldbackground='#18253d',foreground=INK,rowheight=row_height,font=('Leelawadee UI',10))
        style.configure('Job.Treeview.Heading',background='#22324e',foreground=INK,font=('Leelawadee UI',10,'bold'))
        header=tk.Frame(self.window.content,bg='#13243e',padx=20,pady=10);header.pack(fill='x')
        tk.Label(header,text='SONG LIBRARY  /  WORKSPACE',bg='#13243e',fg='#73dadd',font=('Segoe UI',10,'bold')).pack(anchor='w')
        tk.Label(header,text='นำเข้าและสร้างรายการเพลง',bg='#13243e',fg='white',font=('Leelawadee UI',19,'bold')).pack(anchor='w',pady=(3,0))
        self.heartbeat=tk.Label(header,text='เตรียมงาน',bg='#13243e',fg='#b7c8df',font=('Leelawadee UI',10))
        self.heartbeat.pack(anchor='w')
        from .song_workspace import WorkspaceControls
        self.workspace = WorkspaceControls(self)
        body=tk.Frame(self.window.content,bg=BG,padx=20,pady=8);body.pack(fill='both',expand=True)
        body.columnconfigure(0,weight=1);body.rowconfigure(5,weight=1)
        top=tk.Frame(body,bg=BG);top.grid(row=0,column=0,sticky='ew');top.columnconfigure(0,weight=1)
        self.phase=tk.Label(top,text='กำลังเตรียมงาน',bg=BG,fg=INK,font=('Leelawadee UI',16,'bold'),anchor='w')
        self.phase.grid(row=0,column=0,sticky='w')
        self.percentage=tk.Label(top,text='—',bg=BG,fg=TEAL,font=('Segoe UI',27,'bold'))
        self.percentage.grid(row=0,column=1,rowspan=2,sticky='e')
        self.phase_count=tk.Label(top,text='กำลังหาจำนวนเป้าหมาย',bg=BG,fg=MUTED,font=('Leelawadee UI',10),wraplength=640,justify='left')
        self.phase_count.grid(row=1,column=0,sticky='w')
        self.bar=ttk.Progressbar(body,style='Job.Horizontal.TProgressbar',mode='indeterminate',maximum=100)
        self.bar.grid(row=1,column=0,sticky='ew',pady=(10,12));self.bar.start(20)
        cards=self.cards=tk.Frame(body,bg=BG);cards.grid(row=2,column=0,sticky='ew')
        self.metrics={}
        for index,(key,title,color) in enumerate([('target','เป้าหมายเพลง',INK),('processed','ตรวจแล้ว',INK),('accepted','รายการพร้อมใช้',TEAL),('rejected','ข้าม / อ่านไม่ได้','#ffcf86'),('duplicates','ซ้ำในรอบนี้','#bdaaff')]):
            cards.columnconfigure(index,weight=1)
            card=tk.Frame(cards,bg='#18253d',padx=12,pady=10,highlightbackground='#22324e',highlightthickness=1)
            card.grid(row=0,column=index,sticky='ew',padx=(0,8) if index<4 else 0)
            tk.Label(card,text=title,bg='#18253d',fg=MUTED,font=('Leelawadee UI',9)).pack(anchor='w')
            value=tk.Label(card,text='0',bg='#18253d',fg=color,font=('Segoe UI',17,'bold'));value.pack(anchor='w');self.metrics[key]=value
        current=self.current=tk.Frame(body,bg=BG);current.grid(row=3,column=0,sticky='ew',pady=(12,8));current.columnconfigure(0,weight=1)
        self.file=tk.Label(current,text='รอเริ่มงาน',bg=BG,fg=INK,font=('Leelawadee UI',10),anchor='w',justify='left',wraplength=980)
        self.file.grid(row=0,column=0,sticky='ew')
        self.time_label=tk.Label(current,text='',bg=BG,fg=MUTED,font=('Leelawadee UI',10),anchor='w')
        self.time_label.grid(row=1,column=0,sticky='ew',pady=(5,0))
        style.configure('Job.TNotebook',background=BG,borderwidth=0)
        style.configure('Job.TNotebook.Tab',background='#22324e',foreground=MUTED,padding=(12,7))
        style.map('Job.TNotebook.Tab',background=[('selected','#18253d')],foreground=[('selected',TEAL)])
        self.book=ttk.Notebook(body,style='Job.TNotebook')
        self.book.grid(row=5,column=0,sticky='nsew',pady=(6,0))
        table=tk.Frame(self.book,bg=BG);table.columnconfigure(0,weight=1);table.rowconfigure(0,weight=1)
        self.book.add(table,text='ผลตรวจล่าสุด (300 รายการ)')
        self.workspace.build_catalog(self.book)
        self.tree=ttk.Treeview(table,style='Job.Treeview',columns=('status','code','title','artist','path'),show='headings',height=6)
        for key,title,width in [('status','ผลตรวจ',80),('code','รหัส',80),('title','ชื่อเพลง',240),('artist','ศิลปิน',160),('path','ตำแหน่งไฟล์',400)]:
            self.tree.heading(key,text=title);self.tree.column(key,width=130 if key=='status' else width,minwidth=60)
        self.tree.grid(row=0,column=0,sticky='nsew')
        scroll=ttk.Scrollbar(table,orient='vertical',command=self.tree.yview);scroll.grid(row=0,column=1,sticky='ns')
        horizontal=ttk.Scrollbar(table,orient='horizontal',command=self.tree.xview);horizontal.grid(row=1,column=0,sticky='ew')
        self.tree.configure(yscrollcommand=scroll.set,xscrollcommand=horizontal.set)
        self.tree.tag_configure('skip',foreground='#ffcf86');self.tree.tag_configure('ok',foreground='#73dadd')
        self.tree.bind('<<TreeviewSelect>>',self.show_row)
        footer=ActionBar(self.window.footer,padding=(16,10));footer.pack(fill='x')
        self.workspace.build_actions(footer)
        self.cancel=ttk.Button(footer,text='ยกเลิกงาน',command=self.request_cancel);self.cancel.pack(side='left')
        ttk.Button(footer,text='ซ่อน / ทำงานต่อ',command=self.hide).pack(side='left',padx=8)
        self.report=ttk.Button(footer,text='เปิดบันทึกทั้งหมด',command=self.open_log,state='disabled');self.report.pack(side='right')
        ttk.Button(footer,text='รายงานสรุป',command=app.show_import_report).pack(side='right',padx=8)
        self.window.bind('<Destroy>',self.cleanup,add='+')
        self.bar.stop()
        self.cancel.configure(state='disabled')
        self.phase.configure(text='พร้อมสร้างรายการเพลง')
        self.phase_count.configure(text='เลือกโฟลเดอร์ แล้วกดเริ่มสร้างรายการ')
        self.window.bind('<Escape>',lambda event:self.hide())
        self.cards.grid_remove();self.current.grid_remove()
        self.bar.configure(mode='determinate',value=0)
        self.book.select(1)
        self.tick();self.show()
        self.window.update_idletasks()
        self.window.geometry('1120x820')
        self.window.fit()

    def reset_job(self):
        self.workspace.set_sources_open(False)
        self.cards.grid();self.current.grid()
        self.state={};self.cancel_requested=False;self.log_path=None
        self.last_update=time.monotonic()
        self.tree.delete(*self.tree.get_children())
        self.cancel.configure(state='normal',text='ยกเลิกงาน')
        self.report.configure(state='disabled')
        self.bar.stop();self.bar.configure(mode='indeterminate',value=0);self.bar.start(20)
        self.percentage.configure(text='—',fg=TEAL)
        self.book.select(0)

    def request_cancel(self):
        self.cancel_requested=True
        self.app.cancel_scan.set()
        self.cancel.configure(state='disabled',text='กำลังยกเลิก…')
        self.phase.configure(text='กำลังยกเลิก — รอชุดปัจจุบันบันทึกให้เสร็จ')

    def show(self):
        self.window.deiconify();self.window.lift()
    def hide(self):self.window.withdraw()
    def cleanup(self,event):
        if event.widget is self.window and self.timer is not None:
            self.app.after_cancel(self.timer);self.timer=None
            self.workspace.close()
    def open_log(self):
        if self.log_path and Path(self.log_path).is_file():
            try:os.startfile(self.log_path)
            except (OSError,AttributeError) as error:self.app.show_error(error)
    def show_row(self,_=None):
        selected=self.tree.selection()
        if selected:
            values=self.tree.item(selected[0],'values')
            self.file.configure(text='รายการที่เลือก: '+str(values[-1]))
    def update(self,packet):
        self.cards.grid();self.current.grid()
        was_finished=self.state.get('finished')
        state=packet['state'];old_phase=self.state.get('phase');old_mode=self.state.get('total')
        self.state=state;self.log_path=state.get('log');self.last_update=time.monotonic()
        if old_phase!=state.get('phase'):self.stage_start=time.monotonic()
        self.phase.configure(text=('กำลังยกเลิก — รอชุดปัจจุบันบันทึกให้เสร็จ' if self.cancel_requested and not state.get('finished') else state.get('phase','')))
        value=percent(state)
        if state.get('finished'):
            self.bar.stop();self.bar.configure(mode='determinate')
            self.cancel.configure(state='disabled')
            if not state.get('cancelled') and not state.get('error'):
                self.bar.configure(value=100);self.percentage.configure(text='100%')
            else:
                self.percentage.configure(text='ยกเลิก' if state.get('cancelled') else 'ผิดพลาด',fg='#b76523')
        elif value is None:
            if old_mode is not None:self.bar.stop();self.bar.configure(mode='indeterminate');self.bar.start(20)
            self.percentage.configure(text='—',fg=TEAL)
        else:
            self.bar.stop();self.bar.configure(mode='determinate',value=value)
            self.percentage.configure(text=f'{value:.1f}%',fg=TEAL)
        total=state.get('total')
        self.phase_count.configure(text=(f"ขั้นตอนนี้: {state.get('done',0):,} / {total:,} รายการ" if total is not None else f"กำลังนับหรือเตรียมงาน • พบแล้ว {state.get('done',0):,} รายการ") + (f"  |  เดิม {state.get('unchanged',0):,} · ใหม่ {state.get('added',0):,} · อัปเดต {state.get('updated',0):,}" if state.get('incremental') else ''))
        for key,widget in self.metrics.items():
            value=state.get(key,0)+(state.get('unsupported',0) if key=='rejected' else 0)
            widget.configure(text=f'{value:,}')
        if state.get('error'):self.file.configure(text=state['error'])
        elif state.get('finished'):self.file.configure(text='งานสิ้นสุดแล้ว — เปิดรายงานสรุปหรือรายการทั้งหมดได้ด้านล่าง')
        elif state.get('path'):self.file.configure(text='กำลังทำงาน: '+state['path'])
        for row in packet.get('rows',[]):
            self.tree.insert('','end',values=(row.get('result') or ('อ่านได้' if row.get('ok') else 'ข้าม'),row.get('code',''),
                row.get('title',''),row.get('artist',''),row.get('path','')),tags=('ok' if row.get('ok') else 'skip',))
        ids=self.tree.get_children()
        if len(ids)>300:self.tree.delete(*ids[:-300])
        if ids:self.tree.see(ids[-1])
        if state.get('finished') and not was_finished:self.workspace.search()
        if state.get('finished') and self.log_path and Path(self.log_path).is_file():self.report.configure(state='normal')

    def tick(self):
        if not self.window.winfo_exists():return
        now=time.monotonic();state=dict(self.state);idle=now-self.last_update
        if not state.get('finished'):
            state['elapsed']=state.get('elapsed',0)+idle
            state['phase_elapsed']=state.get('phase_elapsed',0)+idle
        rate,eta=timing(state)
        if state.get('finished'):
            elapsed=state.get('elapsed',0)
            rate=(state.get('processed',0) or state.get('done',0))/elapsed if elapsed>0 else 0
            eta=None if state.get('cancelled') or state.get('error') else 0
        transfer=''
        if state.get('bytes_total'):
            transfer=f"  •  อ่านไฟล์ {state.get('bytes_done',0)/1048576:,.1f} / {state['bytes_total']/1048576:,.1f} MB"
        self.time_label.configure(text=f"ใช้เวลา {duration(state.get('elapsed',0))}  •  {rate:,.1f} รายการ/วินาที  •  เหลือขั้นตอนนี้ประมาณ {duration(eta)}"+transfer)
        self.workspace.poll()
        if not self.state:
            self.heartbeat.configure(text='เลือกแหล่งเพลง • สร้างรายการ • ค้นหาและดูชื่อเพลงในหน้าต่างเดียว',fg='#b7c8df')
            self.time_label.configure(text='')
        elif state.get('finished'):
            self.heartbeat.configure(text='งานสิ้นสุดแล้ว • ดูสรุปผลและเปิดรายงานฉบับเต็มได้',fg='#b7c8df')
        else:
            self.heartbeat.configure(text=f"● ทำงานเบื้องหลัง • หน้าต่างตอบสนอง • ผลล่าสุด {int(idle)} วินาทีที่แล้ว",
                                     fg='#73dadd' if int(now*2)%2 else '#c5e9f0')
        self.timer=self.app.after(200,self.tick)
