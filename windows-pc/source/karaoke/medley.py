"""Queued MIDI/audio transitions, preloading, sequential fades and crossfades."""
import bisect
import logging
import math
import time
import tkinter as tk
from tkinter import ttk
from .dialog_layout import DialogWindow, ActionBar
from .medley_full import next_item, session, source_bounds, with_lyrics


FULL_SONG = {'enabled': True, 'full_song': True}


def base_volume(app):
    return 1.0 if getattr(app, 'system_volume', None) is not None else app.volume_var.get() / 100


def queue_uses_full_song(app):
    return bool(session(getattr(app, 'current_item', None)) or session(next_item(app)))

def options(settings):
    raw=settings.get('medley',{})
    if not isinstance(raw,dict):raise ValueError('การตั้งค่าเมดเล่ย์ไม่ถูกต้อง')
    bars=float(raw.get('bars',0));fade=float(raw.get('fade',1))
    if not math.isfinite(bars) or not bars.is_integer() or not 0<=bars<=32:raise ValueError('Mark Out ต้องเป็น 0–32 ห้อง')
    if not math.isfinite(fade) or not 0<=fade<=10:raise ValueError('Fade ต้องเป็น 0–10 วินาที')
    return dict(enabled=bool(raw.get('enabled',False)),bars=int(bars),fade=fade,keep_bpm=bool(raw.get('keep_bpm',False)),crossfade=bool(raw.get('crossfade',False)),keep_rhythm=bool(raw.get('keep_rhythm',False)))

def mark_out(song,bars):
    if not bars or song.division&0x8000:return song.duration
    end=song.seconds_tick(song.duration);starts=[]
    signatures=sorted(song.signatures)
    for index,(tick,num,den) in enumerate(signatures):
        stop=min(end,signatures[index+1][0] if index+1<len(signatures) else end)
        step=song.division*4*num/den
        if step<=0:raise ValueError('Time signature ไม่ถูกต้อง')
        count=max(0,math.ceil((stop-tick)/step))
        if count>100000:raise ValueError('เพลงยาวเกินขอบเขต Mark Out')
        starts.extend(tick+i*step for i in range(count))
    return song.tick_seconds(starts[max(0,len(starts)-bars)]) if starts else song.duration

def bpm_at(engine):
    song=getattr(engine,'song',None)
    if song is None:return None
    index=max(0,bisect.bisect_right([row[1] for row in song.tempo_map],engine.position)-1)
    return 60000000/song.tempo_map[index][2]*engine.speed

def begin(app):
    opts=options(app.settings)
    carry=app.__dict__.pop('_medley_carry',None)
    engine=app.engine
    full_song = bool(session(getattr(app, 'current_item', None)))
    if not full_song and opts['enabled'] and opts['keep_bpm'] and carry and getattr(engine,'song',None):
        requested=carry/engine.song.initial_bpm
        speed=max(.5,min(1.5,requested));engine.set_speed(speed);app.current_item.speed=round(speed*100);app.speed_var.set(app.current_item.speed)
    decks=app.__dict__.get('_medley_decks')
    if decks and decks.rhythm and decks.rhythm_target is engine:engine.set_channel(9,muted=True)
    song=getattr(engine,'song',None)
    trigger=mark_out(song,opts['bars']) if song and not full_song else engine.duration
    if trigger<=0:trigger=engine.duration  # Never skip a whole short song on entry.
    app._medley_state=dict(engine=engine,opts=opts,trigger=trigger,fired=False,elapsed=0.,stamp=time.monotonic(),last_position=0.,gain=None)
    path = getattr(engine, 'medley_tail_path', None)
    if full_song and path:
        from .medley_decks import Decks

        if decks is None:
            decks = app._medley_decks = Decks()
        app._medley_state['analysis'] = decks.pool.submit(source_bounds, engine, path)
        engine.medley_tail_path = None

