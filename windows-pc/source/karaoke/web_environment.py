"""Non-interactive prerequisites for the X-Stage Online one-click workflow.

The desktop settings (or existing SoundFont install) are the sole source of
rendering configuration. Never display file pickers, install executables from
unverified URLs, or silently change a user's saved audio profile.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .soundfont import normalize_audio, inspect_font
from .windows_process import silent_subprocess_options


def _existing_soundfont(home, data_dir):
    """Look only in well-known app-owned locations, not an entire user drive."""
    home, data_dir = Path(home), Path(data_dir)
    directories = (data_dir / 'SoundFonts', data_dir / 'soundfonts',
                   home / 'SoundFonts', home / 'soundfonts',
                   home / 'SoundFont', home / 'native' / 'soundfonts',
                   home.parent / 'SoundFonts')
    found = []
    for directory in directories:
        if not directory.is_dir():
            continue
        for file in sorted(directory.iterdir()):
            if file.is_file() and not file.is_symlink() and file.suffix.lower() == '.sf2':
                try:
                    inspect_font(file)
                except (OSError, ValueError):
                    continue
                found.append(file)
    return found[0] if found else None


def resolve_soundfont(home, data_dir, settings):
    """Use current player SF2; auto-detect only when none is configured."""
    effective = dict(settings)
    options = normalize_audio(effective, require_files=False)
    if not options['fonts']:
        font = _existing_soundfont(home, data_dir)
        if font is None:
            raise FileNotFoundError(
                'ไม่พบ SoundFont ของ X-Stage: กรุณาตั้งค่า SoundFont ในเครื่องเล่นหลักครั้งเดียว ' 
                'หรือวางไฟล์ SF2 ในโฟลเดอร์ SoundFonts ของโปรแกรม')
        audio = dict(effective.get('soundfont_audio') or {})
        audio['fonts'] = [{'path': str(font), 'gain_db': -6.0}]
        effective['soundfont_audio'] = audio
    checked = normalize_audio(effective, require_files=True)
    return effective, Path(checked['fonts'][0]['path'])


def resolve_ffmpeg(home, settings):
    """Prefer the FFmpeg binary bundled into the Windows EXE by imageio-ffmpeg."""
    candidates = []
    try:
        import imageio_ffmpeg
        candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
    except (ImportError, RuntimeError, OSError):
        pass
    candidates.extend((settings.get('web_ffmpeg'), Path(home) / 'native' / 'x64' / 'ffmpeg.exe',
                       Path(home) / 'ffmpeg.exe', shutil.which('ffmpeg')))
    for candidate in candidates:
        if not candidate:
            continue
        binary = str(candidate)
        if not Path(binary).is_file():
            continue
        try:
            result = subprocess.run([binary, '-version'], capture_output=True, text=True,
                                    errors='replace', timeout=8, check=False,
                                    **silent_subprocess_options())
            if result.returncode == 0 and 'ffmpeg version' in result.stdout.lower():
                return binary
        except (OSError, subprocess.TimeoutExpired):
            continue
    raise FileNotFoundError(
        'ไม่พบ FFmpeg ที่พร้อมใช้: รุ่น Windows ต้อง Build พร้อม imageio-ffmpeg ' 
        'หรือมี ffmpeg.exe ติดตั้งไว้แล้ว ไม่ต้องเลือกไฟล์จากหน้าซิงก์')


def online_soundfont_choices(home, data_dir, settings):
    """List installed and PC-configured fonts without modifying the player.

    Default choice in the UI is always the PC's current layered setup. This
    list is only for an explicit single-SoundFont web rendering override.
    """
    pc = normalize_audio(settings, require_files=False)
    paths = []
    seen = set()
    def add(path):
        path = Path(path)
        if path.suffix.lower() not in ('.sf2', '.sfz') or not path.is_file():
            return
        key = str(path.resolve()).casefold()
        if key not in seen:
            seen.add(key)
            paths.append(path)
    for row in pc['fonts']:
        add(row['path'])
    home, data_dir = Path(home), Path(data_dir)
    for parent in (data_dir / 'SoundFonts', data_dir / 'soundfonts',
                   home / 'SoundFonts', home / 'soundfonts',
                   home / 'SoundFont', home / 'native' / 'soundfonts',
                   home.parent / 'SoundFonts'):
        if parent.is_dir():
            for file in sorted(parent.iterdir()):
                if file.is_file() and not file.is_symlink():
                    add(file)
    return paths


def resolve_online_soundfont(home, data_dir, settings, override=None):
    """PC's exact profile unless the user explicitly selects a single font.

    The caller receives a copy; the current player settings are never changed.
    """
    if override is None:
        return resolve_soundfont(home, data_dir, settings)
    font = Path(override)
    inspect_font(font)
    effective = dict(settings)
    audio = dict(effective.get('soundfont_audio') or {})
    audio['fonts'] = [{'path': str(font), 'gain_db': -6.0}]
    effective['soundfont_audio'] = audio
    # A PC mapping to a different SoundFont would cause BASS to reject the
    # render. An explicit override uses only the selected font's GM mapping.
    effective['instrument_fonts'] = {}
    effective['soundfont_follow_song'] = True
    checked = normalize_audio(effective, require_files=True)
    return effective, Path(checked['fonts'][0]['path'])


def prepare_online_renderer(home, data_dir, settings, *, override=None):
    """No dialog: PC SoundFonts unless explicitly overridden for online sync."""
    effective, font = resolve_online_soundfont(home, data_dir, settings, override=override)
    ffmpeg = resolve_ffmpeg(home, effective)
    from .offline_generator import choose_workers
    workers = choose_workers('auto', font)
    return effective, font, ffmpeg, workers
