"""MIDI activity display and isolated live keyboard overlay."""
import threading

class NoteMonitor:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()
    def reset(self):
        with self.lock:
            self.held = [set() for _ in range(16)]
            self.sounding = [set() for _ in range(16)]
            self.sustain = [False] * 16
    def feed(self, data):
        if len(data) < 3 or not 0x80 <= data[0] < 0xf0:
            return
        kind, ch = data[0] & 0xf0, data[0] & 15
        note, value = data[1:3]
        with self.lock:
            if kind == 0x90 and value:
                self.held[ch].add(note); self.sounding[ch].add(note)
            elif kind == 0x80 or (kind == 0x90 and not value):
                self.held[ch].discard(note)
                if not self.sustain[ch]: self.sounding[ch].discard(note)
            elif kind == 0xb0:
                if note == 64:
                    self.sustain[ch] = value >= 64
                    if value < 64: self.sounding[ch] = set(self.held[ch])
                elif note == 120:
                    self.held[ch].clear(); self.sounding[ch].clear()
                elif note == 123:
                    self.held[ch].clear()
                    if not self.sustain[ch]: self.sounding[ch].clear()
                elif note == 121:
                    self.sustain[ch] = False; self.sounding[ch] = set(self.held[ch])
    def snapshot(self, channel=None):
        with self.lock:
            channels = range(16) if channel is None else (channel,)
            return frozenset().union(*(self.sounding[ch] for ch in channels))

