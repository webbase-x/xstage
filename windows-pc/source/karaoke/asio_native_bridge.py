"""Optional ctypes owner for the native SPSC ASIO PCM bridge.

The audio callback must call the exported native xstage_pcm_pop directly;
never use this Python wrapper from an audio callback.
"""
import ctypes
import os
from pathlib import Path

UINT = ctypes.c_uint32
PTR = ctypes.c_void_p
U64 = ctypes.c_uint64


class NativePcmBridge:
    def __init__(self, native, capacity_frames=48000, *, bindings=None):
        if type(capacity_frames) is not int or not 0 < capacity_frames <= 480000:
            raise ValueError('ความจุบัฟเฟอร์ PCM ไม่ถูกต้อง')
        if bindings is None:
            if os.name != 'nt':
                raise OSError('Native ASIO PCM bridge รองรับ Windows เท่านั้น')
            path = Path(native) / 'xstage_asio_pcm.dll'
            if not path.is_file():
                raise OSError('ไม่พบ xstage_asio_pcm.dll')
            dll = ctypes.WinDLL(str(path))
        else:
            dll = bindings
        signatures = {
            'xstage_pcm_create': ([UINT], PTR),
            'xstage_pcm_destroy': ([PTR], None),
            'xstage_pcm_push': ([PTR, PTR, UINT], UINT),
            'xstage_pcm_pop': ([PTR, PTR, UINT], UINT),
            'xstage_pcm_underruns': ([PTR], U64),
            'xstage_pcm_overruns': ([PTR], U64),
            'xstage_asio_callback': ([ctypes.c_int, UINT, PTR, UINT, PTR], UINT),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(dll, name)
            fn.argtypes, fn.restype = args, result
        handle = dll.xstage_pcm_create(capacity_frames)
        if not handle:
            raise OSError('สร้าง Native PCM bridge ไม่สำเร็จ')
        self.dll, self.handle = dll, handle

    def callback_address(self):
        if not self.handle:
            raise OSError('PCM bridge ถูกปิดแล้ว')
        return ctypes.cast(self.dll.xstage_asio_callback, PTR).value

    def push(self, pcm):
        if not self.handle:
            raise OSError('PCM bridge ถูกปิดแล้ว')
        data = bytes(pcm)
        if len(data) % 8:
            raise ValueError('ต้องเป็น stereo float32 interleaved')
        if not data:
            return 0
        buffer = ctypes.create_string_buffer(data)
        return self.dll.xstage_pcm_push(self.handle, ctypes.cast(buffer, PTR), len(data) // 8)

    def close(self):
        if self.handle:
            self.dll.xstage_pcm_destroy(self.handle)
            self.handle = None
