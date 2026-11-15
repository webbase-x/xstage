"""Bounded WASAPI microphone + default-speaker recording, with visible failures."""
import math
import queue
import threading
import time
import wave
from contextlib import contextmanager
from pathlib import Path

from .windows_audio import audio_context

def devices():
    with audio_context() as sc:
        return [(m.id,m.name) for m in sc.all_microphones(include_loopback=False)]

@contextmanager
def capture_source(kind,device,rate,block):
    with audio_context() as sc:
        if kind=='music':
            speaker=sc.default_speaker()
            if speaker is None:raise OSError('ไม่พบลำโพงเริ่มต้นของ Windows')
            source=sc.get_microphone(id=speaker.id,include_loopback=True)
            if not source.isloopback:raise OSError('ไม่พบช่องรับเสียงลำโพง')
        else:source=sc.get_microphone(id=device,include_loopback=False)
        # Request stereo to avoid the documented WASAPI single-channel issue.
        with source.recorder(samplerate=rate,channels=2,blocksize=block) as recorder:yield recorder

def mix_frames(mic,music,mic_gain=0.7,music_gain=0.7):
    import numpy as np
    if mic.shape!=music.shape or mic.ndim!=2 or mic.shape[1]!=2:raise ValueError('ข้อมูลเสียงสองแหล่งไม่ตรงกัน')
    if not all(math.isfinite(x) and 0<=x<=2 for x in (mic_gain,music_gain)):raise ValueError('ระดับเสียงไม่ถูกต้อง')
    mixed=np.nan_to_num(mic,nan=0,posinf=0,neginf=0)*mic_gain+np.nan_to_num(music,nan=0,posinf=0,neginf=0)*music_gain
    peak=float(np.max(np.abs(mixed))) if mixed.size else 0.
    clips=int(np.count_nonzero(np.abs(mixed)>1))
    return (np.clip(mixed,-1,1)*32767).astype('<i2').tobytes(),peak,clips

class MixedRecorder:
    def __init__(self,file,device,mic_gain=.7,music_gain=.7,source=capture_source):
        if not all(math.isfinite(x) and 0<=x<=2 for x in (mic_gain,music_gain)):raise ValueError('ระดับเสียงไม่ถูกต้อง')
        self.path=Path(file);self.device=device;self.gains=(mic_gain,music_gain);self.source=source
        self.rate=48000;self.block=4800;self.quit=threading.Event();self.ready=threading.Barrier(2)
        self.queues=[queue.Queue(maxsize=8),queue.Queue(maxsize=8)]
        self.error=None;self.thread=None;self.workers=[];self.frames=0;self.peak=0.;self.max_peak=0.;self.clipped=0
    @property
    def running(self):return bool(self.thread and self.thread.is_alive())
    def start(self):
        if self.thread:raise RuntimeError('เครื่องบันทึกนี้เริ่มทำงานแล้ว')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.thread=threading.Thread(target=self._run,daemon=True,name='mixed-wav-writer');self.thread.start()
    def _capture(self,index):
        try:
            with self.source(('mic','music')[index],self.device,self.rate,self.block) as rec:
                self.ready.wait(timeout=10)
                rec.record(numframes=None)  # Discard startup backlog before paired blocks.
                while not self.quit.is_set():
                    frames=rec.record(numframes=self.block)
                    if frames.shape!=(self.block,2):raise OSError('จำนวนเฟรมเสียงจากอุปกรณ์ไม่ครบ')
                    try:self.queues[index].put(frames,timeout=.5)
                    except queue.Full:raise OSError('บัฟเฟอร์บันทึกเสียงเต็ม หรืออุปกรณ์สองแหล่งเดินเวลาไม่ตรงกัน')
        except Exception as error:
            if not self.quit.is_set():self.error=error
            self.quit.set();self.ready.abort()
    def _run(self):
        try:
            with wave.open(str(self.path),'wb') as out:
                out.setnchannels(2);out.setsampwidth(2);out.setframerate(self.rate)
                for i in range(2):
                    worker=threading.Thread(target=self._capture,args=(i,),daemon=True,name='mixed-capture-'+str(i))
                    self.workers.append(worker);worker.start()
                last=time.monotonic();pending=[None,None]
                while True:
                    for i in range(2):
                        if pending[i] is None:
                            try:pending[i]=self.queues[i].get(timeout=.1)
                            except queue.Empty:pass
                    if all(x is not None for x in pending):
                        pcm,peak,clipped=mix_frames(*pending,*self.gains)
                        if self.frames*4+len(pcm)>0xffffff00:raise OSError('ถึงขนาดสูงสุดของ WAV กรุณาเริ่มไฟล์ใหม่')
                        out.writeframesraw(pcm);self.frames+=self.block;self.peak=peak;self.max_peak=max(self.max_peak,peak);self.clipped+=clipped
                        pending=[None,None];last=time.monotonic()
                    elif self.quit.is_set():break
                    elif time.monotonic()-last>12:raise OSError('ไม่ได้รับเสียงจากอุปกรณ์ภายในเวลาที่กำหนด')
        except Exception as error:self.error=error
        finally:
            self.quit.set();self.ready.abort()
            for worker in self.workers:worker.join(timeout=1)
            if any(w.is_alive() for w in self.workers):self.error=RuntimeError('ไดรเวอร์รับเสียงไม่ยอมหยุด กรุณาปิดโปรแกรมก่อนบันทึกใหม่')
    def stop(self):
        self.quit.set();self.ready.abort()
        if self.thread:self.thread.join(timeout=4)
        if self.running:self.error=RuntimeError('ยังปิดไฟล์เสียงไม่สำเร็จ กรุณารอ')
        return not self.running and not any(w.is_alive() for w in self.workers)
