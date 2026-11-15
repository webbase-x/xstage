"""Native BASS FX 2.4 eight-band processor. Explicit per-stream scope."""
import ctypes as C
import copy
import os
from .eq_model import validate,KINDS,flat
from .equalizer import output_for

class Biquad(C.Structure):
    _fields_=[('kind',C.c_int),('frequency',C.c_float),('gain',C.c_float),('bandwidth',C.c_float),('q',C.c_float),('slope',C.c_float),('channel',C.c_int)]
class Volume(C.Structure):
    _fields_=[('channel',C.c_int),('volume',C.c_float)]

class Processor:
    def __init__(self,output,graphic=False):
        self.dll=output.dll;self.stream=output.stream;self.handles=[];self.state=flat()
        if graphic:
            from .graphic_eq import flat as graphic_flat
            self.state=graphic_flat()
        self.count=len(self.state['bands'])
        if not hasattr(output,'fx'):
            from .branding import asset
            from .bass import BassSynth
            path=asset('x').parent.parent/'native'/'x64'/'bass_fx.dll'
            BassSynth.validate_dll(path)
            if os.name!='nt':raise OSError('EQ native ต้องทดสอบบน Windows')
            self.fx=C.WinDLL(str(path))
        else:self.fx=output.fx
        for name,args,result in [('BASS_ChannelSetFX',[C.c_uint32,C.c_uint32,C.c_int],C.c_uint32),('BASS_FXSetParameters',[C.c_uint32,C.c_void_p],C.c_int),('BASS_ChannelRemoveFX',[C.c_uint32,C.c_uint32],C.c_int),('BASS_ChannelGetAttribute',[C.c_uint32,C.c_uint32,C.POINTER(C.c_float)],C.c_int)]:
            fn=getattr(self.dll,name);fn.argtypes=args;fn.restype=result
        rate=C.c_float()
        if not self.dll.BASS_ChannelGetAttribute(self.stream,1,C.byref(rate)) or rate.value<100:raise OSError('อ่าน Sample Rate ไม่สำเร็จ')
        self.rate=rate.value
        try:
            for kind,priority in [(0x10003,100)]+[(0x10013,90-i) for i in range(self.count)]+[(0x10003,10)]:
                h=self.dll.BASS_ChannelSetFX(self.stream,kind,priority)
                if not h:raise OSError('เปิด EQ ไม่สำเร็จ • ตรวจ bass_fx.dll ด้วย Setup-Audio.ps1')
                self.handles.append(h)
            self._write(self.state)
        except Exception:self.close();raise
    def _param(self,h,p):
        if not self.dll.BASS_FXSetParameters(h,C.byref(p)):raise OSError('ส่งค่า EQ ไม่สำเร็จ')
    def _write(self,state):
        bypass=state['bypass']
        self._param(self.handles[0],Volume(0,1 if bypass else 10**(state['preamp_db']/20)))
        for h,b in zip(self.handles[1:-1],state['bands']):
            shelf=b['kind'] in ('low_shelf','high_shelf')
            self._param(h,Biquad(KINDS[b['kind']],min(b['frequency'],self.rate*.49),b['gain_db'],b.get('bandwidth',0),0 if shelf else b['q'],b['slope'] if shelf else 0,0 if bypass or not b['enabled'] or b['frequency']>=self.rate/2 else -1))
        self._param(self.handles[-1],Volume(0,1 if bypass else 10**(state['output_db']/20)))
    def set(self,state):
        if state.get('graphic')==31:
            from .graphic_eq import validate as graphic_validate
            state=graphic_validate(state)
        else:state=validate(state)
        try:self._write(state)
        except Exception:
            try:self._write(self.state)
            except Exception:self.close()
            raise
        self.state=copy.deepcopy(state)
    def close(self):
        for h in self.handles:self.dll.BASS_ChannelRemoveFX(self.stream,h)
        self.handles.clear()

def apply(engine,state):
    output=output_for(engine)
    if output is None:raise ValueError('เสียงนี้ไม่รองรับ EQ • ใช้ SoundFont หรือ WAV/MP3 ผ่าน BASS')
    processor=getattr(output,'_parametric_eq',None)
    if processor is None or not processor.handles or len(processor.state['bands'])!=len(state['bands']):
        replacement=Processor(output,graphic=state.get('graphic')==31)
        try:replacement.set(state)
        except Exception:replacement.close();raise
        if processor:processor.close()
        processor=replacement;output._parametric_eq=processor
    processor.set(state)
    legacy=getattr(output,'_equalizer',None)
    if legacy:legacy.close();output._equalizer=None
