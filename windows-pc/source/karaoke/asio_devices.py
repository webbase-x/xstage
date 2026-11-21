"""Read-only ASIO driver discovery via official BASSASIO 2.4 ABI.

Discovery does not initialize ASIO, change the default output, or promise that
a device is usable. ASIO PCM callbacks and output bridging are separate work.
"""
import ctypes
import os
from dataclasses import dataclass
from pathlib import Path

UINT = ctypes.c_uint32
BOOL = ctypes.c_int


class BASS_ASIO_DEVICEINFO(ctypes.Structure):
    _fields_ = [('name', ctypes.c_char_p), ('driver', ctypes.c_char_p)]


@dataclass(frozen=True)
class AsioDevice:
    index: int
    name: str
    driver: str


def discover_asio(native, *, bindings=None):
    """Enumerate installed ASIO drivers; return [] if addon is unavailable.

    A present but incompatible addon is an error rather than an implicit
    fallback. Driver names use the Windows active ANSI codepage.
    """
    if bindings is None:
        if os.name != 'nt':
            return []
        path = Path(native) / 'bassasio.dll'
        if not path.is_file():
            return []
        from .bass import BassSynth
        BassSynth.validate_dll(path)
        dll = ctypes.WinDLL(str(path))
    else:
        dll = bindings
    get_version = dll.BASS_ASIO_GetVersion
    get_version.argtypes = []
    get_version.restype = UINT
    version = get_version()
    if version >> 16 != 0x204:
        raise OSError('bassasio.dll ต้องเป็น BASSASIO 2.4')
    get_info = dll.BASS_ASIO_GetDeviceInfo
    get_info.argtypes = [UINT, ctypes.POINTER(BASS_ASIO_DEVICEINFO)]
    get_info.restype = BOOL
    devices = []
    for index in range(256):
        info = BASS_ASIO_DEVICEINFO()
        if not get_info(index, ctypes.byref(info)):
            break
        devices.append(AsioDevice(
            index,
            (info.name or b'').decode('mbcs' if os.name == 'nt' else 'utf-8', errors='replace'),
            (info.driver or b'').decode('mbcs' if os.name == 'nt' else 'utf-8', errors='replace'),
        ))
    return devices
