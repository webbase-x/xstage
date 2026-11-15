"""WinMM short-message input. Driver callback only enqueues bounded data."""
import ctypes as C
import os
import queue

class MidiInput:
    @staticmethod
    def devices():
        if os.name != 'nt':return []
        from ctypes import wintypes as W
        class Caps(C.Structure):
            _fields_=[('mid',W.WORD),('pid',W.WORD),('version',W.DWORD),('name',W.WCHAR*32),('support',W.DWORD)]
        dll=C.WinDLL('winmm');dll.midiInGetDevCapsW.argtypes=[C.c_size_t,C.POINTER(Caps),W.UINT]
        result=[]
        for i in range(dll.midiInGetNumDevs()):
            caps=Caps()
            if not dll.midiInGetDevCapsW(i,C.byref(caps),C.sizeof(caps)):result.append((i,caps.name))
        return result
    def __init__(self,device):
        if os.name!='nt':raise OSError('MIDI input ใช้บน Windows')
        self.events=queue.Queue(2048);self.overflow=False;self.handle=C.c_void_p()
        self.dll=C.WinDLL('winmm')
        callback=C.WINFUNCTYPE(None,C.c_void_p,C.c_uint,C.c_size_t,C.c_size_t,C.c_size_t)
        def receive(handle,message,instance,data,stamp):
            if message==0x3c3:
                try:self.events.put_nowait(data & 0xffffff)
                except queue.Full:self.overflow=True
        self.callback=callback(receive)
        self.dll.midiInOpen.argtypes=[C.POINTER(C.c_void_p),C.c_uint,callback,C.c_size_t,C.c_uint]
        for name in ('midiInStart','midiInStop','midiInReset','midiInClose'):
            getattr(self.dll,name).argtypes=[C.c_void_p]
        code=self.dll.midiInOpen(C.byref(self.handle),device,self.callback,0,0x30000)
        if code:raise OSError(f'เปิด MIDI input ไม่ได้ ({code})')
        code=self.dll.midiInStart(self.handle)
        if code:self.close();raise OSError(f'เริ่ม MIDI input ไม่ได้ ({code})')
    def drain(self,voice):
        if self.overflow:
            self.overflow=False;voice.release()
            while not self.events.empty():self.events.get_nowait()
            return
        for _ in range(2048):
            try:packed=self.events.get_nowait()
            except queue.Empty:break
            status=packed&255;note=(packed>>8)&127;value=(packed>>16)&127
            source=('midi',status&15);kind=status&0xf0
            if kind==0x90 and value:voice.press(note,value,source)
            elif kind in (0x80,0x90):voice.off(note,source)
            elif kind==0xb0 and note in (120,123):
                voice.release_source(source)
                if voice.output:voice.output.send(bytes([0xb0,64,0]))
            elif kind==0xb0 and note==64:
                voice.ensure();voice.output.send(bytes([0xb0,64,value]))
            elif kind==0xe0:
                voice.ensure();voice.output.send(bytes([0xe0,note,value]))
    def close(self):
        if self.handle.value:
            self.dll.midiInStop(self.handle);self.dll.midiInReset(self.handle)
            self.dll.midiInClose(self.handle);self.handle=C.c_void_p()
