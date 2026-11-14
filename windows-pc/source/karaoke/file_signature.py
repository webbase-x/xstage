"""Change stamps without reading media bodies; Windows uses FILE_BASIC_INFO."""
import os
from functools import lru_cache

@lru_cache(maxsize=1)
def windows_api():
    import ctypes
    from ctypes import wintypes
    class BasicInfo(ctypes.Structure):
        _fields_=[('CreationTime',ctypes.c_longlong),('LastAccessTime',ctypes.c_longlong),
                  ('LastWriteTime',ctypes.c_longlong),('ChangeTime',ctypes.c_longlong),
                  ('FileAttributes',wintypes.DWORD)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    create=kernel.CreateFileW
    create.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,
                     wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    create.restype=wintypes.HANDLE
    query=kernel.GetFileInformationByHandleEx
    query.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD];query.restype=wintypes.BOOL
    close=kernel.CloseHandle;close.argtypes=[wintypes.HANDLE];close.restype=wintypes.BOOL
    return ctypes,BasicInfo,create,query,close


def change_time(path,stat):
    if os.name!='nt':return stat.st_ctime_ns
    ctypes,BasicInfo,create,query,close=windows_api()
    handle=create(str(path),0x80,7,None,3,0,None)  # read attributes, share read/write/delete
    if handle==ctypes.c_void_p(-1).value:return None
    try:
        data=BasicInfo()
        if not query(handle,0,ctypes.byref(data),ctypes.sizeof(data)):return None
        return data.ChangeTime or None
    finally:close(handle)
