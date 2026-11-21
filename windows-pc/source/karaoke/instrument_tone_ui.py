"""SoundFont-specific per-channel and per-drum controls.

These are BASSMIDI native cutoff/resonance/level controls. They do NOT
pretend to be independent 31-band DSP or modify external Windows MIDI.
"""
import copy
import tkinter as tk
from tkinter import ttk
from .dialog_layout import DialogWindow, ActionBar
from .instrument_tone import (
    CHANNEL_DEFAULT, DRUM_DEFAULT, DRUM_NOTES, changed, get, normalized
)
from .playback import MidiPlayer

class ToneWindow(DialogWindow):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title('โทนเสียงเครื่องดนตรี / กลอง · BASSMIDI')
        self.geometry('760x490')
        self.pending = None
        self.updating = False
        self.preset = normalized(app.settings.get('midi_tone', {}))
        self.kind = 'channels'
        self.index = 0
        self.status = tk.StringVar(value='ปรับ Cutoff และ Resonance แยกช่อง MIDI (ไม่ใช่ EQ 31 ย่านต่อเครื่องดนตรี)')
        body = ttk.Frame(self.content, padding=14)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='SoundFont · ปรับโทนเสียงแยกช่องและชิ้นกลอง',
                  font=('Leelawadee UI', 15, 'bold')).pack(anchor='w', pady=(0, 8))
        ttk.Label(body, text='Cutoff ลด/เพิ่มความสว่างของโทนเสียง · Resonance เน้นบริเวณจุดตัด · 64 คือค่าปกติ\nปรับได้ระหว่างเล่น MIDI ที่ใช้ BASSMIDI + SoundFont เท่านั้น ไม่เปลี่ยนเสียง Windows MIDI',
                  wraplength=700).pack(anchor='w', pady=(0, 10))
        picker = ttk.Frame(body)
        picker.pack(fill='x', pady=5)
        self.mode = tk.StringVar(value='channels')
        for label, value in (('เครื่องดนตรีตามช่อง MIDI', 'channels'), ('ชิ้นกลอง Ch10', 'drums')):
            ttk.Radiobutton(picker, text=label, variable=self.mode, value=value,
                            command=self.switch).pack(side='left', padx=8)
        self.target = ttk.Combobox(body, state='readonly', width=46)
        self.target.pack(fill='x', pady=(4, 10))
        self.target.bind('<<ComboboxSelected>>', self.select)
        self.values = {name: tk.DoubleVar(value=default) for name, default
                       in (('cutoff', 64), ('resonance', 64), ('level', 127))}
        self.rows = {}
        labels = {'cutoff': 'Cutoff · โทนทึบ — สว่าง',
                  'resonance': 'Resonance · ความกังวานที่จุดตัด',
                  'level': 'Level · ความดังชิ้นกลอง'}
        for name in ('cutoff', 'resonance', 'level'):
            row = ttk.Frame(body)
            row.pack(fill='x', pady=4)
            ttk.Label(row, text=labels[name], width=32).pack(side='left')
            scale = ttk.Scale(row, from_=0, to=127, variable=self.values[name],
                              command=lambda _, name=name: self.queue_change())
            scale.pack(side='left', fill='x', expand=True, padx=6)
            readout = ttk.Label(row, width=6)
            readout.pack(side='left')
            self.rows[name] = (row, readout)
        ttk.Label(body, textvariable=self.status, wraplength=700).pack(fill='x', pady=12)
        bar = ActionBar(self.footer)
        bar.pack(fill='x', padx=14, pady=10)
        ttk.Button(bar, text='คืนค่าปกติ (รายการนี้)', command=self.neutral).pack(side='left')
        ttk.Button(bar, text='คืนค่าที่บันทึก', command=self.restore).pack(side='left')
        ttk.Button(bar, text='บันทึก Preset', command=self.save).pack(side='right')
        ttk.Button(bar, text='ปิด', command=self.destroy).pack(side='right')
        self.protocol('WM_DELETE_WINDOW', self.destroy)
        self.bind('<Destroy>', self.cleanup, add='+')
        self.switch()

    def selections(self):
        if self.kind == 'channels':
            return list(range(16)), [f'Ch {i+1:02}' + (' · กลอง' if i == 9 else '')
                                      for i in range(16)]
        return [note for note, _ in DRUM_NOTES], [f'{name} (MIDI {note})' for note, name in DRUM_NOTES]

    def switch(self):
        self.cancel_pending()
        self.kind = self.mode.get()
        indices, labels = self.selections()
        self.target.configure(values=labels)
        self.target.current(0)
        self.index = indices[0]
        self.rows['level'][0].pack(fill='x', pady=4) if self.kind == 'drums' else self.rows['level'][0].pack_forget()
        self.load()

    def select(self, event=None):
        self.cancel_pending()
        indices, _ = self.selections()
        position = self.target.current()
        if 0 <= position < len(indices):
            self.index = indices[position]
            self.load()

    def load(self):
        self.updating = True
        try:
            state = get(self.preset, self.kind, self.index)
            for key, var in self.values.items():
                var.set(state.get(key, 127))
        finally:
            self.updating = False
        self.readouts()
        self.capability_message()

    def readouts(self):
        for name, var in self.values.items():
            self.rows[name][1].configure(text=str(int(round(var.get()))))

    def capability_message(self):
        engine = getattr(self.app, 'engine', None)
        if isinstance(engine, MidiPlayer) and hasattr(engine.output, 'set_channel_tone'):
            self.status.set('BASSMIDI พร้อม · ปรับแล้วมีผลขณะเล่นและบันทึกใช้กับเพลงถัดไปได้')
        elif isinstance(engine, MidiPlayer):
            self.status.set('กำลังใช้ Windows MIDI · ปรับโทนแยกไม่ได้ กรุณาเลือก BASSMIDI + SoundFont')
        else:
            self.status.set('ยังไม่มีเพลง MIDI ผ่าน BASSMIDI · ปรับและบันทึก Preset สำหรับเพลงถัดไปได้')

    def cancel_pending(self):
        if self.pending is not None:
            self.after_cancel(self.pending)
            self.pending = None

    def queue_change(self):
        if self.updating:
            return
        self.readouts()
        self.cancel_pending()
        self.pending = self.after(35, self.apply_live)

    def apply_live(self):
        self.pending = None
        self.preset = changed(self.preset, self.kind, self.index, {
            name: int(round(self.values[name].get()))
            for name in (CHANNEL_DEFAULT if self.kind == 'channels' else DRUM_DEFAULT)
        })
        engine = getattr(self.app, 'engine', None)
        if not isinstance(engine, MidiPlayer):
            self.capability_message()
            return
        if not hasattr(engine.output, 'set_channel_tone'):
            self.capability_message()
            return
        state = get(self.preset, self.kind, self.index)
        try:
            if self.kind == 'channels':
                engine.set_channel_tone(self.index, **state)
            else:
                engine.set_drum_tone(self.index, **state)
            self.status.set('ใช้ค่า Live แล้ว · กดบันทึก Preset หากต้องการใช้ต่อในเพลงถัดไป')
        except (OSError, ValueError) as error:
            self.status.set('ปรับเสียงไม่สำเร็จ: ' + str(error))
            self.app.show_error(error)

    def neutral(self):
        self.cancel_pending()
        self.preset = changed(self.preset, self.kind, self.index,
                              copy.deepcopy(CHANNEL_DEFAULT if self.kind == 'channels' else DRUM_DEFAULT))
        self.load()
        self.apply_live()

    def restore(self):
        self.cancel_pending()
        self.preset = normalized(self.app.settings.get('midi_tone', {}))
        self.load()
        self.apply_live()

    def save(self):
        self.cancel_pending()
        self.apply_live()
        previous = self.app.settings.get('midi_tone')
        try:
            self.app.settings['midi_tone'] = normalized(self.preset)
            self.app.save_settings()
            self.status.set('บันทึกโทนเสียงแล้ว · ใช้กับ MIDI ผ่าน BASSMIDI + SoundFont ในเพลงถัดไป')
        except (OSError, ValueError) as error:
            if previous is None:
                self.app.settings.pop('midi_tone', None)
            else:
                self.app.settings['midi_tone'] = previous
            self.app.show_error(error)

    def cleanup(self, event):
        if event.widget is self:
            self.cancel_pending()
            if getattr(self.app, '_instrument_tone_window', None) is self:
                self.app._instrument_tone_window = None


def open_window(app):
    old = getattr(app, '_instrument_tone_window', None)
    if old is not None and old.winfo_exists():
        old.deiconify()
        old.lift()
        return old
    win = ToneWindow(app)
    app._instrument_tone_window = win
    return win
