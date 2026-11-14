"""Eight-band EQ editor. Edits are staged until Apply; no Python audio callback."""
import copy
import json
import math
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
import numpy as np
from .dialog_layout import DialogWindow,ActionBar
from .eq_model import flat,validate,from_settings,response,peak_gain,headroom
from .equalizer import output_for

LABELS={'bell':'Bell • เพิ่ม/ลดเฉพาะย่าน','low_shelf':'Low Shelf • ย่านทุ้ม','high_shelf':'High Shelf • ย่านแหลม','low_cut':'Low Cut • ตัดทุ้ม','high_cut':'High Cut • ตัดแหลม','notch':'Notch • ตัดเฉพาะจุด'}
COLORS=('#ffbf69','#ffd166','#a9df84','#61dfc4','#58c8f5','#869cff','#bba1ff','#f4a3cb')

class EQWindow(DialogWindow):
    def __init__(self,app,system=False):
        super().__init__(app);self.app=app;self.system=system;self.title('X-STAGE • Parametric EQ');self.geometry('940x700')
        self.viewport.layout=self.layout_body
        self.pending=None;self.selected=0;self.history=[];self.points=[];self.rate=48000
        try:self.state=validate(app.settings.get('system_eq',flat())) if system else from_settings(app.settings)
        except (ValueError,TypeError,KeyError) as error:self.state=flat();app.show_error(error)
        self.opening=copy.deepcopy(self.state);self.slots={'A':copy.deepcopy(self.state),'B':flat()};self.slot='A'
        self.status=tk.StringVar(value='ปรับค่าแล้วกด “ใช้ค่า” เพื่อเปลี่ยนเสียง')
        if 'parametric_eq' not in app.settings and any(app.settings.get('output_eq',[0,0,0])):
            self.status.set('EQ เดิม 3 ย่านยังทำงานอยู่ • กดใช้ค่าเพื่อเปลี่ยนเป็น EQ 8 แบนด์')
        if app.settings.get('eq_scope')=='windows':self.status.set('กดใช้ค่า EQ เพื่อปิดชุด EQ Windows ของ X-Stage เดิม และเปลี่ยนเป็น EQ เพลง')
        self.mode=tk.StringVar(value=app.settings.get('eq_view_mode','ง่าย'))
        self.bypass=tk.BooleanVar(value=self.state['bypass']);self.enabled=tk.BooleanVar()
        self.kind=tk.StringVar();self.frequency=tk.StringVar();self.gain=tk.StringVar();self.width=tk.StringVar()
        self.preamp=tk.StringVar(value=str(self.state['preamp_db']));self.output=tk.StringVar(value=str(self.state['output_db']))
        body=ttk.Frame(self.content,padding=12);body.pack(fill='both',expand=True)
        header=ttk.Frame(body);header.pack(fill='x',pady=(0,8))
        ttk.Label(header,text='X-STAGE  /  PARAMETRIC EQUALIZER',font=('Tahoma',18,'bold')).pack(side='left')
        ttk.Label(header,text='8 BAND • STEREO',font=('Tahoma',10)).pack(side='right')
        ttk.Label(body,text='EQ เพลงผ่าน BASS / SoundFont • มิเตอร์ LED แสดงเสียงรวม Windows',wraplength=1000).pack(anchor='w')
        bar=ActionBar(body);bar.pack(fill='x')
        for mode in ('ง่าย','ขั้นสูง'):
            ttk.Radiobutton(bar,text=mode,variable=self.mode,value=mode,command=self.mode_changed).pack(side='left')
        ttk.Checkbutton(bar,text='Bypass EQ',variable=self.bypass,command=self.toggle_bypass).pack(side='left')
        for name in ('A','B'):
            ttk.Button(bar,text='ชุด '+name,command=lambda n=name:self.select_slot(n)).pack(side='left')
        ttk.Button(bar,text='คัดลอก → B',command=self.copy_slot).pack(side='left')
        from .eq_rack import EQRack
        self.rack=EQRack(body,self);self.rack.pack(fill='x',pady=6)
        lower=ttk.Frame(body);lower.pack(fill='x');lower.columnconfigure(0,weight=3);lower.columnconfigure(1,weight=2)
        graphpage=ttk.Frame(lower);graphpage.grid(row=0,column=0,sticky='nsew',padx=(0,10))
        self.graph=tk.Canvas(graphpage,height=180,width=320,bg='#080e1b',highlightthickness=1,highlightbackground='#293b53')
        self.graph.pack(fill='both',expand=True);self.graph.bind('<Configure>',self.schedule_draw)
        self.graph.bind('<Button-1>',self.pick);self.graph.bind('<B1-Motion>',self.drag)
        self.graph.bind('<ButtonRelease-1>',lambda e:self.load_band())
        self.info=tk.StringVar();ttk.Label(graphpage,textvariable=self.info,wraplength=700).pack(anchor='w',pady=4)
        edit=ttk.LabelFrame(lower,text='แบนด์ที่เลือก',padding=8);edit.grid(row=0,column=1,sticky='nsew')
        self.buttons=[]
        ttk.Checkbutton(edit,text='เปิดแบนด์',variable=self.enabled,command=self.commit).grid(row=0,column=0,sticky='w')
        self.kindbox=ttk.Combobox(edit,textvariable=self.kind,values=list(LABELS.values()),state='readonly',width=23)
        self.kindbox.grid(row=0,column=1,sticky='ew');self.kindbox.bind('<<ComboboxSelected>>',self.kind_changed)
        self.controls=[]
        for row,label,var,low,high,inc in [(1,'ความถี่ • Hz',self.frequency,20,20000,10),(2,'Gain • dB',self.gain,-15,15,.5),(3,'Q',self.width,.1,1,.05)]:
            lab=ttk.Label(edit,text=label);lab.grid(row=row,column=0,sticky='w',padx=(0,12))
            spin=ttk.Spinbox(edit,textvariable=var,from_=low,to=high,increment=inc,width=10,command=self.commit)
            spin.grid(row=row,column=1,sticky='ew',pady=3);spin.bind('<Return>',self.commit);spin.bind('<FocusOut>',self.commit)
            self.controls.append(spin)
            if row==3:self.width_label=lab
        edit.columnconfigure(1,weight=1)
        ttk.Button(edit,text='คืนค่าแบนด์นี้',command=self.reset_band).grid(row=4,column=0,columnspan=2,sticky='ew',pady=4)
        levels=ttk.Frame(body);levels.pack(fill='x',pady=6)
        for col,label,var,low,high in [(0,'PREAMP • dB',self.preamp,-48,0),(2,'OUTPUT • dB',self.output,-24,6)]:
            ttk.Label(levels,text=label).grid(row=0,column=col,padx=8)
            spin=ttk.Spinbox(levels,textvariable=var,from_=low,to=high,increment=.5,width=8,command=self.commit)
            spin.grid(row=0,column=col+1);spin.bind('<Return>',self.commit);spin.bind('<FocusOut>',self.commit)
        ttk.Button(levels,text='เผื่อระดับเสียง',command=self.compensate).grid(row=0,column=4,padx=8)
        pbar=ActionBar(body);pbar.pack(fill='x')
        for label,cmd in [('นำเข้า Preset',self.import_preset),('ส่งออก Preset',self.export_preset),('Flat',self.reset),('คืนค่าตอนเปิด',self.restore)]:
            ttk.Button(pbar,text=label,command=cmd).pack(side='left')
        footer=ttk.Frame(self.footer,padding=(12,8));footer.pack(fill='x')
        ttk.Label(footer,textvariable=self.status,wraplength=1000).pack(fill='x',pady=(0,4))
        actions=ActionBar(footer);actions.pack(fill='x')
        for label,cmd in [('เลิกทำ',self.undo),('ใช้ค่า EQ',self.apply),('จอคาราโอเกะ • Esc',self.show_karaoke),('ปิด EQ',self.close)]:
            ttk.Button(actions,text=label,command=cmd,style='Accent.TButton' if label=='ใช้ค่า EQ' else 'TButton').pack(side='left')
        self.protocol('WM_DELETE_WINDOW',self.close);self.bind('<Destroy>',self.cleanup,add='+')
        self.bind('<Escape>',self.show_karaoke)
        self.lower_panel=lower;self.graph_panel=graphpage;self.edit_panel=edit
        body.bind('<Configure>',self.reflow_panels,add='+')
        self.load_band();self.schedule_draw()
    def fit(self):
        super().fit()
        from .dialog_layout import work_area
        left,top,right,bottom=work_area(self)
        self.geometry(f'{max(320,right-left-16)}x{max(280,bottom-top-48)}{left+8:+d}{top+8:+d}')
        try:self.wm_state('zoomed')
        except tk.TclError:pass
    def reflow_panels(self,event=None):
        narrow=self.content.winfo_width()<1000
        self.graph_panel.grid_configure(row=0,column=0,columnspan=2 if narrow else 1)
        self.edit_panel.grid_configure(row=1 if narrow else 0,column=0 if narrow else 1,columnspan=2 if narrow else 1)
    def show_karaoke(self,event=None):
        self.commit();self.withdraw();self.app.lift();self.app.focus_set()
        return 'break'
    def layout_body(self):
        view=self.viewport;view.pending=None
        width=max(320,view.winfo_width()-view.vertical.winfo_reqwidth())
        view.canvas.itemconfigure(view.item,width=width)
        height=view.content.winfo_reqheight()
        view.canvas.configure(scrollregion=(0,0,width,height))
        view.horizontal.grid_remove()
        if height>view.winfo_height():view.vertical.grid(row=0,column=1,sticky='ns')
        else:view.vertical.grid_remove();view.canvas.yview_moveto(0)
    def checkpoint(self):
        self.history.append(copy.deepcopy(self.state));self.history=self.history[-50:]
    def dirty(self):
        if hasattr(self,'rack'):self.rack.refresh()
        self.status.set('ชุด '+self.slot+' • มีค่ารอใช้ — กด “ใช้ค่า” เพื่อฟัง');self.schedule_draw()
    def commit(self,event=None):
        try:
            candidate=copy.deepcopy(self.state);b=candidate['bands'][self.selected]
            b.update(enabled=self.enabled.get(),frequency=float(self.frequency.get()),gain_db=float(self.gain.get()))
            b['slope' if 'shelf' in b['kind'] else 'q']=float(self.width.get())
            candidate.update(preamp_db=float(self.preamp.get()),output_db=float(self.output.get()))
            candidate=validate(candidate)
            if candidate!=self.state:self.checkpoint();self.state=candidate;self.dirty()
            return True
        except (ValueError,TypeError,tk.TclError) as error:
            self.status.set('ยังไม่ใช้ค่า: '+str(error));return False
    def load_band(self):
        b=self.state['bands'][self.selected]
        self.enabled.set(b['enabled']);self.kind.set(LABELS[b['kind']]);self.frequency.set(f"{b['frequency']:.1f}");self.gain.set(f"{b['gain_db']:.1f}")
        self.width.set(f"{b['slope'] if 'shelf' in b['kind'] else b['q']:.3f}")
        self.width_label.configure(text='ความชัน S' if 'shelf' in b['kind'] else 'Q')
        advanced=self.mode.get()=='ขั้นสูง';self.kindbox.configure(state='readonly' if advanced else 'disabled')
        self.controls[2].configure(state='normal' if advanced else 'disabled')
        gain_used=b['kind'] in ('bell','low_shelf','high_shelf')
        self.controls[1].configure(from_=-15 if advanced else -6,to=15 if advanced else 6,state='normal' if gain_used and (advanced or abs(b['gain_db'])<=6) else 'disabled')
        for i,button in enumerate(self.buttons):button.configure(relief='sunken' if i==self.selected else 'flat',text=f"{'●' if i==self.selected else ''}{i+1}{'' if self.state['bands'][i]['enabled'] else ' −'}")
        self.preamp.set(str(self.state['preamp_db']));self.output.set(str(self.state['output_db']));self.bypass.set(self.state['bypass'])
        if hasattr(self,'rack'):self.rack.refresh()
    def select_band(self,index):
        if self.commit():self.selected=index;self.load_band();self.schedule_draw()
    def mode_changed(self):
        self.commit();self.load_band();self.schedule_draw()
    def kind_changed(self,event=None):
        self.checkpoint();self.state['bands'][self.selected]['kind']=next(k for k,v in LABELS.items() if v==self.kind.get());self.load_band();self.dirty()
    def toggle_bypass(self):self.checkpoint();self.state['bypass']=self.bypass.get();self.dirty()
    def select_slot(self,name):
        if not self.commit():return
        self.slots[self.slot]=copy.deepcopy(self.state);self.checkpoint();self.slot=name;self.state=copy.deepcopy(self.slots[name]);self.load_band();self.dirty()
    def copy_slot(self):
        if self.commit():self.slots['B']=copy.deepcopy(self.state);self.status.set('คัดลอกชุดปัจจุบันไป B แล้ว')
    def reset_band(self):self.checkpoint();self.state['bands'][self.selected]=flat()['bands'][self.selected];self.load_band();self.dirty()
    def reset(self):self.checkpoint();self.state=flat();self.load_band();self.dirty()
    def restore(self):self.checkpoint();self.state=copy.deepcopy(self.opening);self.load_band();self.dirty()
    def undo(self):
        if self.history:self.state=self.history.pop();self.load_band();self.dirty()
    def compensate(self):
        if self.commit():self.checkpoint();self.state['preamp_db']=round(headroom(self.state),2);self.load_band();self.dirty()
    def import_preset(self):
        path=filedialog.askopenfilename(parent=self,filetypes=[('EQ preset','*.json')])
        if not path:return
        try:
            from pathlib import Path
            if Path(path).stat().st_size>65536:raise ValueError('ไฟล์ Preset ใหญ่เกินไป')
            candidate=validate(json.loads(Path(path).read_text(encoding='utf-8')))
            self.checkpoint();self.state=candidate;self.load_band();self.dirty()
        except Exception as error:self.app.show_error(error)
    def export_preset(self):
        if not self.commit():return
        path=filedialog.asksaveasfilename(parent=self,defaultextension='.json',initialfile='X-Stage-EQ.json',filetypes=[('EQ preset','*.json')])
        if path:
            try:
                from pathlib import Path
                Path(path).write_text(json.dumps(validate(self.state),ensure_ascii=False,indent=2),encoding='utf-8')
                self.status.set('ส่งออก Preset แล้ว')
            except Exception as error:self.app.show_error(error)
    def apply(self):
        if self.system:
            try:
                from .system_eq_ui import apply_system
                apply_system(self)
            except Exception as error:self.app.show_error(error)
            return
        if not self.commit():return
        from .parametric_eq import apply
        engines=[getattr(self.app,'engine',None)]
        decks=getattr(self.app,'_medley_decks',None)
        if decks:engines.append(decks.tail)
        engines=[e for e in engines if output_for(e)]
        previous=copy.deepcopy(self.app.settings);applied=[];apo_restore=None
        try:
            from .eq_scope import suspend_windows_eq
            apo_restore=suspend_windows_eq(previous)
            for engine in engines:
                output=output_for(engine);p=getattr(output,'_parametric_eq',None)
                applied.append((engine,copy.deepcopy(p.state) if p else None))
                apply(engine,self.state)
            self.app.settings['eq_scope']='xstage';self.app.settings['parametric_eq']=copy.deepcopy(self.state);self.app.settings['eq_view_mode']=self.mode.get();self.app.save_settings()
            self.status.set('ใช้ EQ กับเพลงที่รองรับแล้ว' if engines else 'บันทึกแล้ว • ใช้กับเพลงถัดไปที่เล่นผ่าน BASS')
            self.saved=copy.deepcopy(self.state)
        except Exception as error:
            self.app.settings.clear();self.app.settings.update(previous)
            if apo_restore:
                try:
                    from .system_eq import atomic_write
                    atomic_write(*apo_restore)
                except Exception as rollback_error:self.app.show_error(rollback_error)
            for engine,old in reversed(applied):
                try:
                    if old is not None:apply(engine,old)
                    else:
                        p=getattr(output_for(engine),'_parametric_eq',None)
                        if p:p.close()
                        from .equalizer import apply as legacy_apply
                        legacy_apply(engine,previous.get('output_eq',[0,0,0]))
                except Exception:pass
            self.app.show_error(error)
    def schedule_draw(self,event=None):
        if self.pending is None:self.pending=self.after_idle(self.draw)
    def draw(self):
        self.pending=None;c=self.graph;c.delete('all');w=max(200,c.winfo_width());h=max(180,c.winfo_height());left,right,top,bottom=45,w-18,20,h-28
        def x(f):return left+math.log10(f/20)/3*(right-left)
        def y(db):return top+(24-max(-24,min(24,db)))/48*(bottom-top)
        for f in (20,50,100,200,500,1000,2000,5000,10000,20000):
            c.create_line(x(f),top,x(f),bottom,fill='#1c2a3d');c.create_text(x(f),bottom+14,text=f'{f//1000}k' if f>=1000 else str(f),fill='#9faec5',font=('Tahoma',8))
        for db in (-24,-12,0,12,24):
            c.create_line(left,y(db),right,y(db),fill='#52677e' if db==0 else '#1c2a3d');c.create_text(left-6,y(db),text=f'{db:+}',anchor='e',fill='#9faec5',font=('Tahoma',8))
        grid=np.unique(np.r_[np.geomspace(20,20000,400),[b['frequency'] for b in self.state['bands']]])
        values=response(self.state,grid,self.rate);coords=[v for f,g in zip(grid,values) for v in (x(f),y(g))]
        c.create_line(*coords,fill='#61dfc4' if not self.state['bypass'] else '#718096',width=2)
        self.points=[]
        for i,b in enumerate(self.state['bands']):
            px=x(b['frequency']);py=y(b['gain_db'] if b['kind'] in ('bell','low_shelf','high_shelf') else 0);self.points.append((px,py))
            r=8 if i==self.selected else 6;c.create_oval(px-r,py-r,px+r,py+r,fill=COLORS[i] if b['enabled'] else '#293b53',outline='white' if i==self.selected else COLORS[i])
        peak=peak_gain(self.state,self.rate);total=0 if self.state['bypass'] else peak+self.state['preamp_db']+self.state['output_db']
        advanced=any(abs(b['gain_db'])>6 or b['kind']!='bell' for b in self.state['bands'])
        self.info.set(('BYPASS • ' if self.state['bypass'] else '')+f'ยอดกราฟ EQ ≈ +{peak:.1f} dB • รวมระดับเสียง ≈ {total:+.1f} dB'+(' • ควรเผื่อระดับเสียง' if total>0 and not self.state['bypass'] else '')+(' • ใช้ค่าขั้นสูง' if advanced and self.mode.get()=='ง่าย' else '')+'\nกราฟจำลองที่ 48 kHz • จุดสีแสดงค่าของแบนด์ เส้นแสดงผลรวม')
    def pick(self,event):
        if not self.points:return
        index=min(range(8),key=lambda i:(self.points[i][0]-event.x)**2+(self.points[i][1]-event.y)**2)
        self.select_band(index);self.checkpoint()
    def drag(self,event):
        b=self.state['bands'][self.selected];w=max(200,self.graph.winfo_width());h=max(180,self.graph.winfo_height())
        b['frequency']=round(20*10**(3*max(0,min(1,(event.x-45)/(w-63)))),1)
        limit=15 if self.mode.get()=='ขั้นสูง' else 6
        if b['kind'] in ('bell','low_shelf','high_shelf') and (limit==15 or abs(b['gain_db'])<=6):b['gain_db']=round(max(-limit,min(limit,24-48*(event.y-20)/(h-48))),1)
        self.load_band();self.dirty()
    def cleanup(self,event):
        if event.widget is self and self.pending:
            self.after_cancel(self.pending);self.pending=None
    def close(self):
        valid=self.commit()
        if (not valid or self.state!=getattr(self,'saved',self.opening)) and not messagebox.askyesno('ปิด EQ','มีค่าที่ยังไม่ได้ใช้ ต้องการปิดหน้าต่างหรือไม่?',parent=self):return
        self.destroy()

def open_window(app):
    from .graphic_eq_ui import open_window as open_graphic
    return open_graphic(app)
