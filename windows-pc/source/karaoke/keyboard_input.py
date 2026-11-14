"""Tk modifier state differs between Win32 and X11.

Win32 Mod1 (0x8) is Num Lock, not Alt. Keep lock and extended-key
flags out of shortcut filtering. Tk's Windows ALT_MASK is 0x20000.
"""
import sys


def control_or_alt(state, platform=None):
    platform = sys.platform if platform is None else platform
    alt = 0x20000 if platform == 'win32' else (0x10 if platform == 'darwin' else 0x8)
    return bool(int(state) & (0x4 | alt))


def editing_modifier(state, platform=None):
    return bool(int(state) & 0x1) or control_or_alt(state, platform)
