"""Local output checks. Loopback measures digital output, not acoustic latency."""
import importlib.util
import math
import os
import platform
import threading
import time
from pathlib import Path
from .windows_audio import audio_context

def readiness(home):
    from .bass import BassSynth
    result={'platform':platform.platform(),'python':platform.python_version(),'windows':os.name=='nt','native':{},'soundcard':importlib.util.find_spec('soundcard') is not None}
    for name in ('bass.dll','bassmidi.dll','bass_fx.dll'):
        path=Path(home)/'native'/'x64'/name
        try:BassSynth.validate_dll(path);result['native'][name]='พร้อมตรวจโหลด'
        except (OSError,ValueError) as error:result['native'][name]=str(error)
    return result

def analyze_output(frames,rate):
    import numpy as np
    raw=np.asarray(frames,dtype=float)
    if raw.ndim!=2 or not raw.shape[0]:raise ValueError('ไม่มีข้อมูลเสียงให้ตรวจ')
    invalid=int(np.count_nonzero(~np.isfinite(raw)));data=np.nan_to_num(raw,nan=0,posinf=0,neginf=0)
    mono=data.mean(axis=1);window=min(len(mono),rate//5)
    # Strongest 200-ms window avoids diluting a one-second test tone with silence.
    levels=[];ratios=[]
    for offset in range(0,len(mono)-window+1,max(1,window//2)):
        part=mono[offset:offset+window];spectrum=np.abs(np.fft.rfft(part*np.hanning(window)))**2
        hz=np.fft.rfftfreq(window,1/rate);band=spectrum[(hz>=865)&(hz<=895)].sum()
        ratios.append(float(band/max(1e-20,spectrum.sum())));levels.append(float(np.sqrt(np.mean(part**2))))
    tone=any(r>.65 and level>.0001 for r,level in zip(ratios,levels))
    return dict(seconds=len(data)/rate,peak=float(np.max(np.abs(data))),rms=float(np.sqrt(np.mean(data**2))),
                invalid_samples=invalid,clipped_samples=int(np.count_nonzero(np.abs(data)>=1)),
                test_tone_detected=bool(tone),measurement='Windows default-speaker digital loopback; not acoustic latency')

def probe_output():
    import numpy as np
    rate=48000;duration=3;errors=[];play_thread=None
    def play(speaker_id):
        try:
            with audio_context() as sc:
                speaker=sc.get_speaker(speaker_id)
                tone=np.sin(2*np.pi*880*np.arange(rate)/rate)*.08
                ramp=np.linspace(0,1,480);tone[:480]*=ramp;tone[-480:]*=ramp[::-1]
                time.sleep(.3);speaker.play(np.column_stack((tone,tone)),samplerate=rate)
        except Exception as error:errors.append(str(error))
    with audio_context() as sc:
        speaker=sc.default_speaker()
        if speaker is None:raise OSError('ไม่พบลำโพงเริ่มต้น')
        source=sc.get_microphone(speaker.id,include_loopback=True)
        if not source.isloopback:raise OSError('ไม่พบ loopback สำหรับลำโพง')
        try:
            with source.recorder(samplerate=rate,channels=2,blocksize=4800) as recorder:
                play_thread=threading.Thread(target=play,args=(speaker.id,),daemon=True,name='audio-probe-tone');play_thread.start()
                frames=recorder.record(numframes=rate*duration)
        except Exception as error:
            raise OSError('รับเสียง loopback จาก '+speaker.name+' ไม่สำเร็จ: '+str(error)) from error
        finally:
            if play_thread:play_thread.join(timeout=3)
        if play_thread.is_alive():raise OSError('ไดรเวอร์เล่นเสียงทดสอบไม่ยอมหยุด')
        if errors:raise OSError(errors[0])
        return dict(device=speaker.name,**analyze_output(frames,rate))
