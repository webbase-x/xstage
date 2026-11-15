"""Setup and endpoint selection for Windows-wide EQ."""
import copy
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk,messagebox
from . import system_eq
from .eq_model import flat,validate
from .dialog_layout import ActionBar

class SystemPage(ttk.Frame):
    def __init__(self,editor,notebook):
        super().__init__(notebook,padding=12);self.editor=editor;self.rows=[];self.result=None;self.poll_id=None
        notebook.add(self,text='Windows')
        ttk.Label(self,text='EQ เสียงรวม Windows',font=('Tahoma',14,'bold')).pack(anchor='w')
        ttk.Label(self,text='1. ติดตั้ง Equalizer APO  2. เลือกลำโพงใน Device Selector\n3. เชื่อม X-Stage ครั้งแรก  4. เลือกอุปกรณ์ด้านล่างแล้วใช้ค่า',wraplength=700).pack(anchor='w',pady=6)
        bar=ActionBar(self);bar.pack(fill='x')
        for label,fn in [('ดาวน์โหลด Equalizer APO',lambda:webbrowser.open('https://sourceforge.net/projects/equalizerapo/')),('เลือกอุปกรณ์ใน APO',system_eq.open_selector),('เชื่อม X-Stage ครั้งแรก',lambda:system_eq.setup(editor.app)),('ตรวจสอบอีกครั้ง',self.refresh)]:
            ttk.Button(bar,text=label,command=lambda f=fn:self.run(f)).pack(side='left')
        from .first_run_ui import open_setup
        ttk.Button(self,text='ตั้งค่าเครื่องนี้ / ทดสอบเสียง / ย้ายข้อมูล',command=lambda:open_setup(editor.app)).pack(anchor='w',pady=6)
        self.combo=ttk.Combobox(self,state='readonly',width=30);self.combo.pack(fill='x',pady=8);self.combo.bind('<<ComboboxSelected>>',self.select)
        self.status=tk.StringVar(value='กำลังตรวจอุปกรณ์…');ttk.Label(self,textvariable=self.status,wraplength=700).pack(anchor='w')
        ttk.Label(self,text='มีผลเฉพาะอุปกรณ์ที่ติดตั้ง APO • ASIO / Exclusive อาจไม่ผ่าน EQ\nค่าคงทำงานหลังปิด X-Stage • Bypass ปิดเฉพาะชุดของ X-Stage\nการเชื่อมไฟล์สำเร็จไม่ได้ยืนยันว่า APO กำลังประมวลผล ต้องทดลองฟัง',wraplength=700).pack(anchor='w',pady=8)
        self.bind('<Destroy>',self.cleanup,add='+');self.refresh()
    def run(self,fn):
        try:fn()
        except Exception as error:self.editor.app.show_error(error)
    def refresh(self):
        if self.poll_id:return
        self.result=None;self.status.set('กำลังตรวจอุปกรณ์…')
        def worker():
            try:
                rows=system_eq.endpoints()
                try:config=system_eq.installation();status='เชื่อมไฟล์แล้ว • ต้องทดสอบเสียงจริง' if system_eq.linked(config) else 'พบ APO • ยังไม่ได้เชื่อม X-Stage'
                except OSError:status='ยังไม่พบ Equalizer APO • ติดตั้งก่อนใช้งาน'
                self.result=(rows,status)
            except Exception as error:self.result=([],str(error))
        threading.Thread(target=worker,daemon=True).start();self.poll_id=self.after(100,self.complete)
    def complete(self):
        self.poll_id=None
        if self.result is None:self.poll_id=self.after(100,self.complete);return
        self.rows,status=self.result;self.combo.configure(values=[name for _,name in self.rows]);self.status.set(status)
        wanted=self.editor.app.settings.get('system_eq_device','')
        if wanted in [id for id,_ in self.rows]:self.combo.current([id for id,_ in self.rows].index(wanted));self.select()
    def selected(self):
        i=self.combo.current()
        if not 0<=i<len(self.rows):raise ValueError('เลือกอุปกรณ์ในแท็บ Windows ก่อน')
        return self.rows[i][0]
    def select(self,event=None):
        device=self.selected();self.editor.rack.meter.capture.target_id=device
        profile=self.editor.app.settings.get('system_eq_profiles',{}).get(device)
        if profile is not None:
            if self.editor.state!=getattr(self.editor,'saved',self.editor.opening):
                if not messagebox.askyesno('เปลี่ยนอุปกรณ์','โหลดค่าเดิมของอุปกรณ์นี้แทนค่าที่กำลังปรับ?',parent=self):return
            self.editor.checkpoint();self.editor.state=validate(profile);self.editor.load_band();self.editor.dirty()
    def cleanup(self,event):
        if event.widget is self and self.poll_id:self.after_cancel(self.poll_id);self.poll_id=None

def apply_system(editor):
    if not editor.commit():return
    from .equalizer import output_for,apply as legacy
    from .parametric_eq import apply as parametric
    device=editor.system_page.selected();settings=editor.app.settings;previous=copy.deepcopy(settings)
    engines=[getattr(editor.app,'engine',None)];decks=getattr(editor.app,'_medley_decks',None)
    if decks:engines.append(decks.tail)
    restore=[];written=None
    try:
        # Neutralize the old per-song chain, so it cannot double the system EQ.
        for engine in engines:
            output=output_for(engine)
            if output is None:continue
            p=getattr(output,'_parametric_eq',None);old=getattr(output,'_equalizer',None)
            if p and p.handles:
                restore.append((engine,'parametric',copy.deepcopy(p.state)))
                bypass=flat();bypass['bypass']=True;p.set(bypass)
            elif old and old.handles:
                restore.append((engine,'legacy',list(old.gains)));old.set([0,0,0])
        written=system_eq.write(editor.state,device)
        settings['eq_scope']='windows';settings['system_eq']=copy.deepcopy(editor.state);settings['system_eq_device']=device
        settings.setdefault('system_eq_profiles',{})[device]=copy.deepcopy(editor.state)
        editor.app.save_settings();editor.saved=copy.deepcopy(editor.state)
        editor.status.set('ส่งค่าไป APO แล้ว • ต้องเปิด APO บนอุปกรณ์นี้และทดสอบฟัง')
    except Exception:
        settings.clear();settings.update(previous)
        errors=[]
        if written:
            try:system_eq.atomic_write(*written)
            except Exception as error:errors.append(str(error))
        for engine,kind,state in reversed(restore):
            try:(parametric if kind=='parametric' else legacy)(engine,state)
            except Exception as error:errors.append(str(error))
        if errors:raise OSError('คืนค่าไม่ครบ: '+'; '.join(errors))
        raise
