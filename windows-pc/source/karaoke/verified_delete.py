"""Windows-only deletion of the exact reviewed file handle; never recursive."""
import ctypes as c
import hashlib
import os
import ntpath
from pathlib import Path


def delete_verified(item):
    if os.name!='nt':raise OSError('การลบถาวรที่ตรวจไฟล์ด้วย handle รองรับเฉพาะ Windows')
    from ctypes import wintypes as w
    import msvcrt
    path=Path(item['path'])
    # Only NTFS is supported by the handle-bound, irreversible delete path.
    root=c.create_unicode_buffer(32768)
    k=c.WinDLL('kernel32',use_last_error=True)
    k.GetVolumePathNameW.argtypes=[w.LPCWSTR,w.LPWSTR,w.DWORD]
    k.GetVolumePathNameW.restype=w.BOOL
    if not k.GetVolumePathNameW(str(path),root,len(root)):
        raise c.WinError(c.get_last_error())
    fs=c.create_unicode_buffer(64)
    k.GetVolumeInformationW.argtypes=[w.LPCWSTR,w.LPWSTR,w.DWORD,c.c_void_p,c.c_void_p,c.c_void_p,w.LPWSTR,w.DWORD]
    k.GetVolumeInformationW.restype=w.BOOL
    if not k.GetVolumeInformationW(root.value,None,0,None,None,None,fs,len(fs)):
        raise c.WinError(c.get_last_error())
    if fs.value.upper()!='NTFS':
        raise ValueError('ลบถาวรอย่างปลอดภัยได้เฉพาะดิสก์ NTFS: '+fs.value)
    if ':' in ntpath.splitdrive(str(path))[1]:raise ValueError('ไม่อนุญาตลบ alternate data stream')
    if path.is_symlink() or any(p.is_symlink() or getattr(p,'is_junction',lambda:False)() for p in path.parents):raise ValueError('ไม่ลบผ่านไฟล์หรือโฟลเดอร์ลิงก์')
    kernel=c.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,c.c_void_p,w.DWORD,w.DWORD,w.HANDLE];kernel.CreateFileW.restype=w.HANDLE
    kernel.CloseHandle.argtypes=[w.HANDLE];kernel.CloseHandle.restype=w.BOOL
    kernel.SetFileInformationByHandle.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.DWORD];kernel.SetFileInformationByHandle.restype=w.BOOL
    # Share reads only: an existing writer/deleter or a player denying DELETE blocks the operation.
    handle=kernel.CreateFileW(str(path),0x80000000|0x10000,1,None,3,0x00200000|0x80,None)
    if handle==c.c_void_p(-1).value:raise c.WinError(c.get_last_error())
    owned=True
    try:
        class FileId(c.Structure):_fields_=[('volume',c.c_ulonglong),('identifier',c.c_ubyte*16)]
        kernel.GetFileInformationByHandleEx.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.DWORD];kernel.GetFileInformationByHandleEx.restype=w.BOOL
        info=FileId()
        if not kernel.GetFileInformationByHandleEx(handle,18,c.byref(info),c.sizeof(info)):raise c.WinError(c.get_last_error())
        if (info.volume,int.from_bytes(bytes(info.identifier),'little'))!=(item['device'],item['inode']):raise ValueError('รหัสไฟล์หรือไดรฟ์ไม่ตรงรายงาน')
        # Fail closed if the pathname was swapped to a reparse point, or if
        # the file has another hard-link name. Neither is a safe standalone
        # Song Bundle component for an irreversible deletion.
        class FileTime(c.Structure):
            _fields_=[('low',w.DWORD),('high',w.DWORD)]
        class ByHandleInformation(c.Structure):
            _fields_=[('attributes',w.DWORD),('created',FileTime),('accessed',FileTime),
                      ('written',FileTime),('volume',w.DWORD),('size_high',w.DWORD),
                      ('size_low',w.DWORD),('links',w.DWORD),('file_id_high',w.DWORD),('file_id_low',w.DWORD)]
        kernel.GetFileInformationByHandle.argtypes=[w.HANDLE,c.POINTER(ByHandleInformation)]
        kernel.GetFileInformationByHandle.restype=w.BOOL
        native=ByHandleInformation()
        if not kernel.GetFileInformationByHandle(handle,c.byref(native)):
            raise c.WinError(c.get_last_error())
        if native.attributes & 0x400:
            raise ValueError('ไม่ลบไฟล์ reparse point')
        if native.links != 1:
            raise ValueError('ไม่ลบไฟล์ที่มี hard link ร่วมกับไฟล์อื่น')
        fd=msvcrt.open_osfhandle(int(handle),os.O_RDONLY|os.O_BINARY);owned=False
        with os.fdopen(fd,'rb') as stream:
            stat=os.fstat(stream.fileno())
            if (stat.st_size,stat.st_mtime_ns,stat.st_ino,stat.st_dev)!=(item['size'],item['mtime'],item['inode'],item['device']):raise ValueError('ไฟล์ไม่ใช่ตัวที่ตรวจรายงานไว้')
            digest=hashlib.sha256()
            for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
            if digest.hexdigest()!=item['sha256']:raise ValueError('เนื้อหาไม่ตรง SHA256 ในรายงาน')
            # FILE_DISPOSITION_INFO contains a one-byte BOOLEAN. FileDispositionInfo = 4.
            disposition=c.c_ubyte(1)
            if not kernel.SetFileInformationByHandle(w.HANDLE(handle),4,c.byref(disposition),c.sizeof(disposition)):raise c.WinError(c.get_last_error())
            # The same verified handle owns deletion on close; the path is never reopened to delete.
    finally:
        if owned:kernel.CloseHandle(handle)
