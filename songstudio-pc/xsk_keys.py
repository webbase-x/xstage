"""Protect a per-install XSK encryption key under Windows DPAPI.

The key is bound to the current Windows user. It is never sent to Google Drive,
bundled in the executable, or exposed by the Song Studio REST API. Portable
playback requires a separate, future authorized-key distribution design.
"""
import ctypes
import os
import secrets
from ctypes import wintypes
from pathlib import Path


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data):
    backing = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    return DATA_BLOB(len(data), ctypes.cast(backing, ctypes.POINTER(ctypes.c_ubyte))), backing


def _dpapi(data, decrypt=False):
    if os.name != "nt":
        raise RuntimeError("กุญแจสำหรับ XSK รองรับ Windows DPAPI เท่านั้น")
    crypt = ctypes.windll.crypt32
    kernel = ctypes.windll.kernel32
    crypt.CryptProtectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB)]
    crypt.CryptProtectData.restype = wintypes.BOOL
    crypt.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB)]
    crypt.CryptUnprotectData.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    src, backing = _blob(data)
    result = DATA_BLOB()
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    args = ([ctypes.byref(src), None, None, None, None, 0,
             ctypes.byref(result)] if decrypt else
            [ctypes.byref(src), "X-Stage XSK", None, None, None,
             0x01, ctypes.byref(result)])
    if not fn(*args):
        raise OSError("Windows DPAPI ไม่สามารถจัดการกุญแจ XSK ได้")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel.LocalFree(result.pbData)


def get_key(data_dir):
    path = Path(data_dir) / "xsk-key.dpapi"
    if path.is_file():
        value = _dpapi(path.read_bytes(), decrypt=True)
        if len(value) != 32:
            raise ValueError("กุญแจ XSK เสียหาย")
        return value
    if path.exists():
        raise ValueError("กุญแจ XSK ไม่ใช่ไฟล์ปกติ")
    key = secrets.token_bytes(32)
    payload = _dpapi(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
    except FileExistsError:
        return get_key(data_dir)
    return key
