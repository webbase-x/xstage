"""SoundCard 0.4.6 import ownership and per-calling-thread COM lifetime."""
from contextlib import contextmanager
import importlib
import sys
import threading

_import_lock=threading.Lock()

def load_soundcard():
    # 0.4.6 treats CoInitializeEx's S_FALSE (1) as an error on first import.
    # Import on a fresh thread before our caller initializes COM. Release the
    # library's import-time reference on that same thread, then own references
    # explicitly per audio_context. No HRESULT failures are suppressed.
    with _import_lock:
        if 'soundcard' in sys.modules:return sys.modules['soundcard']
        result=[];errors=[]
        def bootstrap():
            try:
                module=importlib.import_module('soundcard')
                backend=sys.modules.get('soundcard.mediafoundation')
                owner=getattr(backend,'_com',None)
                if owner is not None and getattr(owner,'com_loaded',False):
                    backend._ole32.CoUninitialize()
                    owner.com_loaded=False
                result.append(module)
            except Exception as error:errors.append(error)
        thread=threading.Thread(target=bootstrap,name='soundcard-first-import',daemon=True)
        thread.start();thread.join()
        if errors:raise errors[0]
        return result[0]

@contextmanager
def com_context(ole=None):
    if ole is None:
        import ctypes as C
        # WinDLL leaves HRESULT interpretation to us; OleDLL would raise before
        # we can handle an existing STA apartment (RPC_E_CHANGED_MODE).
        ole=C.WinDLL('ole32')
        ole.CoInitializeEx.argtypes=[C.c_void_p,C.c_uint32];ole.CoInitializeEx.restype=C.c_int32
        ole.CoUninitialize.argtypes=[];ole.CoUninitialize.restype=None
    hr=int(ole.CoInitializeEx(None,0)) & 0xffffffff
    owned=hr in (0,1)
    if not owned and hr!=0x80010106:raise OSError(f'เริ่มระบบเสียง COM ไม่สำเร็จ (HRESULT 0x{hr:08X})')
    try:yield
    finally:
        if owned:ole.CoUninitialize()

@contextmanager
def audio_context():
    if sys.platform!='win32':raise OSError('ระบบรับเสียงนี้รองรับ Windows')
    sc=load_soundcard()
    with com_context():yield sc
