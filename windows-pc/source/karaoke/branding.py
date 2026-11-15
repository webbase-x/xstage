"""Fixed supplied artwork and compact song information shared by both screens."""
from pathlib import Path
import sys
import time


def asset(name):
    if getattr(sys, 'frozen', False):
        roots = [Path(sys.executable).resolve().parent]
        if getattr(sys, '_MEIPASS', None):
            roots.append(Path(sys._MEIPASS))
    else:
        roots = [Path(__file__).resolve().parents[1]]
    for root in roots:
        candidate = root / 'assets' / name
        if candidate.is_file():
            return candidate
    return roots[0] / 'assets' / name


def background_path(settings):
    # Legacy/custom paths are deliberately ignored. Only two supported modes.
    return asset('xstage-background.jpg') if settings.get('background_mode', 'stage') != 'none' else None


def wall_clock():
    return time.strftime('%H:%M:%S')


def song_details(song, duration=0, key_shift=0):
    if not song:
        return '', 'พิมพ์ค้นหาเพลง • คลิกขวาเปิดเมนู', ''
    song = dict(song)
    artist = song.get('artist') or 'ไม่ระบุศิลปิน'
    fields = []
    for label, value in [('ชนิด', song.get('format') or song.get('kind')),
                         ('คีย์', song.get('key_signature')), ('จังหวะ', song.get('rhythm'))]:
        if value:
            fields.append(f'{label} {value}')
    if key_shift:
        fields.append(f'ปรับคีย์ {key_shift:+d}')
    return song.get('title') or song.get('code') or 'ไม่ระบุชื่อเพลง', artist, '  ·  '.join(fields)


def install_window_icon(window):
    """Apply to the current window AND future dialogs, retaining Tk images."""
    import os
    import logging
    from PIL import Image, ImageTk
    from tkinter import TclError
    # Keep independent fallbacks: a failed bitmap must not undo a valid photo.
    if os.name == 'nt':
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('XStage.Karaoke')
        except (AttributeError, OSError):
            logging.exception('Cannot set application identity')
        try:
            icon = str(asset('xstage.ico'))
            window.iconbitmap(bitmap=icon, default=icon)
            return
        except (OSError, TclError):
            logging.exception('Cannot load Windows icon; using logo photo')
    try:
        with Image.open(asset('xstage-logo.jpg')) as source:
            logo = source.convert('RGBA')
        window._brand_icons = [ImageTk.PhotoImage(
            logo.resize((size, size), Image.Resampling.LANCZOS), master=window)
            for size in (16, 32, 48, 64, 128)]
        window.iconphoto(True, *window._brand_icons)
    except (OSError, TclError):
        logging.exception('Cannot set application logo')