def tick(app,now=None):
    if app.__dict__.get('_random_medley_fill'):
        update_random_fill(app)
        return
    decks=app.__dict__.get('_medley_decks')
    if decks:decks.update(app,time.monotonic() if now is None else now)
    state=app.__dict__.get('_medley_state');engine=app.engine
    if not state or engine is not state['engine']:return
    if queue_uses_full_song(app):
        tick_full_song(app, state, decks)
        return
    if not state['opts']['enabled']:return
    now=time.monotonic() if now is None else now;delta=max(0,now-state['stamp']);state['stamp']=now
    if not engine.playing:return
    position=engine.position
    if position<state['last_position']-.5:state['elapsed']=0.;state['fired']=False
    state['last_position']=position;state['elapsed']+=delta
    opts=state['opts'];fade=opts['fade'];waiting=bool(app.song_queue.items)
    from .medley_decks import Decks, supported
    if decks is None and supported(engine):decks=app._medley_decks=Decks()
    if decks:
        decks.prepare(app,opts)
        if decks.future and decks.future.done() and not decks.future.cancelled() and decks.future.exception() and not decks.error:
            decks.error=str(decks.future.exception())
            app.status_var.set('โหลดเพลงล่วงหน้าไม่สำเร็จ • ใช้การต่อคิวปกติ: '+decks.error)
    if opts.get('crossfade') and decks:
        trigger=state['trigger'] if opts['bars'] else max(0,engine.duration-fade*engine.speed)
        if waiting and decks.ready() and position>=trigger and not state['fired']:
            state['fired']=True
            from .performance_features import history_finish
            history_finish(app,'medley')
            app._medley_carry=bpm_at(engine) if opts['keep_bpm'] else None
            app._medley_overlap=True
            try:app.next_song()
            finally:app.__dict__.pop('_medley_overlap',None);app.__dict__.pop('_medley_carry',None)
            return
        if decks.tail:return

    base=base_volume(app)
    gain=min(1.,state['elapsed']/fade) if fade else 1.
    if waiting and fade and not (opts.get('crossfade') and decks and decks.ready()):gain=min(gain,max(0.,(state['trigger']-position)/max(.01,engine.speed)/fade))
    level=gain*base
    if state['gain'] is None or abs(level-state['gain'])>.015 or level in (0,base):
        if level!=state['gain']:engine.set_volume(level);state['gain']=level
    if waiting and position>=state['trigger'] and not state['fired']:
        state['fired']=True
        from .performance_features import history_finish
        history_finish(app,'medley')
        app._medley_carry=bpm_at(engine) if opts['keep_bpm'] else None
        from .medley_decks import advance_prepared
        try:advance_prepared(app)
        finally:app.__dict__.pop('_medley_carry',None)


def tick_full_song(app, state, decks):
    engine = app.engine
    if not engine.playing:
        return
    if next_item(app):
        from .medley_decks import Decks

        if decks is None:
            decks = app._medley_decks = Decks()
        decks.prepare(app, FULL_SONG)
    elif decks:
        decks.discard()

    if not session(getattr(app, 'current_item', None)):
        if state['opts']['enabled'] and state['gain'] != base_volume(app):
            state['gain'] = base_volume(app)
            engine.set_volume(state['gain'])
        return
    analysis = state.get('analysis')
    if analysis and analysis.done():
        state.pop('analysis')
        if not analysis.cancelled() and not analysis.exception():
            engine.medley_bounds = analysis.result()
    bounds = getattr(engine, 'medley_bounds', None)
    if bounds is None or getattr(engine, 'loop_end', None) is not None:
        return
    try:
        offset = app.offset_var.get()
    except tk.TclError:
        offset = 0
    lyrics = app.lyrics
    protection_key = (id(bounds), id(lyrics), offset)
    if state.get('protection_key') != protection_key:
        state['protection_key'] = protection_key
        state['protected_bounds'] = with_lyrics(bounds, lyrics, offset)
    end = state['protected_bounds'].end
    if end < engine.duration and engine.position >= end:
        engine.pause()
        from .transition_report import record

        record(app, 'medley_tail_trim', seconds=round(engine.duration - end, 3))
        app.on_song_ended()


def end_random_medley(app):
    """Start a preloaded fill only between songs in the same random set."""
    item = next_item(app)
    current_session = session(getattr(app, 'current_item', None))
    decks = app.__dict__.get('_medley_decks')
    if not current_session or current_session != session(item) or not decks or not decks.matches(item, app):
        return False
    target, player = decks.future.result()
    if player is None or player.scheduler_error:
        return False

    from pathlib import Path
    from .medley_full import drum_fill
    from .transition_report import record
    from .ui import playback_lyrics

    try:
        row = app.library.get(item.song_id)
        if not row:
            return False
        lyrics, offset = playback_lyrics(app.settings, Path(row['path']), target.song.lyrics, row['path'])
        bounds = with_lyrics(target.medley_bounds, lyrics, offset)
        fill = drum_fill(target.song, bounds, target.speed)
        if fill is None:
            return False
        player.song = fill
        player.duration = fill.duration
        player.times = [event.at for event in fill.events]
        player.seek(0)
        player.set_volume(.7 * base_volume(app))
        player.play()
        player.enable_scheduler()
    except (OSError, ValueError, RuntimeError):
        logging.warning('Medley fill bypassed', exc_info=True)
        if player.playing:
            player.pause()
        return False

    app._random_medley_fill = (item, player)
    app.status_var.set('กำลังลงจังหวะเข้าเพลงถัดไป')
    record(app, 'medley_fill_started', song_id=item.song_id, seconds=round(fill.duration, 3))
    return True


def advance_after_fill(app):
    if next_item(app):
        from .medley_decks import advance_prepared

        advance_prepared(app)
    else:
        app.on_song_ended()


