"""Hardware-style gain faders backed by the actual parametric EQ draft."""
import tkinter as tk

BG='#161c24';PANEL='#202934';INK='#dce7ec';ACCENT='#65dccb'

class EQRack(tk.Frame):
    def __init__(self,parent,editor):
        super().__init__(parent,bg=BG,bd=2,relief='sunken')
        self.editor=editor;self.loading=False;self.scales=[];self.labels=[];self.readouts=[];self.leds=[];self.axes=[]
        header=tk.Frame(self,bg=BG);header.pack(fill='x',padx=12,pady=(8,2))
        tk.Label(header,text='X-STAGE',font=('Tahoma',12,'bold'),fg=INK,bg=BG).pack(side='left')
        self.bank=tk.Label(header,text='8 BAND  /  DRAFT',font=('Tahoma',9),fg=ACCENT,bg=BG);self.bank.pack(side='right')
        from .eq_meter import PeakMeter
        self.meter=PeakMeter(self,editor.app);self.meter.pack(fill='x',padx=10,pady=(4,6))
        strips=tk.Frame(self,bg=BG);strips.pack(fill='both',expand=True,padx=8,pady=4)
        for i in range(8):
            strips.columnconfigure(i,weight=1,uniform='fader')
            strip=tk.Frame(strips,bg=PANEL,bd=1,relief='flat');strip.grid(row=0,column=i,sticky='nsew',padx=2)
            led=tk.Button(strip,text=f'{i+1}  ●',font=('Tahoma',9,'bold'),bg=PANEL,fg=ACCENT,relief='flat',bd=0,takefocus=True,command=lambda n=i:editor.select_band(n));led.pack(fill='x');self.leds.append(led)
            label=tk.Label(strip,text='',font=('Tahoma',9,'bold'),bg=PANEL,fg=INK);label.pack();self.labels.append(label)
            slot=tk.Frame(strip,bg=PANEL);slot.pack(expand=True)
            axis=tk.Canvas(slot,width=22,height=154,bg=PANEL,highlightthickness=0);axis.pack(side='left');self.axes.append(axis)
            scale=tk.Scale(slot,from_=15,to=-15,resolution=.5,orient='vertical',length=154,width=18,sliderlength=28,showvalue=False,highlightthickness=0,bd=1,relief='flat',bg='#65788a',fg=INK,troughcolor='#080d13',activebackground=ACCENT,sliderrelief='raised')
            scale.pack(side='left',pady=2)
            scale.bind('<ButtonPress-1>',lambda e,n=i:self.begin(n))
            scale.bind('<KeyPress>',lambda e:self.editor.checkpoint(),add='+')
            self.scales.append(scale)
            for event in ('<B1-Motion>','<ButtonRelease-1>','<KeyRelease>'):
                scale.bind(event,lambda e,n=i:self.after_idle(lambda:self.changed(n,self.scales[n].get())),add='+')
            readout=tk.Label(strip,text='0.0',font=('Tahoma',10,'bold'),bg='#080d13',fg=ACCENT,pady=3);readout.pack(fill='x',padx=3,pady=(0,5));self.readouts.append(readout)
        self.legend=tk.Label(self,text='+15 dB  ↑     0 dB = FLAT     ↓  −15 dB',font=('Tahoma',9),bg=BG,fg='#a7b7c4');self.legend.pack(pady=(0,7))
    def begin(self,index):
        if self.editor.commit():self.editor.selected=index;self.editor.checkpoint();self.editor.load_band()
    def changed(self,index,value):
        if self.loading:return
        b=self.editor.state['bands'][index]
        if not b['enabled'] or b['kind'] not in ('bell','low_shelf','high_shelf'):return
        if float(value)==b['gain_db']:return
        b['gain_db']=float(value);self.editor.selected=index;self.editor.load_band();self.editor.dirty()
    def refresh(self):
        self.loading=True
        try:
            advanced=self.editor.mode.get()=='ขั้นสูง';limit=15 if advanced else 6
            for i,b in enumerate(self.editor.state['bands']):
                frequency=b['frequency'];text=f'{frequency/1000:g}k' if frequency>=1000 else f'{frequency:g}'
                self.labels[i].configure(text=text+' Hz')
                usable=b['enabled'] and b['kind'] in ('bell','low_shelf','high_shelf')
                locked=not advanced and abs(b['gain_db'])>6
                # Preserve out-of-range advanced values when returning to simple mode.
                span=15 if locked else limit
                self.scales[i].configure(from_=span,to=-span,state='normal' if usable and not locked else 'disabled')
                self.scales[i].set(b['gain_db'])
                axis=self.axes[i];axis.delete('all')
                for yy,text in ((12,f'+{span}'),(77,'0'),(142,f'−{span}')):
                    axis.create_text(12,yy,text=text,fill='#a7b7c4',font=('Tahoma',7))
                self.readouts[i].configure(text=f"{b['gain_db']:+.1f}" if usable else ('OFF' if not b['enabled'] else b['kind'].replace('_cut','').upper()),fg=ACCENT if usable else '#a7b7c4')
                self.leds[i].configure(fg=ACCENT if b['enabled'] else '#74808e',bg='#344657' if i==self.editor.selected else PANEL)
            self.bank.configure(text=f"8 BAND  /  {self.editor.slot}  /  {'BYPASS DRAFT' if self.editor.state['bypass'] else 'DRAFT'}")
            self.legend.configure(text=f'+{limit} dB  ↑     0 dB = FLAT     ↓  −{limit} dB')
        finally:self.loading=False
