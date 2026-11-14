"""Suppress transient Windows consoles for background executable helpers.

Only intended for non-interactive helpers such as ffmpeg and ffprobe.
Installer, build and explicit user-launched diagnostic scripts retain their
normal console so errors remain readable. The caller must handle/log stderr.
"""
from __future__ import annotations

import subprocess
import sys


def silent_subprocess_options():
    """Return Windows-only Popen/run options without hiding diagnostic output.

    On a Windows GUI executable without an attached console, a child console
    binary creates a new visible window unless CREATE_NO_WINDOW is specified.
    SHOWWINDOW/SW_HIDE adds an extra guard for programs honoring STARTUPINFO.
    """
    if sys.platform != 'win32':
        return {}
    options = {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)}
    startup_class = getattr(subprocess, 'STARTUPINFO', None)
    if startup_class is not None:
        startup = startup_class()
        startup.dwFlags |= getattr(subprocess, 'STARTF_USESHOWWINDOW', 0x0001)
        startup.wShowWindow = getattr(subprocess, 'SW_HIDE', 0)
        options['startupinfo'] = startup
    return options
