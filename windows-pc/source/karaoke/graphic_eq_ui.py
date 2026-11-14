"""Compact hardware rack; real loopback band RMS / sample peak LEDs."""
import copy
import time
import tkinter as tk
from tkinter import filedialog,messagebox,ttk,simpledialog
from .graphic_eq import CENTRES,flat,validate,band_rms
from .eq_meter import WindowsMix,dbfs
from .equalizer import output_for
BG='#10151c';PANEL='#202833';INK='#e3eaf0';ACC='#64dfc9'

class SpectrumCapture(WindowsMix):
    def __init__(self):
        super().__init__();self.frames=None;self.spectrum=None;self.spectrum_stamp=0.;self.next_fft=0.;self.last_device=None
    def start(self):
        if not (self.thread and self.thread.is_alive()):self.frames=None;self.spectrum=None;self.spectrum_stamp=0.
        super().start()
    def feed(self,frames):
        import numpy as np
        if self.last_device!=self.name:
            self.frames=None;self.spectrum=None;self.spectrum_stamp=0.;self.last_device=self.name
        super().feed(frames)
        data=np.asarray(frames)
        self.frames=data.copy() if self.frames is None else np.concatenate((self.frames,data))[-32768:]
        now=time.monotonic()
        if len(self.frames)==32768 and now>=self.next_fft:
            values=band_rms(self.frames);self.next_fft=now+.1
            with self.lock:self.spectrum=values;self.spectrum_stamp=now
    def bands(self):
        with self.lock:return list(self.spectrum) if self.spectrum is not None and time.monotonic()-self.spectrum_stamp<.5 and time.monotonic()-self.stamp<.5 else None

def rack_size(area):
    left,top,right,bottom=area
    w=min(1400,max(320,right-left-24));h=min(490,max(240,bottom-top-70))
    return w,h,left+(right-left-w)//2,top+(bottom-top-h)//2

