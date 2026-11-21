"""Reference-count BASS devices owned by X-Stage, never adopt foreign owners."""
import threading

_lock = threading.RLock()
_devices = {}


def acquire(dll, decode=False, *, device_id=None):
    """Acquire one explicitly selected native device or the legacy default.

    A device selection is never silently redirected to another physical output.
    Offline decode always uses the BASS no-sound device (0).
    """
    if device_id is not None and (type(device_id) is not int or device_id < 0):
        raise ValueError('หมายเลขอุปกรณ์เสียงไม่ถูกต้อง')
    if decode and device_id not in (None, 0):
        raise ValueError('โหมดถอดรหัสต้องใช้อุปกรณ์เสียงจำลองเท่านั้น')
    requested = 0 if decode else (-1 if device_id is None else device_id)
    handle = getattr(dll, '_handle', None)
    identity = handle if isinstance(handle, int) else id(dll)
    key = (identity, bool(decode), requested)
    with _lock:
        if key in _devices:
            device, count = _devices[key]
            if not dll.BASS_SetDevice(device):
                raise OSError('เลือกอุปกรณ์ BASS ที่ใช้งานร่วมกันไม่ได้')
            _devices[key] = (device, count + 1)
        else:
            if not dll.BASS_Init(requested, 48000, 0, None, None):
                raise OSError(f'เปิดอุปกรณ์เสียงไม่สำเร็จ (BASS {dll.BASS_ErrorGetCode()})')
            device = dll.BASS_GetDevice()
            _devices[key] = (device, 1)
    return key, device


def release(dll, key):
    with _lock:
        entry = _devices.get(key)
        if entry is None:
            return
        device, count = entry
        if count > 1:
            _devices[key] = (device, count - 1)
        else:
            dll.BASS_SetDevice(device)
            dll.BASS_Free()
            del _devices[key]
