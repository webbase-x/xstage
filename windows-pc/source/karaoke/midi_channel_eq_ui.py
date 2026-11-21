"""31-band per-MIDI-channel editor using BASS_MIDI_StreamGetChannel + BASS FX.

The dry MIDI channel stream is the DSP target, not the master stream and not
a separate MIDI scheduler. Changing notes is never required to hear EQ changes.
"""
import copy
import tkinter as tk
from tkinter import ttk
from .dialog_layout import DialogWindow, ActionBar
from .graphic_eq import CENTRES, flat, validate
from .midi_channel_eq import normalized, get, changed
from .playback import MidiPlayer


class ChannelEQWindow(DialogWindow):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title('EQ 31 ย่าน แยกช่องเครื่องดนตรี MIDI · SoundFont')
        self.geometry('840x660')
        self.pending = None
        self.loading = False
        self.channel = 0
        self.states = normalized(app.settings.get('midi_channel_eq', {}))
        self.draft = flat()
        self.status = tk.StringVar()
        body = ttk.Frame(self.content, padding=12)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='31-BAND EQ · CHANNEL INSERT',
                  font=('Leelawadee UI', 16, 'bold')).pack(anchor='w')
        ttk.Label(body, text='ปรับ DSP เฉพาะเสียงแห้งของช่อง MIDI ที่เลือก · ไม่กระทบช่องอื่น / จังหวะ / เนื้อร้อง\nCh10 เป็นเสียงกลองรวม หากต้องการปรับแต่ละชิ้นให้ใช้เมนูโทนกลอง',
                  wraplength=790).pack(anchor='w', pady=6)
        top = ttk.Frame(body)
        top.pack(fill='x', pady=8)
        ttk.Label(top, text='ช่อง MIDI').pack(side='left', padx=4)
        self.selector = ttk.Combobox(
            top, state='readonly', width=21,
            values=[f'Ch {i+1:02}' + (' · กลองรวม' if i == 9 else '')
                    for i in range(16)])
        self.selector.pack(side='left', padx=5)
        self.selector.current(0)
        self.selector.bind('<<ComboboxSelected>>', self.choose)
        self.bypass = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text='Bypass ช่องนี้', variable=self.bypass,
                        command=self.queue).pack(side='left', padx=10)
        ttk.Button(top, text='Flat ช่องนี้', command=self.reset).pack(side='left')
        levels = ttk.Frame(body)
        levels.pack(fill='x', pady=7)
        ttk.Label(levels, text='INPUT dB').pack(side='left')
        self.pre = tk.DoubleVar(value=0.)
        pre = ttk.Spinbox(levels, from_=-48, to=0, increment=.5,
                          width=7, textvariable=self.pre, command=self.queue)
        pre.pack(side='left', padx=6)
        ttk.Label(levels, text='OUTPUT dB').pack(side='left', padx=(16,0))
        self.post = tk.DoubleVar(value=0.)
        post = ttk.Spinbox(levels, from_=-24, to=6, increment=.5,
                           width=7, textvariable=self.post, command=self.queue)
        post.pack(side='left', padx=6)
        for entry in (pre, post):
            entry.bind('<Return>', self.queue)
            entry.bind('<FocusOut>', self.queue)
        ttk.Label(levels, text='เพิ่ม Gain หลายย่านควรลด INPUT เพื่อไม่ให้เสียงแตก').pack(side='left', padx=8)

        container = ttk.Frame(body)
        container.pack(fill='both', expand=True, pady=4)
        self.canvas = tk.Canvas(container, highlightthickness=0)
        scroller = ttk.Scrollbar(container, orient='vertical', command=self.canvas.yview)
        scroller.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.canvas.configure(yscrollcommand=scroller.set)
        self.inner = ttk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window((0,0), window=self.inner, anchor='nw')
        self.inner.bind('<Configure>', lambda _ : self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self.canvas_window, width=e.width))
        self.gains = []
        self.readouts = []
        for i, frequency in enumerate(CENTRES):
            row = ttk.Frame(self.inner, padding=(6,1))
            row.pack(fill='x')
            label = f'{frequency/1000:g} kHz' if frequency >= 1000 else f'{frequency:g} Hz'
            ttk.Label(row, text=label, width=12).pack(side='left')
            var = tk.DoubleVar(value=0.)
            scale = ttk.Scale(row, from_=-12, to=12, variable=var,
                              command=lambda _, index=i: self.queue(index))
            scale.pack(side='left', fill='x', expand=True, padx=8)
            text = ttk.Label(row, width=8)
            text.pack(side='left')
            self.gains.append(var)
            self.readouts.append(text)
        ttk.Label(body, textvariable=self.status, wraplength=790).pack(fill='x', pady=8)
        bar = ActionBar(self.footer)
        bar.pack(fill='x', padx=12, pady=10)
        ttk.Button(bar, text='คืนค่าที่บันทึก', command=self.restore).pack(side='left')
        ttk.Button(bar, text='บันทึก Preset รายช่อง', command=self.save).pack(side='right')
        ttk.Button(bar, text='ปิด', command=self.destroy).pack(side='right')
        self.protocol('WM_DELETE_WINDOW', self.destroy)
        self.bind('<Destroy>', self.cleanup, add='+')
        self.load()

    def active_player(self):
        player = getattr(self.app, 'engine', None)
        if not isinstance(player, MidiPlayer):
            return None
        if not hasattr(player.output, 'set_channel_eq'):
            return None
        return player

    def set_status(self):
        player = getattr(self.app, 'engine', None)
        if self.active_player():
            self.status.set('พร้อมปรับ EQ แยกช่องผ่าน BASS FX · ผลสดมีผลเฉพาะเพลงปัจจุบันจนกว่าจะบันทึก')
        elif isinstance(player, MidiPlayer):
            self.status.set('Windows MIDI ไม่รองรับ EQ รายช่อง · เลือก BASSMIDI และ SoundFont ก่อน')
        else:
            self.status.set('ยังไม่เล่น MIDI ผ่าน SoundFont · สามารถเตรียม Preset แล้วบันทึกสำหรับเพลงถัดไป')

    def cancel_pending(self):
        if self.pending is not None:
            self.after_cancel(self.pending)
            self.pending = None

    def flush_pending(self):
        if self.pending is not None:
            self.cancel_pending()
            self.apply_live()

    def choose(self, event=None):
        self.flush_pending()
        index = self.selector.current()
        if index >= 0:
            self.channel = index
            self.load()

    def load(self):
        self.loading = True
        try:
            self.draft = get(self.states, self.channel)
            self.bypass.set(self.draft['bypass'])
            self.pre.set(self.draft['preamp_db'])
            self.post.set(self.draft['output_db'])
            for i, var in enumerate(self.gains):
                var.set(self.draft['bands'][i]['gain_db'])
                self.readouts[i].configure(text=f"{var.get():+0.1f} dB")
        finally:
            self.loading = False
        self.set_status()

    def queue(self, index=None):
        if self.loading:
            return
        if type(index) is int:
            self.readouts[index].configure(text=f"{self.gains[index].get():+0.1f} dB")
        self.cancel_pending()
        self.pending = self.after(85, self.apply_live)

    def collect(self):
        state = copy.deepcopy(self.draft)
        state['bypass'] = self.bypass.get()
        state['preamp_db'] = self.pre.get()
        state['output_db'] = self.post.get()
        for index, var in enumerate(self.gains):
            state['bands'][index]['gain_db'] = round(var.get() * 2) / 2
        return validate(state)

    def apply_live(self):
        self.pending = None
        try:
            state = self.collect()
            player = self.active_player()
            if player is not None:
                player.set_channel_eq(self.channel, state)
            self.states = changed(self.states, self.channel, state)
            self.draft = state
            if player:
                self.status.set('ใช้ EQ 31 ย่านสดที่ Ch '+str(self.channel+1)+' แล้ว · ยังไม่ได้บันทึก Preset')
            else:
                self.set_status()
        except (OSError, ValueError) as error:
            self.status.set('ใช้ค่า EQ ไม่สำเร็จ: '+str(error))
            self.app.show_error(error)

    def reset(self):
        self.cancel_pending()
        self.draft = flat()
        self.loading = True
        try:
            self.pre.set(0)
            self.post.set(0)
            self.bypass.set(False)
            for var in self.gains:
                var.set(0)
        finally:
            self.loading = False
        for readout in self.readouts:
            readout.configure(text='+0.0 dB')
        self.apply_live()

    def restore(self):
        self.cancel_pending()
        previous = self.states
        self.states = normalized(self.app.settings.get('midi_channel_eq', {}))
        player = self.active_player()
        if player:
            # Undo unsaved edits on other channels, not just the current one.
            for key in sorted(set(previous) | set(self.states), key=int):
                try:
                    player.set_channel_eq(int(key), self.states.get(key, flat()))
                except (OSError, ValueError) as error:
                    self.app.show_error(error)
                    break
        self.load()

    def save(self):
        self.flush_pending()
        previous = self.app.settings.get('midi_channel_eq')
        try:
            self.app.settings['midi_channel_eq'] = normalized(self.states)
            self.app.save_settings()
            self.status.set('บันทึก EQ รายช่องแล้ว · เมื่อเปิดเพลง MIDI ผ่าน BASSMIDI ครั้งถัดไปจะโหลดค่าด้วย')
        except (OSError, ValueError) as error:
            if previous is None:
                self.app.settings.pop('midi_channel_eq', None)
            else:
                self.app.settings['midi_channel_eq'] = previous
            self.app.show_error(error)

    def cleanup(self, event):
        if event.widget is self:
            self.cancel_pending()
            if getattr(self.app, '_midi_channel_eq_window', None) is self:
                self.app._midi_channel_eq_window = None


def open_window(app):
    old = getattr(app, '_midi_channel_eq_window', None)
    if old is not None and old.winfo_exists():
        old.deiconify()
        old.lift()
        return old
    result = ChannelEQWindow(app)
    app._midi_channel_eq_window = result
    return result
