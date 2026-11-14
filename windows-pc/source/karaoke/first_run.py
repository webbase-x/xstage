"""Local audio setup state and portable backup metadata. No APO writes on startup."""
import copy
import hashlib
import json
from pathlib import Path
import platform
import shutil
import time
from .library import write_json

LOCAL_KEYS = ('system_eq_device', 'system_eq_profiles', 'midi_device', 'audio_setup')
CURVE_KEYS = ('system_eq', 'parametric_eq', 'graphic_eq', 'song_eq', 'output_eq')


def machine_key():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography',
                            0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            identity = winreg.QueryValueEx(key, 'MachineGuid')[0]
    except (ImportError, OSError):
        identity = platform.node()
    return hashlib.sha256(str(identity).encode('utf-8')).hexdigest()


def portable_settings(settings):
    """Retain user curves for deliberate import, without binding them to new hardware."""
    result = copy.deepcopy(settings)
    curves = result.setdefault('imported_audio_presets', {})
    for key in CURVE_KEYS:
        if key in result:
            curves[key] = result.pop(key)
    for key in LOCAL_KEYS:
        result.pop(key, None)
    result.pop('eq_scope', None)
    if not curves:
        result.pop('imported_audio_presets', None)
    return result


def settings_for_restore(folder, settings):
    metadata = Path(folder) / 'transfer-meta.json'
    if metadata.is_file():
        info = json.loads(metadata.read_text(encoding='utf-8'))
        if info.get('machine') == machine_key():
            return copy.deepcopy(settings)
    return portable_settings(settings)


def backup_settings(path):
    path = Path(path)
    if not path.is_file():
        return None
    destination = path.parent / 'setup-backups' / (
        time.strftime('%Y%m%d-%H%M%S') + '-' + str(time.time_ns()))
    destination.mkdir(parents=True, exist_ok=False)
    target = destination / path.name
    shutil.copy2(path, target)
    if target.read_bytes() != path.read_bytes():
        raise OSError('สำรองการตั้งค่าไม่สำเร็จ จึงยังไม่เปลี่ยนการตั้งค่า')
    return target


def read_state(data_dir):
    path = Path(data_dir) / 'audio-setup.json'
    if not path.is_file():
        return {}
    state = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(state, dict):
        raise ValueError('ข้อมูลตั้งค่าเสียงไม่ถูกต้อง')
    return state


def setup_reason(state, devices, machine=None):
    if not state:
        return 'first_run'
    if state.get('machine') != (machine or machine_key()):
        return 'new_machine'
    if state.get('device') and state['device'] not in devices:
        return 'missing_device'
    return None


def hardware_changed(data_dir):
    if data_dir is None:
        return False
    try:
        state = read_state(data_dir)
    except (OSError, ValueError):
        return True
    return bool(state.get('machine') and state['machine'] != machine_key())


def enumerate_devices():
    from .windows_audio import audio_context
    with audio_context() as sc:
        default = sc.default_speaker()
        return [(str(s.id), s.name, default is not None and str(s.id) == str(default.id))
                for s in sc.all_speakers()]


def test_tone(device):
    """A short -30 dBFS tone on the chosen endpoint; never change Windows volume."""
    import numpy as np
    from .windows_audio import audio_context
    rate = 48000
    count = int(rate * .7)
    t = np.arange(count) / rate
    tone = .03 * np.sin(2 * np.pi * 660 * t) * np.sin(np.pi * t / .7) ** 2
    with audio_context() as sc:
        speaker = next((s for s in sc.all_speakers() if str(s.id) == device), None)
        if speaker is None:
            raise OSError('อุปกรณ์นี้ถูกถอดออก กรุณาเลือกใหม่')
        channels = min(2, speaker.channels)
        if channels < 1:
            raise OSError('อุปกรณ์ไม่มีช่องเสียงที่ใช้งานได้')
        speaker.play(np.repeat(tone[:, None], channels, axis=1), samplerate=rate)


def save_choice(app, device, device_name, use_eq, heard, eq_confirmed=False):
    if not heard:
        raise ValueError('กรุณาทดสอบและยืนยันว่าได้ยินเสียงก่อน')
    rows = enumerate_devices()
    if device not in [row[0] for row in rows]:
        raise ValueError('อุปกรณ์เปลี่ยนไป กรุณาตรวจสอบอีกครั้ง')
    if not any(row[0] == device and row[2] for row in rows):
        raise ValueError('ตั้งอุปกรณ์นี้เป็นเอาต์พุตหลักใน Windows ก่อน เพื่อให้เพลงออกตรงกับเสียงทดสอบ')
    from . import system_eq
    eq_ready = False
    if use_eq:
        config = system_eq.installation()
        if not system_eq.linked(config):
            raise ValueError('ยังเชื่อม EQ ไม่สำเร็จ เลือกใช้งานคาราโอเกะก่อนได้')
        if not eq_confirmed:
            raise ValueError('กรุณาทดสอบ EQ ใน Device Selector และยืนยันผลด้วยตนเองก่อน')
        eq_ready = True
    previous = copy.deepcopy(app.settings)
    old_state = read_state(app.data_dir)
    imported = old_state.get('machine') not in (None, machine_key())
    # Settings restored from an unknown/other computer must not activate old curves.
    prior_device = old_state.get('device') or app.settings.get('system_eq_device')
    if imported or (prior_device and prior_device != device):
        updated = portable_settings(app.settings)
    else:
        updated = copy.deepcopy(app.settings)
    updated['audio_setup'] = {'device': device, 'name': device_name}
    if eq_ready:
        updated['system_eq_device'] = device
        # This marks the device choice, not proof that an APO is processing audio.
    state = {'schema': 1, 'machine': machine_key(), 'device': device,
             'name': device_name, 'system_eq_requested': bool(use_eq),
             'heard': True, 'eq_user_confirmed': eq_ready, 'status': 'ready' if eq_ready else 'karaoke_ready'}
    backup_settings(app.settings_path)
    try:
        app.settings.clear()
        app.settings.update(updated)
        app.save_settings()
        write_json(Path(app.data_dir) / 'audio-setup.json', state)
    except Exception:
        app.settings.clear()
        app.settings.update(previous)
        app.save_settings()
        raise
    return state


def write_transfer_metadata(folder):
    write_json(Path(folder) / 'transfer-meta.json', {'schema': 1, 'machine': machine_key(),
        'media_included': False, 'soundfonts_included': False})


def open_tool(app, name, arguments=()):
    from .external_program import launch
    path = Path(app.home) / 'tools' / name
    if not path.is_file():
        raise OSError('ชุดติดตั้งไม่ครบ: ' + name)
    return launch(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', path,
                   *arguments], path.parent, hidden=True)
