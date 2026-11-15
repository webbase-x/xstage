"""Stereo sample-peak LEDs from the Windows default output loopback."""
import math
import time
import threading
import tkinter as tk

class WindowsMix:
    """Bounded peak accumulator; captures default endpoint only, writes no audio files."""
    def __init__(self):
        self.stop_event=threading.Event();self.lock=threading.Lock();self.peaks=[0.,0.]
        self.target_id='';self.stamp=0.;self.name='';self.error='';self.thread=None
    def start(self):
        if self.thread and self.thread.is_alive():return
        self.stop_event.clear();self.error='';self.stamp=0.
        self.thread=threading.Thread(target=self.run,daemon=True,name='eq-windows-loopback');self.thread.start()
    def stop(self):self.stop_event.set()
    def feed(self,frames):
        import numpy as np
        data=np.asarray(frames)
        if data.ndim!=2 or data.shape[1]!=2 or not len(data) or not np.isfinite(data).all():raise ValueError('ข้อมูลระดับเสียงไม่ถูกต้อง')
        peaks=np.max(np.abs(data),axis=0)
        with self.lock:
            self.peaks=[max(self.peaks[i],float(peaks[i])) for i in range(2)];self.stamp=time.monotonic()
    def read(self):
        with self.lock:
            values=tuple(self.peaks) if time.monotonic()-self.stamp<.5 else None
            self.peaks=[0.,0.]
        return values
    def run(self):
        try:
            import os
            if os.name!='nt':raise OSError('มิเตอร์เสียงรวมรองรับ Windows')
            from .windows_audio import audio_context
            with audio_context() as sc:
                while not self.stop_event.is_set():
                    selected=self.target_id
                    speaker=sc.get_speaker(selected) if selected else sc.default_speaker()
                    if speaker is None:raise OSError('ไม่พบลำโพงเริ่มต้น Windows')
                    self.name=speaker.name
                    source=sc.get_microphone(id=speaker.id,include_loopback=True)
                    if not source.isloopback:raise OSError('อุปกรณ์ไม่รองรับ loopback')
                    with self.lock:self.peaks=[0.,0.];self.stamp=0.
                    with source.recorder(samplerate=48000,channels=2,blocksize=960) as recorder:
                        next_check=time.monotonic()+1
                        while not self.stop_event.is_set():
                            self.feed(recorder.record(numframes=960))
                            if time.monotonic()>=next_check:
                                current=sc.default_speaker();next_check=time.monotonic()+1
                                if selected!=self.target_id or (not selected and (current is None or current.id!=speaker.id)):break
        except Exception as error:
            self.error=str(error)
        finally:
            with self.lock:self.stamp=0.;self.peaks=[0.,0.]

def dbfs(value):return 20*math.log10(value) if value>0 else -math.inf

METER_VISIBLE_INTERVAL_MS = 80  # 12.5 Hz is ample for peak LEDs; not an RTA spectrum
METER_HIDDEN_INTERVAL_MS = 250  # Stop any off-screen animation work

class PeakMeter(tk.Canvas):
    def __init__(self,parent,app):
        super().__init__(parent,height=104,width=300,bg='#080d13',highlightthickness=1,highlightbackground='#344657')
        self.app=app;self.capture=WindowsMix();self.was_visible=False;self.timer=None;self.holds=[-math.inf]*2;self.until=[0.,0.];self.clips=[0.,0.];self.source=None
        self.bind('<Destroy>',self.cleanup,add='+');self.poll()
    def cleanup(self,event):
        if event.widget is self:
            self.capture.stop()
            if self.timer:self.after_cancel(self.timer);self.timer=None
    def poll(self):
        self.timer=None
        visible=bool(self.winfo_ismapped())
        if visible:
            if not self.was_visible or (self.capture.stop_event.is_set() and not (self.capture.thread and self.capture.thread.is_alive())):self.capture.start()
            if self.source!=self.capture.name:
                self.source=self.capture.name;self.holds=[-math.inf]*2;self.until=[0.,0.];self.clips=[0.,0.]
            self.render(self.capture.read())
        elif self.was_visible:
            self.capture.stop();self.holds=[-math.inf]*2;self.until=[0.,0.];self.clips=[0.,0.]
        self.was_visible=visible
        self.timer=self.after(METER_VISIBLE_INTERVAL_MS if visible else METER_HIDDEN_INTERVAL_MS,self.poll)
    def render(self,values):
        self.delete('all');w=max(280,self.winfo_width());left=28;right=w-90;step=(right-left)/30;now=time.monotonic()
        self.create_text(9,10,anchor='w',text='WINDOWS OUTPUT MIX • SAMPLE PEAK • dBFS',fill='#a7b7c4',font=('Tahoma',8))
        detail=self.capture.error or self.capture.name or 'กำลังเชื่อมต่อเสียงรวม Windows'
        self.create_text(9,25,anchor='w',text=detail[:75],fill='#a7b7c4',font=('Tahoma',8))
        for row,name in enumerate(('L','R')):
            db=dbfs(values[row]) if values is not None else -math.inf;y=44+row*21
            self.create_text(12,y+5,text=name,fill='#dce7ec',font=('Tahoma',9,'bold'))
            if db>=self.holds[row] or now>=self.until[row]:self.holds[row]=db;self.until[row]=now+1
            if db>=0:self.clips[row]=now+1
            for i in range(30):
                threshold=-60+2*(i+1);color='#45d489' if threshold<-12 else '#f2c94c' if threshold<-3 else '#f15b60'
                self.create_rectangle(left+i*step,y,left+(i+1)*step-2,y+10,fill=color if db>=threshold else '#1d2932',outline='')
            if self.holds[row]>-60 and values is not None:
                x=left+min(1,max(0,(self.holds[row]+60)/60))*(right-left)
                self.create_line(x,y-1,x,y+11,fill='#e8f2ff')
            text='—' if values is None else ('−∞' if db==-math.inf else f'{db:+.1f}')
            self.create_text(right+8,y+5,text=text,anchor='w',fill='#dce7ec',font=('Tahoma',9))
            self.create_text(w-22,y+5,text='CLIP',fill='#ff6268' if values is not None and now<self.clips[row] else '#39434c',font=('Tahoma',8,'bold'))
        for db in (-60,-36,-24,-12,0):self.create_text(left+(db+60)/60*(right-left),94,text=str(db),fill='#8796a7',font=('Tahoma',7))
        
