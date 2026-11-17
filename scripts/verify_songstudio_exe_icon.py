"""Verify native icon resources in built Windows executables (CI only)."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys


def verify(path):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    kernel.LoadLibraryExW.restype = wintypes.HMODULE
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMODULE,
                                      ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ssize_t)
    kernel.EnumResourceNamesW.argtypes = [wintypes.HMODULE, ctypes.c_void_p,
                                         callback_type, ctypes.c_ssize_t]
    kernel.EnumResourceNamesW.restype = wintypes.BOOL
    kernel.FreeLibrary.argtypes = [wintypes.HMODULE]
    handle = kernel.LoadLibraryExW(str(Path(path).resolve()), None, 2)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    found = []
    callback = callback_type(lambda module, kind, name, param: found.append(name) or True)
    try:
        # RT_GROUP_ICON = 14. The launcher previously had no icon resources.
        kernel.EnumResourceNamesW(handle, 14, callback, 0)
        if not found:
            raise RuntimeError(f"Executable has no embedded icon: {path}")
    finally:
        kernel.FreeLibrary(handle)
    print(f"PASS: embedded Windows icon: {path}")


if __name__ == "__main__":
    for executable in sys.argv[1:]:
        verify(executable)
