"""Bounded event diagnostics; timings are software timings, not measured audio."""
from collections import deque
from datetime import datetime
import json
import logging
import platform
import time

def record(app,event,**details):
    rows=app.__dict__.setdefault('_transition_events',deque(maxlen=200))
    row=dict(event=event,time=datetime.now().isoformat(timespec='milliseconds'),monotonic=time.monotonic(),**details)
    rows.append(row)
    logging.info('Playback transition: %s',row)

def snapshot(app):
    from . import __version__
    engine=getattr(app,'engine',None)
    return dict(version=__version__,platform=platform.platform(),
        timing_note='Software events only; not an acoustic or sample-accurate gap measurement.',
        medley=getattr(app,'settings',{}).get('medley',{}),
        backend=getattr(app,'settings',{}).get('synth_backend','windows'),
        engine=type(engine).__name__ if engine else None,
        queue_count=len(app.song_queue.items),
        events=list(app.__dict__.get('_transition_events',[])))

def export_report(app):
    from tkinter import filedialog
    from pathlib import Path
    target=filedialog.asksaveasfilename(parent=app,title='บันทึกรายงานการต่อเพลง',
        initialfile='XStage-transition-report.json',defaultextension='.json',filetypes=[('JSON','*.json')])
    if not target:return
    try:
        Path(target).write_text(json.dumps(snapshot(app),ensure_ascii=False,indent=2),encoding='utf-8')
        app.status_var.set('บันทึกรายงานการต่อเพลงแล้ว')
    except OSError as error:app.show_error(error)
