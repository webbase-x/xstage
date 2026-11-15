"""Three-band parametric output EQ for a BASS stream, not external MIDI."""
import ctypes as C
import math

class Parameters(C.Structure):
    _fields_=[('center',C.c_float),('bandwidth',C.c_float),('gain',C.c_float)]

class Equalizer:
    frequencies=(100,1000,8000)
    def __init__(self,dll,stream):
        self.dll,self.stream=dll,stream;self.handles=[];self.gains=[0.,0.,0.]
        for name,args,result in [('BASS_ChannelSetFX',[C.c_uint32,C.c_uint32,C.c_int],C.c_uint32),
                                  ('BASS_FXSetParameters',[C.c_uint32,C.c_void_p],C.c_int),
                                  ('BASS_ChannelRemoveFX',[C.c_uint32,C.c_uint32],C.c_int),
                                  ('BASS_ChannelGetAttribute',[C.c_uint32,C.c_uint32,C.POINTER(C.c_float)],C.c_int)]:
            f=getattr(dll,name);f.argtypes=args;f.restype=result
        rate=C.c_float()
        if not dll.BASS_ChannelGetAttribute(stream,1,C.byref(rate)) or rate.value<240:raise OSError('อ่านความถี่เสียงสำหรับ EQ ไม่ได้')
        self.frequencies=tuple(min(f,rate.value/3) for f in self.frequencies)
        try:
            for frequency in self.frequencies:
                handle=dll.BASS_ChannelSetFX(stream,7,0)
                if not handle:raise OSError('เปิด EQ ไม่ได้')
                self.handles.append(handle)
            self.set([0,0,0])
        except Exception:self.close();raise
    def set(self,gains):
        values=[float(x) for x in gains]
        if len(values)!=3 or any(not math.isfinite(x) or not -12<=x<=12 for x in values):raise ValueError('EQ ต้องเป็น 3 ค่า ระหว่าง -12 ถึง +12 dB')
        try:
            self._write(values)
        except OSError:
            try:self._write(self.gains)
            except OSError:self.close()
            raise
        self.gains=values
    def _write(self,values):
        for handle,freq,gain in zip(self.handles,self.frequencies,values):
            param=Parameters(freq,12,gain)
            if not self.dll.BASS_FXSetParameters(handle,C.byref(param)):raise OSError('ตั้งค่า EQ ไม่สำเร็จ')
    def close(self):
        for handle in self.handles:self.dll.BASS_ChannelRemoveFX(self.stream,handle)
        self.handles.clear()

def output_for(engine):
    from .playback import MidiPlayer
    output=engine.output if isinstance(engine,MidiPlayer) else engine
    return output if output is not None and hasattr(output,'dll') and getattr(output,'stream',0) else None

def apply(engine,gains):
    output=output_for(engine)
    if output is None:raise ValueError('EQ ใช้กับ SoundFont หรือ WAV/MP3 ผ่าน BASS FX')
    eq=getattr(output,'_equalizer',None)
    if eq is None or not eq.handles:output._equalizer=eq=Equalizer(output.dll,output.stream)
    eq.set(gains)
