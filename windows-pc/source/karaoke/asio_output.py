"""Opt-in BASSASIO stereo output host for the native PCM callback.

Only float32 stereo devices at 48 kHz are supported. The caller owns the
producer and must stop it before closing this host. Never run Python in ASIOPROC.
"""
import ctypes
import os
from pathlib import Path

from .asio_native_bridge import NativePcmBridge

UINT = ctypes.c_uint32
BOOL = ctypes.c_int
PTR = ctypes.c_void_p
BASS_ASIO_FORMAT_FLOAT = 19


class AsioOutput:
    def __init__(self, native, *, device, channel=0, rate=48000,
                 capacity_frames=48000, bindings=None, bridge_factory=NativePcmBridge):
        if type(device) is not int or device < 0:
            raise ValueError('ASIO device ID ไม่ถูกต้อง')
        if type(channel) is not int or channel < 0 or channel % 2:
            raise ValueError('ASIO output ต้องเริ่มจากช่องเลขคู่')
        if rate != 48000:
            raise ValueError('ASIO bridge รองรับ 48000 Hz เท่านั้น')
        if bindings is None:
            if os.name != 'nt':
                raise OSError('ASIO output รองรับ Windows เท่านั้น')
            path = Path(native) / 'bassasio.dll'
            if not path.is_file():
                raise OSError('ไม่พบ bassasio.dll')
            dll = ctypes.WinDLL(str(path))
        else:
            dll = bindings
        signatures = {
            'BASS_ASIO_Init': ([UINT, UINT], BOOL),
            'BASS_ASIO_Free': ([], BOOL),
            'BASS_ASIO_ChannelEnable': ([BOOL, UINT, PTR, PTR], BOOL),
            'BASS_ASIO_ChannelJoin': ([BOOL, UINT, UINT], BOOL),
            'BASS_ASIO_ChannelSetFormat': ([BOOL, UINT, UINT], BOOL),
            'BASS_ASIO_ChannelSetRate': ([BOOL, UINT, ctypes.c_double], BOOL),
            'BASS_ASIO_Start': ([UINT, UINT], BOOL),
            'BASS_ASIO_Stop': ([], BOOL),
            'BASS_ASIO_ErrorGetCode': ([], ctypes.c_int),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(dll, name)
            fn.argtypes, fn.restype = args, result
        self.dll = dll
        self.bridge = None
        self.started = False
        self.initialized = False
        try:
            self._check(dll.BASS_ASIO_Init(device, 0), 'เปิด ASIO')
            self.initialized = True
            self.bridge = bridge_factory(native, capacity_frames)
            # Interleaved stereo buffer is returned by the native callback on
            # the first output channel; joined second channel shares its data.
            self._check(dll.BASS_ASIO_ChannelEnable(0, channel,
                PTR(self.bridge.callback_address()), PTR(self.bridge.handle)), 'เปิด ASIO channel')
            self._check(dll.BASS_ASIO_ChannelJoin(0, channel + 1, channel), 'จับคู่ Stereo')
            self._check(dll.BASS_ASIO_ChannelSetFormat(0, channel, BASS_ASIO_FORMAT_FLOAT), 'กำหนด Float32')
            self._check(dll.BASS_ASIO_ChannelSetRate(0, channel, float(rate)), 'กำหนด Sample Rate')
            self._check(dll.BASS_ASIO_Start(0, 0), 'เริ่ม ASIO')
            self.started = True
        except BaseException:
            try:
                self.close()
            except Exception:
                pass
            raise

    def _check(self, value, action):
        if not value:
            raise OSError(f'{action} ไม่สำเร็จ (ASIO {self.dll.BASS_ASIO_ErrorGetCode()})')

    def push(self, pcm):
        if not self.started:
            raise OSError('ASIO output ยังไม่เริ่มทำงาน')
        return self.bridge.push(pcm)

    def close(self):
        # Never destroy callback user-data while the driver might still call it.
        # A failed BASS_ASIO_Free must be visible, not silently treated as
        # success: the caller can retry closure before releasing this bridge.
        if self.initialized:
            try:
                self.dll.BASS_ASIO_Stop()
            finally:
                self._check(self.dll.BASS_ASIO_Free(), 'ปิด ASIO driver')
                self.initialized = False
                self.started = False
        if self.bridge is not None:
            self.bridge.close()
            self.bridge = None
