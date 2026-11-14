"""Measure actual BASSMIDI float PCM rendering, without playing to speakers.

This measures synthesis throughput, not output-driver dropouts or sound quality.
"""
from __future__ import annotations
from array import array
from datetime import datetime, timezone
import math
import time
from .audio_auto import machine_specs
from .soundfont import normalize_audio

CANDIDATES = (
    dict(quality=2, voices=512, buffer_ms=100),
    dict(quality=1, voices=256, buffer_ms=150),
    dict(quality=0, voices=128, buffer_ms=200),
)
FRAMES = 480
BLOCK_SECONDS = FRAMES / 48000
GROUPS = 9
BLOCKS = 50


class Cancelled(Exception):
    pass


def choose(rows):
    # Ranked by interpolation quality, with substantial processing headroom.
    return next((dict(row['settings']) for row in rows if row['passed']), None)


def metrics(times, peak):
    ordered = sorted(times)
    mean = sum(times)/len(times)
    p95 = ordered[max(0, math.ceil(len(times)*.95)-1)]
    worst = max(times)
    audible = peak > 1e-7
    return dict(mean_ms=mean*1000, p95_ms=p95*1000, worst_ms=worst*1000,
                realtime_ratio=mean/BLOCK_SECONDS, peak=peak,
                passed=audible and mean <= .0035 and p95 <= .005 and worst <= .009,
                signal_detected=audible)


def run(native, options, cancel, progress=lambda value: None, *, factory=None,
        clock=time.perf_counter, groups=GROUPS, blocks=BLOCKS):
    if factory is None:
        from .bass import BassSynth
        factory = BassSynth
    options = normalize_audio({'soundfont_audio': options}, require_files=True)
    rows = []
    started = clock()
    report = dict(schema=1, created_at=datetime.now(timezone.utc).isoformat(),
                  kind='offline_actual_pcm', machine=machine_specs(),
                  fonts=options['fonts'], effects={k: options[k] for k in
                  ('effects_mode', 'reverb', 'chorus')},
                  limits=dict(mean_ms=3.5, p95_ms=5, worst_ms=9, block_ms=10),
                  output_driver_tested=False, rows=rows)
    def check():
        if cancel.is_set():
            raise Cancelled()
    total = len(CANDIDATES)*2*groups*blocks
    done = 0
    for candidate in CANDIDATES:
        check()
        settings = {**options, **candidate, 'quality_mode':'manual'}
        progress(dict(percent=done/total*100, text=f"โหลด SoundFont • คุณภาพ {candidate['quality']}"))
        synth = None
        load_start = clock()
        try:
            synth = factory(native, settings={'soundfont_audio':settings}, decode=True)
            load_seconds = clock()-load_start
            times, peak, cold_worst = [], 0.0, 0.0
            # First pass observes initial sample loading; second measures warmed
            # rendering. All 128 GM programs are requested over 9 groups.
            for repeat in range(2):
                for group in range(groups):
                    check()
                    event_start = clock()
                    synth.reset()
                    melodic = 0
                    for channel in range(16):
                        program = 0 if channel == 9 else (group*15+melodic)%128
                        if channel != 9:
                            melodic += 1
                        synth.send(bytes([0xc0|channel, program]))
                        synth.send(bytes([0xb0|channel, 7, 90]))
                        synth.send(bytes([0xb0|channel, 64, 127 if channel != 9 else 0]))
                        for note in range(8):
                            synth.send(bytes([0x90|channel, 36+note*4, 96]))
                    event_seconds = clock()-event_start
                    for block in range(blocks):
                        check()
                        t = clock()
                        pcm = synth.render(FRAMES)
                        elapsed = clock()-t + (event_seconds if block == 0 else 0)
                        if len(pcm) != FRAMES*2*4:
                            raise ValueError('ระบบเสียงคืนข้อมูล PCM ไม่ครบ')
                        samples = array('f')
                        samples.frombytes(pcm)
                        block_peak = max(abs(x) for x in samples)
                        if not all(math.isfinite(x) for x in samples):
                            raise ValueError('ข้อมูล PCM มีค่าผิดปกติ')
                        peak = max(peak, block_peak)
                        if repeat:
                            times.append(elapsed)
                        else:
                            cold_worst = max(cold_worst, elapsed)
                        done += 1
                        if block % 10 == 0 or done == total:
                            progress(dict(percent=done/total*100,
                                text=f"คุณภาพ {candidate['quality']} • รอบ {repeat+1}/2 • ชุดเครื่องดนตรี {group+1}/{groups}"))
            row = dict(settings=dict(candidate), **metrics(times, peak),
                       load_seconds=load_seconds, initial_worst_ms=cold_worst*1000)
            rows.append(row)
        finally:
            if synth is not None:
                synth.close()
    check()
    report.update(recommended=choose(rows), elapsed_seconds=clock()-started,
                  warning='ผลเรนเดอร์ PCM จริง ไม่ใช่การวัดไดรเวอร์ ลำโพง หรือทุกเพลง/ทุก bank')
    return report
