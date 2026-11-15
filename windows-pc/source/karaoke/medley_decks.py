"""Preload one supported audio deck; UI owns promotion and overlap lifecycle."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import json
import math
import time

from .medley_full import session

def supported(engine):
    from .playback import MidiPlayer
    from .bass import BassSynth
    from .pcm_player import PcmPlayer
    return isinstance(engine,PcmPlayer) or (isinstance(engine,MidiPlayer) and isinstance(engine.output,BassSynth))

def drum_pattern(song, end):
    """Extract the last complete bar containing drums, retain its MIDI setup."""
    from .smf import MidiSong, MidiEvent
    from .lyrics import Lyrics
    if song.division & 0x8000:return None
    tick=song.seconds_tick(end)
    sig=next((s for s in reversed(song.signatures) if s[0]<=tick), (0,4,4))
    length=song.division*4*sig[1]/sig[2]
    boundary=sig[0]+int((tick-sig[0])/length)*length
    for offset in range(4):
        right=boundary-offset*length;left=right-length
        if left<0:break
        a,b=song.tick_seconds(left),song.tick_seconds(right)
        events=[e for e in song.events if a<=e.at<b and e.data[0]&15==9]
        if not any(e.data[0]==0x99 and e.data[2] for e in events):continue
        setup={}
        for e in song.events:
            if e.at>=a:break
            if e.data[0] in (0xb9,0xc9):setup[(e.data[0],e.data[1] if e.data[0]==0xb9 else 0)]=e.data
        rows=[MidiEvent(0,data) for data in setup.values()]+[MidiEvent(e.at-a,e.data) for e in events]
        bpm=60000000/next((x[2] for x in reversed(song.tempo_map) if x[1]<=a),500000)
        return MidiSong(rows,b-a+.001,Lyrics(),initial_bpm=bpm), b-a
    return None

def build(native,settings,path,key,speed,melody,pattern,full_song=False,fill=False):
    from .bass import BassSynth
    from .playback import MidiPlayer
    from .pcm_player import PcmPlayer
    from .library import MIDI_EXT
    engine=rhythm=None
    try:
        if path.suffix.lower() in MIDI_EXT:
            engine=MidiPlayer(output=BassSynth(native,settings=settings));engine.load(path)
            engine.set_channel(3,muted=melody)
        else:engine=PcmPlayer(native);engine.load(path)
        engine.set_key(key);engine.set_speed(speed/100);engine.set_volume(0)
        if full_song:
            from .medley_full import can_play_fill, drum_fill, source_bounds
            engine.medley_bounds = source_bounds(engine, path)
            if fill and isinstance(engine, MidiPlayer):
                song = drum_fill(engine.song, engine.medley_bounds, engine.speed)
                if song and can_play_fill(engine, settings, engine.medley_bounds.first_note):
                    try:
                        rhythm = MidiPlayer(output=BassSynth(native, settings=settings))
                        rhythm.song = song
                        rhythm.duration = song.duration
                        rhythm.times = [event.at for event in song.events]
                        rhythm.seek(0)
                    except (OSError, ValueError):
                        if rhythm:
                            rhythm.close()
                        rhythm = None
        if pattern and isinstance(engine,MidiPlayer):
            rhythm=MidiPlayer(output=BassSynth(native,settings=settings))
            rhythm.song,rhythm.duration=pattern[0],pattern[0].duration
            rhythm.times=[e.at for e in rhythm.song.events];rhythm.seek(0)
            rhythm.set_loop(0,pattern[1]);rhythm.set_volume(0)
        return engine,rhythm
    except BaseException:
        if engine:engine.close()
        if rhythm:rhythm.close()
        raise

def preparation_key(app,item,path):
    stat=path.stat()
    return (item.song_id,item.key,item.speed,str(path),stat.st_mtime_ns,
            json.dumps(app.settings,sort_keys=True),id(app.engine),stat.st_size,
            bool(app.melody_var.get()),session(item))

class Decks:
    def __init__(self):
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='medley-preload')
        self.future=None;self.key=None;self.tail=None;self.rhythm=None;self.elapsed=0.;self.stamp=0.;self.error='';self.rhythm_target=None;self.drum_was_muted=False
        self.item = None
    def discard(self):
        future,self.future=self.future,None;self.key=None;self.item=None
        if future and not future.cancel():
            def dispose(done):
                try:
                    for engine in done.result():
                        if engine:engine.close()
                except BaseException:pass
            future.add_done_callback(dispose)
    def prepare(self,app,opts):
        full_song = opts.get('full_song', False)
        if not opts['enabled'] or (not full_song and not supported(app.engine)) or not app.song_queue.items:
            self.discard();return
        item=app.song_queue.items[0];row=app.library.get(item.song_id)
        if not row:self.discard();return
        path=Path(row['path'])
        from .library import MIDI_EXT
        from .pcm_player import available
        native = app.home / 'native' / 'x64'
        if path.suffix.lower() not in MIDI_EXT|{'.wav','.mp3'}:
            self.discard();return
        if path.suffix.lower() in MIDI_EXT and app.settings.get('synth_backend')!='bass':
            self.discard();return
        if full_song and path.suffix.lower() in ('.wav', '.mp3') and not available(native):
            self.discard();return
        try:key=preparation_key(app,item,path)
        except OSError:self.discard();return
        if key==self.key and item is self.item:
            if self.future and self.future.done() and not getattr(self,'reported',False):
                from .transition_report import record
                record(app,'preload_ready' if self.ready() else 'preload_failed',song_id=item.song_id,
                    error=str(self.future.exception()) if not self.future.cancelled() and self.future.exception() else '')
                self.reported=True
            return
        from .transition_report import record
        record(app,'preload_requested',song_id=item.song_id)
        self.discard();self.key=key;self.item=item;self.error='';self.reported=False
        pattern=None
        if opts.get('crossfade') and opts.get('keep_rhythm') and getattr(app.engine,'song',None):
            pattern=drum_pattern(app.engine.song,app._medley_state['trigger'])
        same_session = session(item) and session(item) == session(getattr(app, 'current_item', None))
        self.future=self.pool.submit(
            build, native, deepcopy(app.settings), path, item.key, item.speed,
            app.melody_var.get(), pattern, bool(session(item)), bool(same_session))
    def ready(self):
        return self.future is not None and self.future.done() and not self.future.cancelled() and self.future.exception() is None
    def matches(self,item,app=None):
        if not self.ready() or (item.song_id,item.key,item.speed)!=self.key[:3]:return False
        if self.item is not None and item is not self.item:
            return False
        if app is not None:
            try:
                row=app.library.get(item.song_id)
                valid=bool(row) and self.key==preparation_key(app,item,Path(row['path']))
            except (OSError,ValueError,TypeError,KeyError):valid=False
            if not valid:self.discard();return False
        return True
    def take(self,item,app=None):
        if not self.matches(item,app):return None
        result=self.future.result();self.future=None;self.key=None;self.item=None
        return result
    def attach(self,old,rhythm,app,fade):
        self.stop_tail()
        self.tail=old;self.rhythm=rhythm;self.elapsed=0.;self.stamp=time.monotonic();self.fade=max(.01,fade)
        if rhythm:
            from .medley import bpm_at
            bpm=bpm_at(app.engine)
            if bpm:rhythm.set_speed(bpm/rhythm.song.initial_bpm)
            self.rhythm_target=app.engine;self.drum_was_muted=9 in app.engine.muted
            old.set_channel(9,muted=True);app.engine.set_channel(9,muted=True)
            rhythm.play();rhythm.enable_scheduler()
    def update(self,app,now):
        active=app.engine
        if active is None:self.stop_tail();return
        dt=max(0,now-self.stamp);self.stamp=now
        base=1. if getattr(app,'system_volume',None) is not None else app.volume_var.get()/100
        for player in (self.tail,self.rhythm):
            if player:
                if not active.playing and player.playing:player.pause()
                elif active.playing and not player.playing and not player.ended:player.play()
                player.pump()
        if not active.playing:return
        self.elapsed+=dt
        if self.rhythm:
            from .medley import bpm_at
            bpm=bpm_at(active)
            if bpm:
                speed=max(.5,min(1.5,bpm/self.rhythm.song.initial_bpm))
                if abs(speed-self.rhythm.speed)>.0001:self.rhythm.set_speed(speed)
            self.rhythm.set_volume(base)
        if self.tail:
            ratio=min(1,self.elapsed/self.fade)
            self.tail.set_volume(base*math.sqrt(1-ratio));active.set_volume(base*math.sqrt(ratio))
            if ratio>=1:self.tail.close();self.tail=None
    def stop_tail(self):
        if self.rhythm_target:
            try:self.rhythm_target.set_channel(9,muted=self.drum_was_muted)
            except OSError:pass
            self.rhythm_target=None
        for name in ('tail','rhythm'):
            engine=getattr(self,name);setattr(self,name,None)
            if engine:engine.close()
    def close(self):
        self.discard();self.stop_tail();self.pool.shutdown(wait=False,cancel_futures=True)

def cleanup(app):
    from .medley import cancel_random_fill
    cancel_random_fill(app)
    decks=app.__dict__.pop('_medley_decks',None)
    if decks:decks.close()


def advance_prepared(app):
    """Promote a ready next occurrence at end/mark-out without an overlap."""
    decks=app.__dict__.get('_medley_decks')
    item=app.song_queue.items[0] if app.song_queue.items else None
    if decks and item and decks.matches(item,app):app._medley_prepared=True
    try:app.next_song()
    finally:app.__dict__.pop('_medley_prepared',None)
