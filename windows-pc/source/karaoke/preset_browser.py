"""Browse every preset in the selected file without changing song assignments."""
from pathlib import Path
import logging
import tkinter as tk
from tkinter import ttk
from .dialog_layout import ActionBar, scrollable_tree
from .soundfont import inspect_font
from .font_metadata import MetadataLoader


def filter_presets(rows, query='', bank=None):
    tokens=query.casefold().split()
    return [row for row in rows if (bank is None or row[0]==bank) and
            all(t in f'{row[0]} {row[1]} {row[2]}'.casefold() for t in tokens)]


def preview_settings(options, path, bank, preset):
    """Audition the exact source preset; never save this temporary mapping."""
    info=inspect_font(path)
    if info['presets'] is None:
        if (bank,preset)!=(0,0):raise ValueError('SFZ ทดลองได้ที่ Bank 0 / Preset 0')
        mapping={}
    else:
        if (bank,preset) not in [(b,p) for b,p,_ in info['presets']]:raise ValueError('ไม่พบเสียงที่เลือกในไฟล์นี้')
        mapping={('drums' if bank==128 else 'piano'):{'path':path,'bank':bank,'preset':preset}}
    fonts=[dict(row) for row in options['fonts'] if row['path']==path]
    if not fonts:raise ValueError('ไฟล์ที่เลือกไม่อยู่ในชุดเสียง')
    return {'soundfont_audio':dict(options,fonts=fonts),'instrument_fonts':mapping,'soundfont_follow_song':False}


