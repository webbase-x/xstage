"""Windows default playback endpoint volume. All calls stay on the Tk thread.

Microsoft interfaces: IMMDeviceEnumerator, IMMDevice, IAudioEndpointVolume.
Reacquire the endpoint each operation to follow Windows default-device changes.
"""
import ctypes as C
import math
import sys
import uuid
from contextlib import contextmanager

HRESULT = C.c_int32
DWORD = C.c_uint32
BOOL = C.c_int32

class GUID(C.Structure):
    _fields_ = [('data1', DWORD), ('data2', C.c_uint16), ('data3', C.c_uint16), ('data4', C.c_ubyte * 8)]
    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)

CLSID_ENUM = GUID.parse('bcde0395-e52f-467c-8e3d-c4579291692e')
IID_ENUM = GUID.parse('a95664d2-9614-4f35-a746-de8db63617e6')
IID_VOLUME = GUID.parse('5cdf2c82-841e-4546-9722-0cf74078229a')


def checked(hr):
    if C.c_int32(hr).value < 0:
        raise OSError(f'Windows audio HRESULT 0x{hr & 0xffffffff:08X}')


def invoke(pointer, index, argtypes=(), args=(), result=HRESULT):
    table = C.cast(pointer, C.POINTER(C.POINTER(C.c_void_p))).contents
    method = C.WINFUNCTYPE(result, C.c_void_p, *argtypes)(table[index])
    return method(pointer, *args)


class WindowsVolume:
    def __init__(self):
        if sys.platform != 'win32':
            raise OSError('Windows Core Audio is required')
        self.ole = C.WinDLL('ole32')
        self.ole.CoInitializeEx.argtypes = [C.c_void_p, DWORD]
        self.ole.CoInitializeEx.restype = HRESULT
        self.ole.CoUninitialize.argtypes = []
        self.ole.CoUninitialize.restype = None
        self.ole.CoCreateInstance.argtypes = [C.POINTER(GUID), C.c_void_p, DWORD, C.POINTER(GUID), C.POINTER(C.c_void_p)]
        self.ole.CoCreateInstance.restype = HRESULT
        hr = self.ole.CoInitializeEx(None, 2)
        self.owns_com = hr in (0, 1)
        if (hr & 0xffffffff) != 0x80010106:  # already initialized with another apartment model
            checked(hr)
        self.closed = False

    @contextmanager
    def endpoint(self):
        if self.closed:
            raise OSError('Windows volume controller closed')
        enum, device, volume = C.c_void_p(), C.c_void_p(), C.c_void_p()
        try:
            checked(self.ole.CoCreateInstance(C.byref(CLSID_ENUM), None, 23, C.byref(IID_ENUM), C.byref(enum)))
            checked(invoke(enum, 4, (C.c_int, C.c_int, C.POINTER(C.c_void_p)), (0, 0, C.byref(device))))
            checked(invoke(device, 3, (C.POINTER(GUID), DWORD, C.c_void_p, C.POINTER(C.c_void_p)),
                           (C.byref(IID_VOLUME), 23, None, C.byref(volume))))
            yield volume
        finally:
            for pointer in (volume, device, enum):
                if pointer.value:
                    invoke(pointer, 2, result=DWORD)

    @staticmethod
    def _read(volume):
        level, muted = C.c_float(), BOOL()
        checked(invoke(volume, 9, (C.POINTER(C.c_float),), (C.byref(level),)))
        checked(invoke(volume, 15, (C.POINTER(BOOL),), (C.byref(muted),)))
        return max(0, min(100, float(level.value)*100)), bool(muted.value)

    def read(self):
        with self.endpoint() as volume:
            return self._read(volume)

    def write(self, percent):
        value = float(percent)
        if not math.isfinite(value):
            raise ValueError('Volume must be finite')
        value = max(0, min(100, value))
        with self.endpoint() as volume:
            checked(invoke(volume, 7, (C.c_float, C.c_void_p), (value / 100, None)))
            checked(invoke(volume, 14, (BOOL, C.c_void_p), (int(value == 0), None)))
            return self._read(volume)

    def close(self):
        if not self.closed:
            self.closed = True
            if self.owns_com:
                self.ole.CoUninitialize()