class GraphicEQ(tk.Toplevel):
    def __init__(self,app):
        super().__init__(app);self.app=app;self.configure(bg=BG);self.title('EQ X-Stage Karaoke')
        self.transient(app);self.overrideredirect(True);self.resizable(False,False)
        from .dialog_layout import work_area
        w,h,x,y=rack_size(work_area(self))
        self.base_height=h;self.flow_rows=[]
        self.geometry(f'{w}x{h}+{x}+{y}');self.minsize(min(w,760),min(h,340))
        from .song_eq import selected
        self.state=selected(app.settings,getattr(app,'current_song',None))
        self.saved=copy.deepcopy(self.state);self.capture=SpectrumCapture();self.timer=None;self.drag_band=None;self.active=0;self.seen=False;self.outside=None;self.transition=None;self.wheel_remainder=0.;self.preset_timer=None;self.live_timer=None;self.live_pending=False;self.last_live=0.;self.song_token=self.current_token();self.settings_timer=None;self.settings_dirty=False;self.child_windows=set()
        self.peaks=[-120.,-120.];self.hold_until=[0.,0.];self.clip_until=[0.,0.];self.source=''
        header=tk.Frame(self,bg=BG,padx=12,pady=8);header.pack(fill='x')
        try:
            from PIL import Image,ImageTk
            from .branding import asset
            with Image.open(asset('xstage-logo.jpg')) as im:self.logo=ImageTk.PhotoImage(im.resize((48,48)),master=self)
            tk.Label(header,image=self.logo,bg=BG).pack(side='left',padx=(0,12))
        except (OSError,tk.TclError):pass
        title=tk.Frame(header,bg=BG);title.pack(side='left')
        tk.Label(title,text='EQ X-Stage Karaoke',font=('Leelawadee UI',18,'bold'),fg=INK,bg=BG).pack(anchor='w')
        tk.Label(title,text='31 BAND  •  1/3 OCTAVE  •  STEREO LINK',font=('Tahoma',9),fg=ACC,bg=BG).pack(anchor='w')
        self.button(header,'-',self.dock).pack(side='right',padx=3)
        for widget in (header,title,*title.winfo_children()):
            widget.bind('<Button-1>',self.start_move);widget.bind('<B1-Motion>',self.move_rack)
        bottom=tk.Frame(self,bg=BG,padx=10,pady=8);self.bottom=bottom;self.header=header;bottom.pack(side='bottom',fill='x')
        def panel(parent,title):
            return tk.LabelFrame(parent,text=title,bg=BG,fg='#9db0c3',font=('Leelawadee UI',9),padx=6,pady=4,bd=1,relief='groove')
        presets=panel(bottom,'พรีเซ็ต / เปรียบเทียบ');presets.pack(fill='x',pady=(0,6));self.build_presets(presets)
        panels=tk.Frame(bottom,bg=BG);panels.pack(fill='x');self.control_panels=panels
        sound=panel(panels,'ปรับเสียง');songs=panel(panels,'ค่าเพลง / ไฟล์');self.panel_groups=(sound,songs)
        controls=tk.Frame(sound,bg=BG);controls.pack(fill='x')
        self.bypassbutton=self.button(controls,'BYPASS',self.bypass);self.bypassbutton.pack(side='left',padx=3)
        self.button(controls,'FLAT',self.reset).pack(side='left',padx=3)
        input_group=tk.Frame(controls,bg=BG);input_group.pack(side='left',padx=3)
        tk.Label(input_group,text='INPUT dB',fg=INK,bg=BG,font=('Tahoma',9)).pack(side='left',padx=(4,4))
        self.pre=tk.StringVar(value=str(self.state['preamp_db']))
        self.prebox=tk.Spinbox(input_group,from_=-48,to=0,increment=.5,width=5,textvariable=self.pre,bg=PANEL,fg=INK,buttonbackground=PANEL,command=self.adjust_input);self.prebox.pack(side='left')
        self.prebox.bind('<Return>',lambda e:self.apply())
        self.button(controls,'เผื่อระดับเสียง',self.adjust_headroom).pack(side='left',padx=3)
        self.button(controls,'ใช้ค่า',self.apply).pack(side='left',padx=3)
        song_controls=tk.Frame(songs,bg=BG);song_controls.pack(fill='x')
        for label,cmd in [('จำ EQ เพลงนี้',self.remember_song),('ลบค่าที่จำ',self.forget_song),('จัดการค่าเพลง',self.manage_songs),('นำเข้า',self.load),('ส่งออก',self.save)]:self.button(song_controls,label,cmd).pack(side='left',padx=3)
        for row in (controls,song_controls):row.bind('<Configure>',lambda e,row=row:self.layout_controls(row))
        panels.bind('<Configure>',lambda e:self.layout_panels())
        self.status=tk.StringVar(value=('ค่าระบบเดิมยังทำงาน • กดใช้ค่าเพื่อเปลี่ยนเป็น 31 ช่อง' if 'graphic_eq' not in app.settings and ('parametric_eq' in app.settings or app.settings.get('eq_scope')=='windows') else 'EQ เพลง X-Stage • LED: เสียงรวม Windows • ปรับเสียงสด'))
        self.status_label=tk.Label(bottom,textvariable=self.status,bg=BG,fg='#a8b9ca',anchor='w',font=('Leelawadee UI',9),wraplength=1300)
        self.status_label.pack(fill='x',pady=(6,0),padx=(0,28))
        self.resize_origin=None
        self.grip=tk.Canvas(self,width=24,height=24,bg=BG,highlightthickness=0,cursor='sizing')
        for offset in (5,11,17):self.grip.create_line(offset,22,22,offset,fill=ACC,width=2)
        self.grip.place(relx=1,rely=1,anchor='se')
        self.grip.bind('<Button-1>',self.start_resize)
        self.grip.bind('<B1-Motion>',self.resize_rack)
        self.grip.bind('<ButtonRelease-1>',self.end_resize)
        self.grip.bind('<Enter>',lambda e:self.grip.configure(bg='#344759'))
        self.grip.bind('<Leave>',lambda e:self.grip.configure(bg=BG))
        self.canvas=tk.Canvas(self,bg=PANEL,highlightthickness=1,highlightbackground='#536171');self.canvas.pack(fill='both',expand=True,padx=10,pady=(0,2))
        self.canvas.bind('<Configure>',lambda e:self.draw());self.canvas.bind('<Button-1>',self.press);self.canvas.bind('<B1-Motion>',self.drag);self.canvas.bind('<ButtonRelease-1>',self.release)
        self.canvas.bind('<Double-Button-1>',self.zero);self.canvas.bind('<Left>',lambda e:self.select(-1));self.canvas.bind('<Right>',lambda e:self.select(1));self.canvas.bind('<Up>',lambda e:self.step(.5));self.canvas.bind('<Down>',lambda e:self.step(-.5))
        for event in ('<MouseWheel>','<Button-4>','<Button-5>'):self.canvas.bind(event,self.wheel)
        self.bind('<Escape>',self.dock);self.protocol('WM_DELETE_WINDOW',self.dock);self.bind('<Destroy>',self.cleanup,add='+')
        if getattr(app,'current_song',None):self.update_status()
        self.screen_check=0.;self.poll()
    def start_resize(self,event):
        self.resize_origin=(event.x_root,event.y_root,self.winfo_width(),self.winfo_height())
        self.outside=None
        return 'break'
    def resize_rack(self,event):
        if not self.resize_origin:return 'break'
        from .dialog_layout import work_area
        from .eq_ui_state import resize_size
        px,py,w,h=self.resize_origin
        area=work_area(self,use_owner=False)
        required=self.header.winfo_reqheight()+self.bottom.winfo_reqheight()+170
        width,height=resize_size((w+event.x_root-px,h+event.y_root-py),
            (area[2]-self.winfo_x(),area[3]-self.winfo_y()),required)
        self.base_height=height
        self.geometry(f'{width}x{height}')
        return 'break'
    def end_resize(self,event):
        self.resize_origin=None;self.fit_to_screen();self.outside=None
        return 'break'
    def layout_panels(self):
        wide=self.control_panels.winfo_width()>=980
        if getattr(self,'panels_wide',None)==wide:return
        self.panels_wide=wide
        for group in self.panel_groups:group.grid_forget()
        for i,group in enumerate(self.panel_groups):group.grid(row=0 if wide else i,column=i if wide else 0,sticky='nsew',padx=(0,6) if wide and i==0 else 0,pady=(0,4))
        self.control_panels.columnconfigure(0,weight=1,uniform='panels')
        self.control_panels.columnconfigure(1,weight=1 if wide else 0,uniform='panels' if wide else '')
    def layout_controls(self,row):
        from .eq_interaction import flow_positions
        if row not in self.flow_rows:self.flow_rows.append(row)
        widgets=row.winfo_children();sizes=[(w.winfo_reqwidth(),w.winfo_reqheight()) for w in widgets]
        signature=(row.winfo_width(),tuple(sizes))
        if getattr(row,'flow_signature',None)==signature:return
        row.flow_signature=signature
        positions,height=flow_positions(sizes,row.winfo_width())
        for widget,(x,y,w,h) in zip(widgets,positions):
            widget.pack_forget();widget.grid_forget();widget.place(x=x,y=y,width=w,height=h)
        row.configure(height=height)
    def queue_settings_save(self):
        # Keep the current default in memory immediately so normal app shutdown saves it.
        # Per-song edits remain explicit: this never writes song_eq automatically.
        if not getattr(self.app,'current_song',None):self.app.settings['graphic_eq']=copy.deepcopy(self.saved)
        self.app.settings['eq_scope']='xstage';self.settings_dirty=True
        if self.settings_timer:self.after_cancel(self.settings_timer)
        self.settings_timer=self.after(350,self.flush_settings)
    def flush_settings(self):
        if self.settings_timer:self.after_cancel(self.settings_timer);self.settings_timer=None
        if not self.settings_dirty:return
        try:self.app.save_settings();self.settings_dirty=False
        except Exception as error:
            self.status.set('ยังบันทึกการตั้งค่าไม่ได้ • '+str(error))
            self.app.show_error(error)
    def adjust_input(self):
        self.manual()
        if self.apply(persist=False):self.queue_settings_save()
    def child_open(self):
        self.child_windows={w for w in self.child_windows if w.winfo_exists()}
        return any(w.winfo_ismapped() for w in self.child_windows)
    def update_status(self):
        from .eq_ui_state import status
        song=getattr(self.app,'current_song',None);out=output_for(getattr(self.app,'engine',None))
        processor=getattr(out,'_parametric_eq',None)
        applied=bool(processor and getattr(processor,'handles',None) and processor.state==self.saved)
        self.status.set(status(self.saved,self.app.settings,song,bool(out),applied))
    def adjust_headroom(self):
        self.manual()
        from .eq_presets import compensate
        processor=getattr(output_for(getattr(self.app,'engine',None)),'_parametric_eq',None)
        rates={44100,48000}
        if processor:rates.add(processor.rate)
        self.transition_to(compensate(self.state,rates))
    def fit_to_screen(self):
        from .dialog_layout import work_area
        from .eq_ui_state import clamp_rack
        self.update_idletasks()
        area=work_area(self,use_owner=False)
        for row in self.flow_rows:self.layout_controls(row)
        self.update_idletasks()
        required=self.header.winfo_reqheight()+self.bottom.winfo_reqheight()+170
        height=max(self.base_height,required)
        x,y,w,h=clamp_rack((self.winfo_x(),self.winfo_y(),self.winfo_width(),height),area)
        self.minsize(min(760,w),min(340,h))
        if (x,y,w,h)!=(self.winfo_x(),self.winfo_y(),self.winfo_width(),self.winfo_height()):
            self.geometry(f'{w}x{h}+{x}+{y}')
    def manage_songs(self):
        from .song_eq_ui import open_manager
        window=open_manager(self);self.child_windows.add(window);self.outside=None
    def current_token(self):
        from .song_eq import key
        return (id(getattr(self.app,'engine',None)),key(getattr(self.app,'current_song',None)))
    def sync_song(self):
        token=self.current_token()
        if token==self.song_token:return
        self.cancel_transition()
        if self.preset_timer:self.after_cancel(self.preset_timer);self.preset_timer=None
        if self.live_timer:self.after_cancel(self.live_timer);self.live_timer=None
        self.live_pending=False;self.drag_band=None;self.song_token=token
        from .song_eq import selected,remembered
        self.state=selected(self.app.settings,getattr(self.app,'current_song',None));self.saved=copy.deepcopy(self.state)
        self.pre.set(str(self.state['preamp_db']));self.preset_base=copy.deepcopy(self.state);self.amount.set(100)
        from .eq_presets import Compare
        self.compare=Compare(self.state);self.ab.configure(text='A / B : A');self.preset_name.set('กำหนดเอง')
        self.update_status()
        self.draw()
    def remember_song(self):
        self.sync_song()
        song=getattr(self.app,'current_song',None)
        if not song:self.status.set('กรุณาเล่นเพลงก่อนบันทึก EQ');return
        if not output_for(getattr(self.app,'engine',None)):self.status.set('เพลงนี้ไม่ได้ใช้ระบบ BASS จึงยังใช้ EQ นี้ไม่ได้');return
        self.manual()
        if not self.apply():return
        old=copy.deepcopy(self.app.settings)
        try:
            from .song_eq import store
            store(self.app.settings,song,self.saved);self.app.save_settings()
            self.update_status()
        except Exception as error:self.app.settings.clear();self.app.settings.update(old);self.app.show_error(error)
    def forget_song(self):
        song=getattr(self.app,'current_song',None)
        if not song:self.status.set('กรุณาเล่นเพลงก่อน');return
        old=copy.deepcopy(self.app.settings)
        try:
            from .song_eq import forget,selected
            forget(self.app.settings,song);self.app.save_settings()
            self.preset_base=selected(self.app.settings,None);self.amount.set(100);self.transition_to(self.preset_base)
            self.status.set('ลบค่าประจำเพลง • กลับใช้ EQ กลาง')
        except Exception as error:self.app.settings.clear();self.app.settings.update(old);self.app.show_error(error)
    def flush_live(self):
        self.live_timer=None
        if self.current_token()!=self.song_token:self.sync_song();return
        if self.live_pending:
            self.live_pending=False;self.last_live=time.monotonic();self.apply(persist=False)
    def queue_live(self):
        self.live_pending=True
        if time.monotonic()-self.last_live>=.02:
            if self.live_timer:self.after_cancel(self.live_timer);self.live_timer=None
            self.flush_live()
        elif not self.live_timer:self.live_timer=self.after(20,self.flush_live)
    def build_presets(self,parent):
        from .eq_presets import builtins,Compare
        self.compare=Compare(self.state);self.preset_base=copy.deepcopy(self.state)
        self.presets=builtins()
        for name,value in self.app.settings.get('graphic_eq_presets',{}).items():
            try:self.presets['★ '+name]=validate(value)
            except (ValueError,KeyError,TypeError):pass
        row=tk.Frame(parent,bg=BG);row.pack(fill='x')
        self.preset_name=tk.StringVar(value='กำหนดเอง')
        style=ttk.Style(self);style.configure('XStageEQ.TCombobox',fieldbackground=PANEL,background='#344454',foreground=INK)
        style.map('XStageEQ.TCombobox',fieldbackground=[('readonly',PANEL)],foreground=[('readonly',INK)])
        self.combo=ttk.Combobox(row,style='XStageEQ.TCombobox',textvariable=self.preset_name,values=list(self.presets),state='readonly',width=21)
        self.combo.pack(side='left',padx=3);self.combo.bind('<<ComboboxSelected>>',self.choose_preset)
        self.amount=tk.DoubleVar(value=100)
        amount_group=tk.Frame(row,bg=BG);amount_group.pack(side='left',padx=4)
        self.amount_label=tk.Label(amount_group,text='ความเข้ม 100%',bg=BG,fg=INK,font=('Leelawadee UI',10),width=13,anchor='e');self.amount_label.pack(side='left')
        self.amount.trace_add('write',lambda *args:self.amount_label.configure(text=f'ความเข้ม {self.amount.get():.0f}%'))
        self.amount_scale=tk.Scale(amount_group,from_=0,to=100,orient='horizontal',variable=self.amount,showvalue=False,length=150,bg=BG,fg=INK,highlightthickness=0)
        self.amount_scale.pack(side='left',padx=4)
        for event in ('<B1-Motion>','<ButtonRelease-1>','<KeyRelease>'):self.amount_scale.bind(event,self.queue_preset)
        self.auto=tk.BooleanVar(value=True)
        tk.Checkbutton(row,text='ชดเชยพรีเซ็ต',variable=self.auto,command=self.use_preset,bg=BG,fg=INK,selectcolor=PANEL,activebackground=BG,activeforeground=INK,font=('Leelawadee UI',10)).pack(side='left',padx=3)
        self.ab=self.button(row,'A / B : A',self.switch_ab);self.ab.pack(side='left',padx=3)
        self.button(row,'บันทึกพรีเซ็ต',self.save_named).pack(side='left',padx=3)
        self.preset_layout=None
        row.bind('<Configure>',lambda e:self.layout_presets(row))
    def layout_presets(self,row):self.layout_controls(row)
    def start_move(self,e):self.move_origin=(e.x_root-self.winfo_x(),e.y_root-self.winfo_y())
    def move_rack(self,e):
        dx,dy=self.move_origin;self.geometry(f'{e.x_root-dx:+d}{e.y_root-dy:+d}');self.fit_to_screen()
    def cancel_transition(self):
        self.bypass_target=None
        if self.transition:self.after_cancel(self.transition);self.transition=None
    def queue_preset(self,*args):
        if self.preset_timer:self.after_cancel(self.preset_timer)
        self.preset_timer=self.after(120,self.use_preset)
    def choose_preset(self,e=None):
        self.preset_base=copy.deepcopy(self.presets[self.preset_name.get()]);self.amount.set(100);self.use_preset()
    def use_preset(self):
        from .eq_presets import intensity,compensate
        if self.preset_timer:self.after_cancel(self.preset_timer);self.preset_timer=None
        target=intensity(self.preset_base,self.amount.get())
        if self.auto.get():
            rates={44100,48000}
            for engine in (getattr(self.app,'engine',None),getattr(getattr(self.app,'_medley_decks',None),'tail',None)):
                p=getattr(output_for(engine),'_parametric_eq',None)
                if p:rates.add(p.rate)
            target=compensate(target,rates)
        self.transition_to(target)
    def transition_to(self,target,on_success=None):
        if self.live_timer:self.after_cancel(self.live_timer);self.live_timer=None
        self.live_pending=False
        self.cancel_transition();target=validate(target);start=copy.deepcopy(self.saved)
        # Short bounded parameter ramp. It is not a sample-accurate click-free guarantee.
        token=self.current_token()
        def tick(n):
            if token!=self.current_token():self.transition=None;self.sync_song();return
            self.transition=None
            from .eq_interaction import ramp_frame
            value=ramp_frame(start,target,n/8)
            self.state=value;self.pre.set(f"{value['preamp_db']:.2f}")
            if not self.apply(persist=n==8,track=False):
                self.state=start;self.pre.set(str(start['preamp_db']));self.apply(track=False);return
            if n<8:self.transition=self.after(20,lambda:tick(n+1))
            else:
                if on_success:on_success()
                self.compare.store(self.state)
        tick(1)
    def switch_ab(self):
        self.compare.store(self.saved)
        def done():
            self.compare.switch();self.ab.configure(text='A / B : '+('B' if self.compare.index else 'A'))
            self.preset_base=copy.deepcopy(self.state);self.preset_name.set('กำหนดเอง');self.amount.set(100)
        self.transition_to(self.compare.other(),done)
    def save_named(self):
        name=simpledialog.askstring('บันทึกพรีเซ็ต','ชื่อพรีเซ็ต',parent=self)
        if not name or not name.strip():return
        name=name.strip()[:60];key='★ '+name
        if key in self.presets and not messagebox.askyesno('บันทึกทับ','แทนที่พรีเซ็ตชื่อนี้หรือไม่?',parent=self):return
        old=copy.deepcopy(self.app.settings)
        try:
            value=validate(self.saved)
            self.app.settings.setdefault('graphic_eq_presets',{})[name]=value;self.app.save_settings()
            self.presets[key]=copy.deepcopy(value);self.combo.configure(values=list(self.presets));self.preset_name.set(key);self.preset_base=value;self.amount.set(100)
        except Exception as error:self.app.settings.clear();self.app.settings.update(old);self.app.show_error(error)
    def wheel(self,e):
        from .eq_presets import wheel_steps
        self.wheel_remainder+=wheel_steps(getattr(e,'delta',0),getattr(e,'num',None))
        whole=int(self.wheel_remainder)
        if whole:self.wheel_remainder-=whole;self.step(.5*whole)
        return 'break'
    def manual(self):
        self.sync_song();self.cancel_transition();self.bypass_target=None
        if self.preset_timer:self.after_cancel(self.preset_timer);self.preset_timer=None
        self.preset_name.set('กำหนดเอง')
    def button(self,parent,text,command):
        return tk.Button(parent,text=text,command=command,bg='#344454',fg=INK,activebackground='#50687e',activeforeground='white',relief='raised',bd=1,padx=8,pady=5,font=('Leelawadee UI',10))
    def geometry_parts(self):
        w=max(320,self.canvas.winfo_width());h=max(150,self.canvas.winfo_height())
        return w,h,38,max(32,(w-132))/31,50,h-56
    def draw(self):
        if not hasattr(self,'canvas'):return
        c=self.canvas;c.delete('all');w,h,left,step,top,base=self.geometry_parts();mid=(top+base)/2
        self.status_label.configure(wraplength=max(280,w-20))
        self.bypassbutton.configure(bg='#d38428' if self.state['bypass'] else '#344454')
        # Shared scale is dB gain. LEDs alongside each fader are digital band RMS.
        for gain in (-12,-6,0,6,12):
            yy=top+(12-gain)/24*(base-top);c.create_line(left-5,yy,w-94,yy,fill='#566777' if gain==0 else '#2c3946');c.create_text(18,yy,text=f'{gain:+}',fill='#9badbd',font=('Tahoma',8))
        bands=self.capture.bands() if self.winfo_ismapped() else None
        for i,f in enumerate(CENTRES):
            x=left+i*step;centre=x+step*.42;gain=self.state['bands'][i]['gain_db'];yy=top+(12-gain)/24*(base-top)
            c.create_text(x+step/2,(17+12*(i%2) if step<28 else 23),text=f'{f/1000:g}k' if f>=1000 else str(f),fill=INK,font=('Tahoma',8))
            c.create_rectangle(centre-2,top,centre+2,base,fill='#060a0f',outline='#475464')
            c.create_rectangle(centre-step*.24,yy-7,centre+step*.24,yy+7,fill='#b6c4cf' if i==self.active else '#748595',outline='#e0e9ee' if i==self.active else '#475464')
            c.create_line(centre-step*.2,yy,centre+step*.2,yy,fill='#152536')
            self.led(x+step*.78,top,base,max(2,step*.12),dbfs(bands[i]) if bands else -120,12)
            c.create_text(x+step/2,base+16+(12*(i%2) if step<32 else 0),text=(f'{gain:+.1f}' if abs(gain)>=.05 else '0.0'),fill=ACC if gain else '#a6b3c0',font=('Tahoma',8))
        now=time.monotonic();values=getattr(self,'levels',None)
        for i,name in enumerate(('L','R')):
            x=w-69+i*29;db=dbfs(values[i]) if values else -120
            if db>=self.peaks[i] or now>=self.hold_until[i]:self.peaks[i]=db;self.hold_until[i]=now+1
            if db>=0:self.clip_until[i]=now+1
            c.create_text(x+6,23,text=name,fill=INK,font=('Tahoma',11,'bold'))
            self.led(x,top,base,13,db,24)
            if values and self.peaks[i]>-60:
                yy=base-min(1,max(0,(self.peaks[i]+60)/60))*(base-top);c.create_line(x-1,yy,x+14,yy,fill='white')
            c.create_text(x+6,base+18,text='—' if values is None else ('−∞' if db<-99 else f'{db:.0f}'),fill=INK,font=('Tahoma',8))
            c.create_text(x+6,base+34,text='CLIP',fill='#ff5055' if values and now<self.clip_until[i] else '#526171',font=('Tahoma',7))
        c.create_text(left,h-10,anchor='w',text='LED WINDOWS: '+(self.capture.error or self.capture.name or 'รอสัญญาณ')[:45]+'  |  BAND RMS / L-R SAMPLE PEAK −60…0 dBFS',fill='#97aabd',font=('Tahoma',8))
    def led(self,x,top,base,width,db,count):
        spacing=(base-top)/count
        for n in range(count):
            threshold=-60+(n+1)*60/count;yy=base-(n+1)*spacing
            color='#47d993' if threshold<-12 else '#efcb4b' if threshold<-3 else '#ef5656'
            self.canvas.create_rectangle(x,yy,x+width,yy+max(1,spacing-2),fill=color if db>=threshold else '#14202b',outline='')
    def press(self,e):
        w,h,left,step,top,base=self.geometry_parts()
        if left<=e.x<left+31*step:
            self.active=max(0,min(30,int((e.x-left)/step)));self.wheel_remainder=0.;self.canvas.focus_set();self.draw()
        if left<=e.x<left+31*step and top-8<=e.y<=base+8:self.manual();self.drag_band=max(0,min(30,int((e.x-left)/step)));self.active=self.drag_band;self.canvas.focus_set();self.drag(e)
    def drag(self,e):
        if self.drag_band is None:return
        *_,top,base=self.geometry_parts();v=round(max(-12,min(12,12-24*(e.y-top)/max(1,base-top)))*2)/2
        self.state['bands'][self.drag_band]['gain_db']=v;self.draw();self.queue_live()
    def release(self,e):
        if self.drag_band is not None:
            if self.live_timer:self.after_cancel(self.live_timer);self.live_timer=None
            self.live_pending=False;self.drag_band=None;self.apply()
    def zero(self,e):
        self.press(e)
        if self.drag_band is not None:self.state['bands'][self.drag_band]['gain_db']=0.;self.drag_band=None;self.apply()
    def select(self,delta):self.active=max(0,min(30,self.active+delta));self.draw();return 'break'
    def step(self,delta):
        self.manual();b=self.state['bands'][self.active];b['gain_db']=max(-12,min(12,b['gain_db']+delta))
        if self.apply(persist=False):self.queue_settings_save()
        return 'break'
    def bypass(self):
        target=copy.deepcopy(getattr(self,'bypass_target',None) or self.saved)
        target['bypass']=not target['bypass'];self.manual()
        self.transition_to(target,lambda:setattr(self,'bypass_target',None))
        self.bypass_target=target if self.transition else None
    def reset(self):self.manual();self.transition_to(flat())
    def apply(self,persist=True,track=True):
        if track:self.cancel_transition()
        if getattr(self.app,'current_song',None) and not output_for(getattr(self.app,'engine',None)):
            self.update_status();return False
        from .parametric_eq import apply
        from .eq_scope import suspend_windows_eq
        old_settings=copy.deepcopy(self.app.settings) if persist else self.app.settings.copy();changed=[];apo=None
        try:
            self.state['preamp_db']=float(self.pre.get());state=validate(self.state)
            apo=suspend_windows_eq(old_settings)
            decks=getattr(self.app,'_medley_decks',None)
            for engine in ([getattr(self.app,'engine',None)] if getattr(self.app,'current_song',None) else [getattr(self.app,'engine',None),getattr(decks,'tail',None)]):
                out=output_for(engine)
                if out:
                    old=getattr(out,'_parametric_eq',None);changed.append((engine,copy.deepcopy(old.state) if old else None));apply(engine,state)
            if persist:
                if not getattr(self.app,'current_song',None):self.app.settings['graphic_eq']=copy.deepcopy(state)
                self.app.settings['eq_scope']='xstage';self.app.save_settings()
                if self.settings_timer:self.after_cancel(self.settings_timer);self.settings_timer=None
                self.settings_dirty=False
            self.saved=copy.deepcopy(state)
            if track:
                self.compare.store(state);self.preset_base=copy.deepcopy(state);self.amount.set(100)
            self.update_status()
        except Exception as error:
            self.app.settings.clear();self.app.settings.update(old_settings)
            try:
                if apo:
                    from .system_eq import atomic_write
                    atomic_write(*apo)
                for engine,old in reversed(changed):
                    if old:apply(engine,old)
                    else:
                        p=getattr(output_for(engine),'_parametric_eq',None)
                        if p:p.close()
                        from .equalizer import apply as legacy
                        legacy(engine,old_settings.get('output_eq',[0,0,0]))
            except Exception as restore_error:self.app.show_error(restore_error)
            self.state=copy.deepcopy(self.saved);self.pre.set(str(self.saved['preamp_db']))
            self.status.set('ยังไม่ใช้ค่า: '+str(error));self.app.show_error(error);self.draw();return False
        self.draw();return True
    def save(self):
        import json
        from pathlib import Path
        try:
            self.state['preamp_db']=float(self.pre.get());state=validate(self.state)
            path=filedialog.asksaveasfilename(parent=self,defaultextension='.json',initialfile='X-Stage-31-band.json')
            if path:Path(path).write_text(json.dumps(state,indent=2),encoding='utf-8')
        except Exception as e:self.app.show_error(e)
    def load(self):
        import json
        from pathlib import Path
        path=filedialog.askopenfilename(parent=self,filetypes=[('31-band EQ','*.json')])
        if not path:return
        try:
            if Path(path).stat().st_size>65536:raise ValueError('ไฟล์ใหญ่เกินไป')
            self.manual();self.state=validate(json.loads(Path(path).read_text(encoding='utf-8')));self.pre.set(str(self.state['preamp_db']));self.apply()
        except Exception as e:self.app.show_error(e)
    def dock(self,event=None):
        if self.child_open():return 'break'
        self.flush_settings();self.withdraw();self.capture.stop();self.levels=None;self.app.lift();self.app.focus_set();return 'break'
    def show(self):
        self.seen=False;self.outside=None;self.show_until=time.monotonic()+2
        self.deiconify();self.update_idletasks();self.fit_to_screen();self.lift();self.focus_set()
    def poll(self):
        self.timer=None
        self.sync_song()
        if self.winfo_ismapped():
            if time.monotonic()-self.screen_check>1:
                self.screen_check=time.monotonic();self.fit_to_screen()
            if not self.capture.thread or (self.capture.stop_event.is_set() and not self.capture.thread.is_alive()):self.capture.start()
            self.levels=self.capture.read()
            if self.source!=self.capture.name:self.source=self.capture.name;self.peaks=[-120.]*2;self.hold_until=[0.,0.];self.clip_until=[0.,0.]
            self.draw()
            x,y=self.winfo_pointerxy();inside=self.winfo_rootx()<=x<self.winfo_rootx()+self.winfo_width() and self.winfo_rooty()<=y<self.winfo_rooty()+self.winfo_height()
            if inside:self.seen=True;self.outside=None
            elif self.child_open() or self.resize_origin is not None:self.outside=None
            elif time.monotonic()>=getattr(self,'show_until',0) and self.seen and self.drag_band is None and self.transition is None and not self.tk.call('grab','current'):
                if self.outside is None:self.outside=time.monotonic()
                elif time.monotonic()-self.outside>1.2:self.dock()
        self.timer=self.after(100 if self.winfo_ismapped() else 250,self.poll)
    def cleanup(self,e):
        if e.widget is self:
            self.flush_settings();self.capture.stop();self.cancel_transition()
            if self.live_timer:self.after_cancel(self.live_timer);self.live_timer=None
            if self.preset_timer:self.after_cancel(self.preset_timer);self.preset_timer=None
            if self.timer:self.after_cancel(self.timer);self.timer=None

def open_window(app):
    old=getattr(app,'_graphic_eq_window',None) or getattr(app,'_eq_window',None)
    if old is None or not old.winfo_exists():old=GraphicEQ(app)
    app._graphic_eq_window=old;app._eq_window=old
    # Creation must follow the same map/lift/focus path as reopening.
    old.show()
    return old
