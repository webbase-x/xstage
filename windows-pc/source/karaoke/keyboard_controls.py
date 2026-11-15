"""Numbered FX and a dedicated Windows software-synth preview session."""
from pathlib import Path

INSTRUMENTS = [('Piano',0),('Bright Piano',1),('Electric Piano',4),('Harpsichord',6),
 ('Vibraphone',11),('Organ',16),('Accordion',21),('Nylon Guitar',24),('Steel Guitar',25),
 ('Electric Guitar',27),('Bass',32),('Violin',40),('Cello',42),('Strings',48),
 ('Trumpet',56),('Saxophone',65),('Flute',73),('Synth Lead',80)]

def fx_folder(app):
    root = Path(app.data_dir).parent if 'data_dir' in app.__dict__ else Path(app.home)
    folder=root/'SoundFx';folder.mkdir(parents=True,exist_ok=True)
    return folder

def fx_file(folder,index):
    if not 1 <= index <= 10:raise ValueError('FX ต้องอยู่ระหว่าง 1–10')
    files={p.name.lower():p for p in Path(folder).iterdir() if p.is_file()}
    for ext in ('.wav','.mp3'):
        path=files.get(f'{index:02d}'+ext)
        if path:return path
    raise ValueError(f'ไม่พบ {index:02d}.wav หรือ {index:02d}.mp3 ใน {folder}')

class PreviewVoice:
    """Use only Microsoft software synth, never the song's/external MIDI port."""
    def __init__(self,factory=None):
        self.factory=factory;self.output=None;self.notes=set();self.program=0;self.sources={}
    def ensure(self):
        if self.output is not None:return
        if self.factory:self.output=self.factory()
        else:
            from .playback import WinMidi
            devices=[i for i,name in WinMidi.devices() if i>=0 and 'microsoft gs' in name.lower()]
            if not devices:raise OSError('ไม่พบ Microsoft GS Wavetable Synth สำหรับคีย์บอร์ดทดลองเสียง')
            self.output=WinMidi(devices[0])
        try:
            self.output.send(bytes([0xc0,self.program]))
            self.output.send(bytes([0xb0,7,80]))
        except Exception:
            self.close();raise
    def select(self,program):
        if not 0<=program<=127:raise ValueError('GM Program ต้องเป็น 0–127')
        self.release();self.program=program
        if self.output:self.output.send(bytes([0xc0,program]))
    def press(self,note,velocity=96,source="mouse"):
        if (source,note) in self.sources:return
        if not 0<=note<=127:raise ValueError('MIDI note ต้องเป็น 0–127')
        self.ensure()
        if note not in self.notes:
            self.output.send(bytes([0x90,note,max(1,min(127,int(velocity)))]));self.notes.add(note)
        self.sources[source,note]=True
    def off(self,note,source="mouse"):
        self.sources.pop((source,note),None)
        if note in self.notes and not any(n==note for _,n in self.sources):
            if self.output:self.output.send(bytes([0x80,note,0]))
            self.notes.discard(note)
    def release_source(self,source):
        for owner,note in tuple(self.sources):
            if owner==source:self.off(note,owner)
    def release(self):
        self.sources.clear()
        if self.output:
            self.output.send(bytes([0xb0,64,0]))
            for note in tuple(self.notes):
                try:self.output.send(bytes([0x80,note,0]))
                finally:self.notes.discard(note)
        self.notes.clear()
    def close(self):
        output=self.output
        try:self.release()
        finally:
            self.output=None
            if output:output.close()

def hit_note(geometry,x,y):
    white,black=geometry
    for n,x1,y1,x2,y2 in reversed(white+black):
        if x1<=x<x2 and y1<=y<y2:return n
    return None


PIANO_KEYS = dict(zip('awsedftgyhujkolp',range(60,76)))

def preview_factory(app):
    def create():
        from .soundfont import normalize_audio
        if normalize_audio(app.settings)['fonts']:
            from .bass import BassSynth
            return BassSynth(app.home/'native'/'x64',settings=app.settings)
        from .playback import WinMidi, MidiPlayer
        if isinstance(app.engine,MidiPlayer) and isinstance(app.engine.output,WinMidi):
            raise OSError('เลือก SoundFont ก่อนเล่นคีย์บอร์ดพร้อมเพลง Windows MIDI')
        devices=[i for i,name in WinMidi.devices() if i>=0 and 'microsoft gs' in name.lower()]
        if not devices:raise OSError('ไม่พบ SoundFont หรือ Microsoft GS Wavetable Synth')
        return WinMidi(devices[0])
    return create