def cancel_random_fill(app, advance=False):
    fill = app.__dict__.pop('_random_medley_fill', None)
    if fill is None:
        return
    _, player = fill
    try:
        if player.playing:
            player.pause()
    except OSError:
        logging.warning('Medley fill stopped after an audio error', exc_info=True)
    finally:
        if advance:
            advance_after_fill(app)


def update_random_fill(app):
    item, player = app._random_medley_fill
    decks = app.__dict__.get('_medley_decks')
    if player.ended or player.scheduler_error or next_item(app) is not item or not decks or not decks.matches(item, app):
        cancel_random_fill(app, advance=True)


def toggle_random_fill(app):
    fill = app.__dict__.get('_random_medley_fill')
    if fill is None:
        return False
    update_random_fill(app)
    if app.__dict__.get('_random_medley_fill') is not fill:
        return True
    _, player = fill
    if player.playing:
        player.pause()
        app.status_var.set('พักจังหวะเข้าเพลงถัดไป')
    else:
        player.play()
        app.status_var.set('กำลังลงจังหวะเข้าเพลงถัดไป')
    return True

def settings_window(app):
    opts=options(app.settings);win=DialogWindow(app);win.title('เมดเล่ย์ / ต่อเพลง');win.geometry('660x540')
    cross=tk.BooleanVar(value=opts['crossfade']);rhythm=tk.BooleanVar(value=opts['keep_rhythm'])
    enabled=tk.BooleanVar(value=opts['enabled']);bars=tk.IntVar(value=opts['bars']);fade=tk.DoubleVar(value=opts['fade']);keep=tk.BooleanVar(value=opts['keep_bpm'])
    ttk.Checkbutton(win.content,text='เปิดการต่อเพลงเมดเล่ย์',variable=enabled).pack(anchor='w',padx=18,pady=14)
    for label,var,start,stop in [('เริ่มเพลงถัดไปก่อนจบ (ห้อง MIDI)',bars,0,32),('Fade out / Fade in (วินาที)',fade,0,10)]:
        row=ttk.Frame(win.content);row.pack(fill='x',padx=18,pady=8);ttk.Label(row,text=label).pack(side='left');ttk.Spinbox(row,from_=start,to=stop,textvariable=var,width=6).pack(side='right')
    ttk.Radiobutton(win.content,text='ใช้ความเร็วของเพลงถัดไป',variable=keep,value=False).pack(anchor='w',padx=18,pady=8)
    ttk.Radiobutton(win.content,text='คง BPM จากเพลงก่อน (เฉพาะ MIDI)',variable=keep,value=True).pack(anchor='w',padx=18,pady=8)
    ttk.Checkbutton(win.content,text='ซ้อนเสียง Crossfade (SoundFont / WAV / MP3 ผ่าน BASS)',variable=cross).pack(anchor='w',padx=18,pady=8)
    ttk.Checkbutton(win.content,text='วนห้องกลองเดิมต่อในเพลง MIDI ถัดไป (ใช้ร่วมกับ Crossfade)',variable=rhythm).pack(anchor='w',padx=18,pady=8)
    ttk.Label(win.content,text='เปิดเมดเล่ย์แล้วจะโหลดคิวถัดไปล่วงหน้า แม้ไม่เลือก Crossfade • ถ้าโหลดไม่พร้อมหรือเป็นวิดีโอ/Windows MIDI จะต่อคิวตามปกติ • การวนกลองใช้หนึ่งห้องจากเพลงเดิม',wraplength=580).pack(fill='x',padx=18,pady=10)
    def save():
        try:
            value=options({'medley':dict(enabled=enabled.get(),bars=bars.get(),fade=fade.get(),keep_bpm=keep.get(),crossfade=cross.get(),keep_rhythm=rhythm.get())})
            from .medley_decks import cleanup
            cleanup(app)
            app.settings['medley']=value;app.save_settings()
            state=app.__dict__.pop('_medley_state',None)
            if app.engine:
                app.engine.set_volume(1 if getattr(app,'system_volume',None) is not None else app.volume_var.get()/100)
                begin(app);app._medley_state['elapsed']=value['fade']
            app.status_var.set('บันทึกเมดเล่ย์แล้ว');win.destroy()
        except (ValueError,OSError,tk.TclError) as error:app.show_error(error)
    from .transition_report import export_report
    actions=ActionBar(win.footer,padding=8);actions.pack(fill='x')
    ttk.Button(actions,text='รายงานการต่อเพลง…',command=lambda:export_report(app)).pack(side='left',padx=12,pady=12)
    ttk.Button(actions,text='บันทึก',command=save).pack(side='right',padx=12,pady=12)
    return win


def carry_at_end(app):
    if queue_uses_full_song(app):
        return
    opts=options(getattr(app,'settings',{}))
    if opts['enabled'] and opts['keep_bpm'] and getattr(app,'engine',None):app._medley_carry=bpm_at(app.engine)
