"""Source-channel selection. Does not remove centered vocals from a stereo mix."""
import ctypes as C
import tkinter as tk
from tkinter import ttk
from .dialog_layout import DialogWindow

class ChannelInfo(C.Structure):
    _fields_=[('freq',C.c_uint32),('chans',C.c_uint32),('flags',C.c_uint32),('ctype',C.c_uint32),('origres',C.c_uint32),('plugin',C.c_uint32),('sample',C.c_uint32),('filename',C.c_void_p)]

def route_samples(samples,mode):
    if mode=='left':samples[:,1]=samples[:,0]
    elif mode=='right':samples[:,0]=samples[:,1]
    elif mode!='stereo':raise ValueError('ช่องเสียงไม่ถูกต้อง')

class StereoRouter:
    def __init__(self,dll,stream):
        self.dll,self.stream=dll,stream;self.mode='stereo';self.handle=0
        dll.BASS_ChannelGetInfo.argtypes=[C.c_uint32,C.POINTER(ChannelInfo)];dll.BASS_ChannelGetInfo.restype=C.c_int
        info=ChannelInfo()
        if not dll.BASS_ChannelGetInfo(stream,C.byref(info)) or info.chans!=2 or not info.flags&0x100:raise OSError('การเลือกช่องเสียงต้องเป็นสตรีโอผ่าน BASS FX')
        callback=getattr(C,'WINFUNCTYPE',C.CFUNCTYPE)(None,C.c_uint32,C.c_uint32,C.c_void_p,C.c_uint32,C.c_void_p)
        import numpy as np
        def process(handle,channel,buffer,length,user):
            if self.mode!='stereo' and length%8==0:
                samples=np.ctypeslib.as_array((C.c_float*(length//4)).from_address(buffer)).reshape(-1,2)
                route_samples(samples,self.mode)
        self.callback=callback(process)
        dll.BASS_ChannelSetDSP.argtypes=[C.c_uint32,callback,C.c_void_p,C.c_int];dll.BASS_ChannelSetDSP.restype=C.c_uint32
        dll.BASS_ChannelRemoveDSP.argtypes=[C.c_uint32,C.c_uint32];dll.BASS_ChannelRemoveDSP.restype=C.c_int
        self.handle=dll.BASS_ChannelSetDSP(stream,self.callback,None,100)
        if not self.handle:raise OSError('เปิดตัวเลือกช่องเสียงไม่ได้')
    def set(self,mode):
        if mode not in ('stereo','left','right'):raise ValueError('ช่องเสียงไม่ถูกต้อง')
        self.mode=mode
    def close(self):
        if self.handle:self.dll.BASS_ChannelRemoveDSP(self.stream,self.handle);self.handle=0

def audio_window(app):
    engine=app.engine;win=DialogWindow(app);win.title('ช่องเสียงร้อง / แทร็กเสียง');win.geometry('560x390')
    mode=tk.StringVar(value=getattr(engine,'audio_mode','stereo'));status=tk.StringVar(value='สำหรับไฟล์ที่แยกเสียงร้องกับดนตรีไว้คนละช่องหรือแทร็ก')
    ttk.Label(win.content,text='เลือกช่องเสียงต้นฉบับ',font=('Tahoma',15,'bold')).pack(anchor='w',padx=16,pady=12)
    def apply():
        if engine is not app.engine or engine is None:status.set('เพลงเปลี่ยนแล้ว กรุณาเปิดหน้าต่างใหม่');return
        try:
            if not hasattr(engine,'set_audio_mode'):raise ValueError('เพลงนี้ยังไม่รองรับเลือกช่องเสียง • WAV/MP3 ต้องใช้ BASS FX')
            engine.set_audio_mode(mode.get());status.set('ใช้ช่องเสียงที่เลือกแล้ว')
        except (OSError,ValueError) as error:mode.set(getattr(engine,'audio_mode','stereo'));app.show_error(error)
    for label,value in [('สเตอริโอเดิม','stereo'),('ใช้เสียงต้นฉบับช่องซ้าย','left'),('ใช้เสียงต้นฉบับช่องขวา','right')]:ttk.Radiobutton(win.content,text=label,value=value,variable=mode,command=apply).pack(anchor='w',padx=16,pady=6)
    track=tk.IntVar(value=1);row=ttk.Frame(win.content);row.pack(fill='x',padx=16,pady=12)
    ttk.Label(row,text='แทร็กเสียง').pack(side='left');ttk.Spinbox(row,from_=1,to=32,textvariable=track,width=5).pack(side='left',padx=8)
    def select_track():
        try:
            if engine is not app.engine or not hasattr(engine,'set_audio_track'):raise ValueError('รองรับเฉพาะวิดีโอที่ codec ของ Windows เปิดให้เลือกแทร็ก')
            engine.set_audio_track(track.get());status.set('เลือกแทร็ก '+str(track.get())+' แล้ว')
        except (OSError,ValueError,tk.TclError) as error:app.show_error(error)
    ttk.Button(row,text='ใช้แทร็ก',command=select_track).pack(side='left')
    ttk.Label(win.content,textvariable=status,wraplength=470).pack(padx=16,pady=12)
    return win
