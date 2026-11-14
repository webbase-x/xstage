"""Reference-count BASS devices owned by X-Stage, never adopt foreign owners."""
import threading

_lock = threading.RLock()
_devices = {}

def acquire(dll, decode=False):
    handle = getattr(dll, '_handle', None)
    key = (handle if isinstance(handle, int) else id(dll), bool(decode))
    with _lock:
        if key in _devices:
            device, count = _devices[key]
            if not dll.BASS_SetDevice(device):
                raise OSError('เลือกอุปกรณ์ BASS ที่ใช้งานร่วมกันไม่ได้')
            _devices[key] = (device, count+1)
        else:
            if not dll.BASS_Init(0 if decode else -1,48000,0,None,None):
                raise OSError(f'เปิดอุปกรณ์เสียงไม่สำเร็จ (BASS {dll.BASS_ErrorGetCode()})')
            device = dll.BASS_GetDevice()
            _devices[key] = (device, 1)
    return key, device

def release(dll, key):
    with _lock:
        entry = _devices.get(key)
        if entry is None:return
        device, count = entry
        if count > 1:_devices[key] = (device, count-1)
        else:
            dll.BASS_SetDevice(device)
            dll.BASS_Free()
            del _devices[key]