class PresetBrowser:
    def __init__(self, owner, parent):
        self.owner=owner;self.rows=[];self.path=None;self.visible=[];self.cache={}
        self.parent=parent;self.generation=0;self.banks=[]
        self.loader=MetadataLoader();self.poll_id=None;self.pending_view=None
        parent.bind('<Destroy>',self.on_destroy,add='+')
        ttk.Label(parent,text='ทุกเสียงในไฟล์เดียว',style='Sound.TLabel',font=('Leelawadee UI',15,'bold')).pack(anchor='w')
        ttk.Label(parent,text='เพลงเรียกเสียงตาม Bank / Program ที่บันทึกไว้ รวมเสียงไทยและเสียงอื่นที่มีอยู่ในไฟล์',style='Sound.Muted.TLabel',wraplength=780).pack(anchor='w',pady=(4,12))
        self.source=ttk.Combobox(parent,state='readonly',font=('Leelawadee UI',11))
        self.source.pack(fill='x');self.source.bind('<<ComboboxSelected>>',self.load)
        row=ttk.Frame(parent,style='Sound.TFrame');row.pack(fill='x',pady=8)
        ttk.Label(row,text='ค้นหาชื่อเสียง',style='Sound.TLabel').pack(side='left',padx=(0,8))
        self.query=tk.StringVar();entry=ttk.Entry(row,textvariable=self.query);entry.pack(side='left',fill='x',expand=True)
        self.query.trace_add('write',lambda *_:self.render())
        self.bank=ttk.Combobox(row,state='readonly',width=16);self.bank.pack(side='left',padx=(8,0));self.bank.bind('<<ComboboxSelected>>',lambda _:self.render())
        box,self.tree=scrollable_tree(parent,columns=('name','bank','preset'),show='headings',height=5,style='Sound.Treeview',selectmode='browse')
        box.pack(fill='both',expand=True)
        for key,title,width in [('name','ชื่อเสียงในไฟล์',460),('bank','Bank',90),('preset','Preset (0–127)',140)]:
            self.tree.heading(key,text=title);self.tree.column(key,width=width,minwidth=80,stretch=key=='name')
        self.tree.bind('<<TreeviewSelect>>',lambda _:self.update_buttons())
        self.tree.bind('<Double-1>',lambda _:self.play())
        self.info=tk.StringVar()
        ttk.Label(parent,textvariable=self.info,style='Sound.Muted.TLabel',wraplength=780).pack(anchor='w',pady=6)
        actions=ActionBar(parent);actions.pack(fill='x')
        self.play_button=ttk.Button(actions,text='▶ ฟังเสียงที่เลือก',style='Sound.TButton',command=self.play);self.play_button.pack(side='left')
        ttk.Button(actions,text='■ หยุดทดลอง',style='Sound.TButton',command=owner.stop_preview).pack(side='left')
        self.cancel_button=ttk.Button(actions,text='ยกเลิกโหลดรายชื่อ',command=self.cancel_loading,state='disabled');self.cancel_button.pack(side='left')
        ttk.Label(parent,text='ค้นหาได้ด้วยชื่อที่ผู้ทำ SoundFont ตั้งไว้ เช่น Ranat, Khim, Khaen หรือชื่อภาษาไทย • การทดลองไม่เปลี่ยนเสียงของเพลง',style='Sound.Muted.TLabel',wraplength=780).pack(anchor='w',pady=(6,0))
        self.refresh()

    def refresh(self):
        paths=[row['path'] for row in self.owner.fonts]
        self.source['values']=[f'{i+1}. {Path(p).name}' for i,p in enumerate(paths)]
        if paths:
            self.source.current(paths.index(self.path) if self.path in paths else 0)
            self.load()
        else:
            self.cancel_loading()
            self.banks=[]
            self.source.set('เพิ่มไฟล์ที่แท็บชุดเสียงก่อน');self.path=None;self.rows=[];self.bank['values']=['ทุก Bank'];self.bank.current(0);self.render()

    def stop_poll(self):
        if self.poll_id is not None:
            self.parent.after_cancel(self.poll_id)
            self.poll_id=None

    def cancel_loading(self):
        self.stop_poll()
        self.generation=self.loader.cancel()
        self.cancel_button.configure(state='disabled')
        self.pending_view=None
        self.info.set('ยกเลิกโหลดรายชื่อแล้ว')

    def on_destroy(self,event):
        if event.widget is self.parent:
            self.stop_poll()
            self.loader.close()

    def load(self,*_):
        index=self.source.current()
        if not 0<=index<len(self.owner.fonts):return
        self.stop_poll()
        self.path=self.owner.fonts[index]['path'];self.rows=[];self.banks=[]
        self.bank['values']=['ทุก Bank'];self.bank.current(0);self.render()
        self.info.set('กำลังอ่านรายชื่อเสียง… กดยกเลิกได้')
        self.cancel_button.configure(state='normal')
        self.generation=self.loader.submit(self.path)
        token=self.generation
        self.poll_id=self.parent.after(50,lambda:self.poll_load(token))

    def restore_selection(self,state):
        self.pending_view=dict(state)
        if self.rows:self.apply_selection()

    def apply_selection(self):
        state=self.pending_view
        if not state or state.get('path')!=self.path:return
        self.pending_view=None
        if state.get('bank') in self.bank['values']:
            self.bank.set(state['bank']);self.render()
        preset=state.get('preset')
        for index,row in enumerate(self.visible[:1000]):
            if preset and tuple(row[:2])==tuple(preset):
                self.tree.selection_set(str(index));self.tree.see(str(index));break

    def poll_load(self,token):
        if token!=self.generation or not self.parent.winfo_exists():return
        self.poll_id=None
        result=self.loader.take()
        if result is None:
            self.poll_id=self.parent.after(50,lambda:self.poll_load(token))
            return
        current,path,info,error=result
        if current!=token:
            self.poll_id=self.parent.after(50,lambda:self.poll_load(token))
            return
        self.cancel_button.configure(state='disabled')
        if error:
            self.info.set(str(error));return
        self.rows=info['presets'] if info['presets'] is not None else [(0,0,Path(path).stem+' (SFZ)')]
        self.banks=sorted({row[0] for row in self.rows})
        self.bank['values']=['ทุก Bank']+[str(bank) for bank in self.banks];self.bank.current(0)
        self.render();self.apply_selection()
        logging.info('SOUNDFONT_BROWSER load complete presets=%s',len(self.rows))

    def render(self):
        index=self.bank.current()
        bank=self.banks[index-1] if index>0 else None
        self.visible=filter_presets(self.rows,self.query.get(),bank)
        self.tree.delete(*self.tree.get_children())
        # SF2 metadata can contain tens of thousands of rows; bound widget creation.
        for i,(b,p,n) in enumerate(self.visible[:1000]):self.tree.insert('','end',iid=str(i),values=(n,b,p))
        self.info.set(f'พบ {len(self.visible):,} / {len(self.rows):,} เสียง'+(' • แสดง 1,000 เสียงแรก กรุณาค้นหาหรือเลือก Bank เพิ่ม' if len(self.visible)>1000 else ''))
        if self.visible:self.tree.selection_set('0')
        self.update_buttons()

    def update_buttons(self):
        self.play_button.configure(state='normal' if self.tree.selection() else 'disabled')

    def play(self):
        selection=self.tree.selection()
        if selection and self.path:
            b,p,n=self.visible[int(selection[0])]
            self.owner.audition((self.path,b,p,n))