def note_name(note):
    return ('C','C♯','D','D♯','E','F','F♯','G','G♯','A','A♯','B')[note % 12] + str(note//12-1)

def keyboard_geometry(width, height, count=128, start=0):
    """All 128 MIDI notes fit; draw black keys after white keys."""
    count = 61 if count == 61 else 128
    start = max(0,min(60,(int(start)//12)*12)) if count == 61 else 0
    white_notes = [n for n in range(start,start+count) if n % 12 not in (1,3,6,8,10)]
    step = max(1, width) / len(white_notes)
    white = []; black = []; white_index = 0
    for n in range(start,start+count):
        if n % 12 in (1,3,6,8,10):
            black.append((n,white_index*step-step*.32,0,white_index*step+step*.32,height*.62))
        else:
            white.append((n,white_index*step,0,(white_index+1)*step,height));white_index+=1
    return white, black


def display_key_count(width, mode='auto', scale=1.0):
    """Keep full-range white keys at least 15 logical pixels wide."""
    if str(mode) in ('61', '128'):
        return int(mode)
    white_count = sum(n % 12 not in (1, 3, 6, 8, 10) for n in range(128))
    return 128 if width >= white_count * 15 * max(1.0, scale) else 61


def open_keyboard(app):
    import tkinter as tk
    from tkinter import ttk
    from .playback import MidiPlayer, WinMidi
    from .stage_fx import FxRack
    from .keyboard_controls import PreviewVoice, INSTRUMENTS, fx_folder, fx_file, hit_note, PIANO_KEYS, preview_factory
    previous = app.__dict__.get('_midi_keyboard_window')
    if previous is not None and previous.winfo_exists():
        previous._keyboard_show()
        previous.lift(); return previous
    panel = tk.Frame(app,bg='#10192d',height=max(140,min(220,app.winfo_height()//4)),highlightthickness=1,highlightbackground='#40516b')
    panel.pack_propagate(False)
    app._midi_keyboard_window = panel
    def show():
        # place overlays the stage without changing its geometry or packed siblings.
        margin = min(354, app.winfo_width() // 4)
        width = max(1, app.winfo_width() - margin * 2)
        toolbar_height=layout_controls(width - 100)
        height = max(toolbar_height+100, min(220, app.winfo_height() // 4))
        panel.place(relx=.5, y=0, anchor='n', width=width, height=height)
        panel.lift()
    panel._keyboard_show = show
    def resized(event):
        if event.widget is app and panel.winfo_ismapped(): show()
    app.bind('<Configure>', resized, add='+')
    rack = app.__dict__.setdefault('_fx_rack',FxRack())
    top = tk.Frame(panel,bg='#10192d');top.pack(fill='x',padx=(6,90),pady=6)
    voice=app.__dict__.setdefault('_keyboard_voice',PreviewVoice(preview_factory(app)))
    midi_port=[None]
    def stop_input():
        if midi_port[0]:midi_port[0].close();midi_port[0]=None
        voice.close()
    panel._keyboard_stop_input=stop_input
    def hide():
        input_mode.set('search')
        held_keys.clear()
        stop_input();panel._keyboard_pinned=False;panel.place_forget();app.focus_set()
    def fire(index):
        try:rack.play(fx_file(fx_folder(app),index),.6)
        except (OSError,ValueError,tk.TclError) as error:app.show_error(error)
    style=ttk.Style(panel)
    style.configure('KeyboardFX.TButton',padding=(3,5),font=('Tahoma',10))
    for i in range(10):
        ttk.Button(top,text=f'Fx{i+1}',width=4,style='KeyboardFX.TButton',command=lambda i=i:fire(i+1)).grid(row=0,column=i,sticky='ew',padx=1)
    controls=top
    top.columnconfigure(15,weight=1,minsize=0)
    selected=tk.StringVar(value='ทั้งหมด')
    ttk.Combobox(controls,state='readonly',textvariable=selected,values=['ทั้งหมด']+[str(i) for i in range(1,17)],width=6).grid(row=0,column=10,padx=(6,3))
    instrument=ttk.Combobox(controls,state='readonly',values=[name for name,_ in INSTRUMENTS],width=15)
    instrument.current(0);instrument.grid(row=0,column=11,padx=3)
    def change_instrument(event=None):
        try:voice.select(INSTRUMENTS[instrument.current()][1])
        except OSError as error:stop_input();app.show_error(error)
    instrument.bind('<<ComboboxSelected>>',change_instrument)
    mode = str(app.settings.get('keyboard_display_mode', 'auto'))
    count_var=tk.StringVar(value=mode if mode in ('61','128') else 'อัตโนมัติ')
    start=[int(app.settings.get('keyboard_start',36)) if isinstance(app.settings.get('keyboard_start',36),int) else 36]
    start[0]=max(0,min(60,(start[0]//12)*12))
    count_box=ttk.Combobox(top,state='readonly',textvariable=count_var,values=['อัตโนมัติ','61','128'],width=9)
    count_box.grid(row=0,column=12,padx=2)
    def change_range(event=None,step=0):
        start[0]=max(0,min(60,start[0]+step*12))
        app.settings['keyboard_display_mode']=count_var.get() if count_var.get() in ('61','128') else 'auto'
        app.settings['keyboard_start']=start[0]
        app.save_settings();redraw()
    lower=ttk.Button(top,text='−Oct',width=4,style='KeyboardFX.TButton',command=lambda:change_range(step=-1))
    upper=ttk.Button(top,text='+Oct',width=4,style='KeyboardFX.TButton',command=lambda:change_range(step=1))
    lower.grid(row=0,column=13);upper.grid(row=0,column=14)
    if count_var.get()=='128':lower.configure(state='disabled');upper.configure(state='disabled')
    count_box.bind('<<ComboboxSelected>>',change_range)
    notes_text=tk.StringVar(value='—')
    note_label=ttk.Label(controls,textvariable=notes_text,width=1,anchor='w')
    note_label.grid(row=0,column=16,sticky='ew',padx=6)
    ttk.Button(panel,text='×',width=2,style='KeyboardFX.TButton',command=hide).place(relx=1,x=-5,y=5,anchor='ne',width=28,height=28)
    pin_var=tk.BooleanVar(value=False)
    ttk.Checkbutton(panel,text='ตรึง',variable=pin_var,command=lambda:setattr(panel,'_keyboard_pinned',pin_var.get())).place(relx=1,x=-38,y=5,anchor='ne',width=50,height=28)
    def choose_input():
        from .midi_input import MidiInput
        from .dialog_layout import DialogWindow
        win=DialogWindow(app);win.title('MIDI input');win.geometry('500x280');win.transient(app)
        ttk.Label(win.content,text='อุปกรณ์ MIDI input',font=('Tahoma',14,'bold')).pack(anchor='w',padx=16,pady=(16,4))
        devices=MidiInput.devices()
        choice=ttk.Combobox(win.content,state='readonly',values=['ปิด MIDI input']+[name for _,name in devices],width=38)
        choice.current(0);choice.pack(fill='x',padx=16,pady=16)
        def connect():
            stop_input()
            try:
                if choice.current()>0:
                    voice.ensure();midi_port[0]=MidiInput(devices[choice.current()-1][0]);panel._keyboard_pinned=True
                win.destroy()
            except OSError as error:stop_input();app.show_error(error)
        ttk.Button(win.footer,text='ตกลง',command=connect).pack(pady=8)
    ttk.Button(top,text='MIDI IN',width=7,command=choose_input).grid(row=0,column=15,padx=2)
    input_mode=tk.StringVar(value='search')
    def set_input_mode():
        if input_mode.get()=='play':
            panel._keyboard_pinned=True;canvas.focus_set()
        else:
            lost_focus(None);app.focus_set()
    ttk.Radiobutton(top,text='เล่นคีย์บอร์ด',value='play',variable=input_mode,command=set_input_mode).grid(row=0,column=17)
    ttk.Radiobutton(top,text='ค้นหาเพลง',value='search',variable=input_mode,command=set_input_mode).grid(row=0,column=18)
    toolbar_widgets = sorted([w for w in top.winfo_children() if w is not note_label], key=lambda widget: int(widget.grid_info()['column']))
    def layout_controls(available):
        # Each row uses explicit positions, avoiding shared grid column expansion.
        available=max(1,available);x=0;y=0;row_height=0
        for widget in toolbar_widgets:
            wanted=min(available,widget.winfo_reqwidth()+8)
            height=max(28,widget.winfo_reqheight())
            if x and x+wanted>available:
                y+=row_height+4;x=0;row_height=0
            widget.grid_forget();widget.place(x=x,y=y,width=wanted,height=height)
            x+=wanted+3;row_height=max(row_height,height)
        if available-x<70:y+=row_height+4;x=0;row_height=28
        note_label.grid_forget();note_label.place(x=x,y=y,width=max(1,available-x),height=max(28,row_height))
        top.configure(height=y+max(28,row_height))
        return y+max(28,row_height)+12
    panel._keyboard_hide=hide
    canvas=tk.Canvas(panel,bg='#10192d',highlightthickness=0,takefocus=True)
    canvas.pack(fill='both',expand=True,padx=6,pady=(0,6))
    keys={};last=None;outside_since=None;geometry=([],[])
    def redraw(event=None):
        nonlocal last,geometry
        canvas.delete('all');keys.clear()
        count=display_key_count(canvas.winfo_width(), count_var.get(), app.winfo_fpixels('1i')/96)
        state='normal' if count==61 else 'disabled'
        lower.configure(state=state);upper.configure(state=state)
        geometry=keyboard_geometry(canvas.winfo_width(),canvas.winfo_height(),count,start[0])
        white,black=geometry
        for group,normal in ((white,'#f0f5ff'),(black,'#152139')):
            for n,x1,y1,x2,y2 in group:
                keys[n]=(canvas.create_rectangle(x1,y1,x2,y2,fill=normal,outline='#465570'),normal)
                if n%12==0 and x2-x1>=14:canvas.create_text((x1+x2)/2,y2-12,text=note_name(n),fill='#24344e',font=('Arial',8))
        last=None
    canvas.bind('<Configure>',redraw)
    def press(event):
        input_mode.set('play');set_input_mode()
        note=hit_note(geometry,event.x,event.y)
        try:
            if ("mouse",note) not in voice.sources:
                voice.release_source("mouse")
                if note is not None:voice.press(note)
        except (OSError,ValueError) as error:
            voice.close();app.show_error(error)
        return 'break'
    canvas.bind('<ButtonPress-1>',press)
    canvas.bind('<B1-Motion>',press)
    canvas.bind('<ButtonRelease-1>',lambda event:voice.release_source('mouse'))
    canvas.bind('<Leave>',lambda event:voice.release_source('mouse'))

    held_keys={}
    def piano_down(event):
        key=event.keysym.lower()
        if input_mode.get()!='play':return
        if key in PIANO_KEYS:
            if key not in held_keys:
                try:
                    note=PIANO_KEYS[key];voice.press(note,source=('pc',key));held_keys[key]=note
                except OSError as error:stop_input();app.show_error(error)
            return 'break'
        if key=='escape':
            input_mode.set('search');set_input_mode();return 'break'
        # Do not turn other typed letters into a search while the piano owns focus.
        if event.char and event.char.isprintable():return 'break'
    def piano_up(event):
        key=event.keysym.lower()
        if key in PIANO_KEYS:
            note=held_keys.pop(key,None)
            if note is not None:voice.off(note,('pc',key))
            return 'break'
    def lost_focus(event):
        input_mode.set('search')
        for key,note in tuple(held_keys.items()):voice.off(note,('pc',key))
        held_keys.clear();voice.release_source('mouse')
    canvas.bind('<KeyPress>',piano_down)
    canvas.bind('<KeyRelease>',piano_up)
    canvas.bind('<FocusOut>',lost_focus)

    def refresh():
        nonlocal last,outside_since
        import time
        if not panel.winfo_exists():return
        try:
            rack.pump()
            if midi_port[0]:midi_port[0].drain(voice)
        except OSError as error:stop_input();app.show_error(error)
        if panel.winfo_ismapped():
            pin_var.set(bool(getattr(panel,'_keyboard_pinned',False)))
            x,y=panel.winfo_pointerxy()
            inside=panel.winfo_rootx()<=x<panel.winfo_rootx()+panel.winfo_width() and panel.winfo_rooty()<=y<panel.winfo_rooty()+panel.winfo_height()
            if inside or getattr(panel,'_keyboard_pinned',False) or panel.grab_current() is not None:outside_since=None
            elif outside_since is None:outside_since=time.monotonic()
            elif time.monotonic()-outside_since>.5:hide();outside_since=None
            engine=app.engine
            ch=None if selected.get()=='ทั้งหมด' else int(selected.get())-1
            notes=engine.note_monitor.snapshot(ch) if isinstance(engine,MidiPlayer) else frozenset()
            notes=notes | frozenset(voice.notes)
            if notes!=last:
                names='  '.join(note_name(n) for n in sorted(notes))
                if keys and notes:
                    if min(notes)<min(keys):names='◀ '+names
                    if max(notes)>max(keys):names+=' ▶'
                notes_text.set(names[:65]+('…' if len(names)>65 else '') if names else '—')
                for n,(item,normal) in keys.items():canvas.itemconfigure(item,fill='#ff354b' if n in notes else normal)
                last=notes
        panel.after(33 if panel.winfo_ismapped() else 200,refresh)
    app.update_idletasks()
    show()
    refresh()
    return panel
