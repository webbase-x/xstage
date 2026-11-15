"""Optional BASS FX playback for WAV/MP3 with independent pitch and tempo."""
import ctypes as C
import math
import os
from pathlib import Path
from .bass import BassSynth

U=C.c_uint32;Q=C.c_uint64;F=C.c_float;P=C.c_void_p;B=C.c_int

_FLOAT_DECODE_FILE = 0x80000000 | 0x200000 | 0x100
_PRESCAN = 0x20000
_POSITION_SCAN = 0x40000000
_QWORD_ERROR = 0xffffffffffffffff
_MAX_SCAN_FILE_BYTES = 32 * 1024 * 1024
_MAX_REGION_BYTES = 8 * 1024 * 1024

def available(native=None):
    if native is None:
        from .branding import asset
        native=asset('x').parent.parent/'native'/'x64'
    return os.name=='nt' and all((Path(native)/name).is_file() for name in ('bass.dll','bass_fx.dll'))

def bounded(value,low,high):
    value=float(value)
    if not math.isfinite(value):raise ValueError('ค่าระบบเสียงไม่ถูกต้อง')
    return max(low,min(high,value))

class PcmPlayer:
    supports_pitch=True
    def __init__(self,native,bindings=None):
        self.stream=0;self.source=0;self.initialized=False;self.directory=None
        self.playing=False;self.ended=False;self.speed=1.;self.key=0;self.duration=0.;self.volume=1.
        if bindings is not None:self.dll,self.fx=bindings
        else:
            native=Path(native).resolve()
            for name in ('bass.dll','bass_fx.dll'):BassSynth.validate_dll(native/name)
            self.directory=os.add_dll_directory(str(native))
            try:self.dll=C.WinDLL(str(native/'bass.dll'));self.fx=C.WinDLL(str(native/'bass_fx.dll'))
            except Exception:self.directory.close();raise
        signatures={
          'BASS_Init':([B,U,U,P,P],B),'BASS_Free':([],B),'BASS_ErrorGetCode':([],B),
          'BASS_GetDevice':([],U),'BASS_SetDevice':([U],B),'BASS_SetConfig':([U,U],B),
          'BASS_StreamCreateFile':([B,P,Q,Q,U],U),'BASS_StreamFree':([U],B),
          'BASS_ChannelPlay':([U,B],B),'BASS_ChannelPause':([U],B),'BASS_ChannelStop':([U],B),
          'BASS_ChannelIsActive':([U],U),'BASS_ChannelSetAttribute':([U,U,F],B),
          'BASS_ChannelGetPosition':([U,U],Q),'BASS_ChannelGetLength':([U,U],Q),
          'BASS_ChannelBytes2Seconds':([U,Q],C.c_double),'BASS_ChannelSeconds2Bytes':([U,C.c_double],Q),
          'BASS_ChannelSetPosition':([U,Q,U],B)}
        for name,(args,result) in signatures.items():
            fn=getattr(self.dll,name);fn.argtypes=args;fn.restype=result
        self.fx.BASS_FX_TempoCreate.argtypes=[U,U];self.fx.BASS_FX_TempoCreate.restype=U
        try:
            from .audio_device import acquire
            self._device_key,self.device=acquire(self.dll)
            self.initialized=True;self.device=self.dll.BASS_GetDevice()
            self.check(self.dll.BASS_SetConfig(0,500),'เตรียมบัฟเฟอร์')
            self.check(self.dll.BASS_SetConfig(1,10),'ตั้งรอบเติมเสียง')
        except Exception:self.close();raise
    def check(self,result,label):
        if not result:raise OSError(f'{label} ไม่สำเร็จ (BASS {self.dll.BASS_ErrorGetCode()})')
        return result
    def load(self,path,*unused):
        if self.stream or self.source:raise ValueError('ต้องเปิดเครื่องเล่นใหม่สำหรับเพลงใหม่')
        path = Path(path)
        name=C.create_unicode_buffer(str(path.resolve()))
        self.source=self.check(self.dll.BASS_StreamCreateFile(False,C.cast(name,P),0,0,_FLOAT_DECODE_FILE),'อ่านไฟล์เสียง')
        self.stream=self.check(self.fx.BASS_FX_TempoCreate(self.source,0x10000|0x100),'สร้างระบบคีย์และความเร็ว')
        # FREESOURCE transfers source ownership to the tempo stream.
        self._tempo_source = self.source
        self._mp3 = path.suffix.lower() == '.mp3'
        self.source=0
        length=self.dll.BASS_ChannelGetLength(self.stream,0)
        if length==0xffffffffffffffff:raise OSError('อ่านความยาวเพลงไม่ได้')
        self.duration=self.dll.BASS_ChannelBytes2Seconds(self.stream,length)
    @property
    def position(self):
        if not self.stream:return 0.
        value=self.dll.BASS_ChannelGetPosition(self.stream,0)
        if value==0xffffffffffffffff:raise OSError('อ่านตำแหน่งเพลงไม่ได้')
        return self.dll.BASS_ChannelBytes2Seconds(self.stream,value)
    def play(self):
        self.check(self.dll.BASS_ChannelPlay(self.stream,False),'เล่นเพลง');self.playing=True;self.ended=False
    def pause(self):
        self.check(self.dll.BASS_ChannelPause(self.stream),'พักเพลง');self.playing=False
    def stop(self):
        if self.stream:
            self.check(self.dll.BASS_ChannelStop(self.stream),'หยุดเพลง');self.seek(0)
        self.playing=False;self.ended=False
    def seek(self,seconds):
        value=self.dll.BASS_ChannelSeconds2Bytes(self.stream,bounded(seconds,0,self.duration))
        self.check(self.dll.BASS_ChannelSetPosition(self.stream,value,0),'เลื่อนตำแหน่ง');self.ended=False

    def seek_medley_start(self, seconds):
        """Seek before playback, scanning only up to the MP3 entry point."""
        if self.playing:
            raise ValueError('ตั้งจุดเริ่มเพลงเมดเลย์ก่อนเล่น')
        if self._mp3 and seconds > 0:
            target = self.dll.BASS_ChannelSeconds2Bytes(self._tempo_source, seconds)
            if (target == _QWORD_ERROR or
                    not self.dll.BASS_ChannelSetPosition(self._tempo_source, target, _POSITION_SCAN) or
                    self.dll.BASS_ChannelGetPosition(self._tempo_source, 0) != target):
                seconds = 0.
        self.seek(seconds)
        return seconds

    def sample_regions(self, path, window, *, scan_tail=True):
        """Read edge samples with an independent stream on the no-sound device."""
        from .audio_device import acquire, release

        path = Path(path)
        mp3 = path.suffix.lower() == '.mp3'
        if mp3 and scan_tail and path.stat().st_size > _MAX_SCAN_FILE_BYTES:
            scan_tail = False
        flags = _FLOAT_DECODE_FILE | (_PRESCAN if mp3 and scan_tail else 0)
        dll = self.dll
        get_data = dll.BASS_ChannelGetData
        get_data.argtypes = [U, P, U]
        get_data.restype = U
        previous_device = dll.BASS_GetDevice()
        device_key, _ = acquire(dll, decode=True)
        stream = 0
        try:
            name = C.create_unicode_buffer(str(path.resolve()))
            stream = dll.BASS_StreamCreateFile(False, C.cast(name, P), 0, 0, flags)
            if not stream:
                return None, None
            length = dll.BASS_ChannelGetLength(stream, 0)
            if length == _QWORD_ERROR:
                return None, None
            window_bytes = dll.BASS_ChannelSeconds2Bytes(stream, window)
            if not 0 < window_bytes <= _MAX_REGION_BYTES:
                return None, None

            def region(start, end):
                size = end - start
                if not size or (start and not dll.BASS_ChannelSetPosition(stream, start, 0)):
                    return None
                if dll.BASS_ChannelGetPosition(stream, 0) != start:
                    return None
                data = C.create_string_buffer(size)
                if get_data(stream, data, size) != size:
                    return None
                return (dll.BASS_ChannelBytes2Seconds(stream, start),
                        dll.BASS_ChannelBytes2Seconds(stream, end), data.raw)

            head = region(0, min(length, window_bytes))
            tail = ((head if length <= window_bytes else region(length-window_bytes, length))
                    if scan_tail else None)
            return head, tail
        finally:
            if stream:
                dll.BASS_StreamFree(stream)
            release(dll, device_key)
            if previous_device != 0xffffffff:
                dll.BASS_SetDevice(previous_device)

    def set_speed(self,value):
        value=bounded(value,.5,1.5)
        self.check(self.dll.BASS_ChannelSetAttribute(self.stream,0x10000,(value-1)*100),'ปรับความเร็ว');self.speed=value
    def set_key(self,value):
        value=int(bounded(value,-12,12))
        self.check(self.dll.BASS_ChannelSetAttribute(self.stream,0x10001,value),'ปรับคีย์');self.key=value
    def set_audio_mode(self,mode):
        from .media_routing import StereoRouter
        if not hasattr(self,'router'):self.router=StereoRouter(self.dll,self.stream)
        self.router.set(mode);self.audio_mode=mode
    def set_volume(self,value):
        value=bounded(value,0,1)
        self.check(self.dll.BASS_ChannelSetAttribute(self.stream,2,value),'ปรับเสียง');self.volume=value
    def pump(self):
        if self.playing and self.dll.BASS_ChannelIsActive(self.stream)==0:self.playing=False;self.ended=True
    def close(self):
        if hasattr(self,'router'):self.router.close()
        if self.stream:self.dll.BASS_StreamFree(self.stream);self.stream=0
        elif self.source:self.dll.BASS_StreamFree(self.source);self.source=0
        if self.initialized:
            from .audio_device import release
            release(self.dll,self._device_key);self.initialized=False
        if self.directory:self.directory.close();self.directory=None
        self.playing=False
