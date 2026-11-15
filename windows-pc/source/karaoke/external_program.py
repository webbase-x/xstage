"""Launch an installed tool without leaking the frozen player's DLL paths."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import threading

_launch_lock = threading.RLock()


def environment(directory, inherited=None):
    env = dict(os.environ if inherited is None else inherited)
    for key in list(env):
        if key.upper().startswith(('QT_', 'QML')):
            env.pop(key)
    bundle = getattr(sys, '_MEIPASS', None)
    if bundle:
        root = os.path.normcase(os.path.abspath(bundle))
        for key in list(env):
            if key.upper() == 'PATH':
                env[key] = os.pathsep.join(
                    item for item in env[key].split(os.pathsep)
                    if item and not (os.path.normcase(os.path.abspath(item)) == root
                        or os.path.normcase(os.path.abspath(item)).startswith(root + os.sep)))
    plugins = Path(directory) / 'qt'
    if (plugins / 'platforms' / 'qwindows.dll').is_file():
        env['QT_PLUGIN_PATH'] = str(plugins)
        env['QT_QPA_PLATFORM_PLUGIN_PATH'] = str(plugins / 'platforms')
    return env


def launch(arguments, directory, hidden=False):
    directory = Path(directory).resolve()
    env = environment(directory)
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if hidden else 0
    with _launch_lock:
        kernel = None
        previous = None
        if sys.platform == 'win32' and getattr(sys, 'frozen', False):
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.GetDllDirectoryW.argtypes = [ctypes.c_uint, ctypes.c_wchar_p]
            kernel.GetDllDirectoryW.restype = ctypes.c_uint
            kernel.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
            kernel.SetDllDirectoryW.restype = ctypes.c_int
            length = kernel.GetDllDirectoryW(0, None)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                if not kernel.GetDllDirectoryW(len(buffer), buffer):
                    raise ctypes.WinError(ctypes.get_last_error())
                previous = buffer.value
            if not kernel.SetDllDirectoryW(None):
                raise ctypes.WinError(ctypes.get_last_error())
        try:
            return subprocess.Popen([str(item) for item in arguments], cwd=str(directory),
                                    env=env, creationflags=flags)
        finally:
            if kernel is not None and not kernel.SetDllDirectoryW(previous):
                raise ctypes.WinError(ctypes.get_last_error())
