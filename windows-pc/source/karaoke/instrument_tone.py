"""Validated BASSMIDI per-channel and per-drum *tone* presets.

Cutoff/resonance are SoundFont filter controls, not 31-band audio EQ.
They are available on BASSMIDI only and never silently change Windows MIDI.
"""
from __future__ import annotations

import copy

CHANNEL_DEFAULT = {'cutoff': 64, 'resonance': 64}
DRUM_DEFAULT = {'cutoff': 64, 'resonance': 64, 'level': 127}
DRUM_NOTES = (
    (35, 'Kick 35'), (36, 'Kick 36'), (37, 'Side stick'),
    (38, 'Snare 38'), (40, 'Snare 40'),
    (42, 'Hi-hat ปิด'), (44, 'Hi-hat เท้า'), (46, 'Hi-hat เปิด'),
    (41, 'Low tom'), (45, 'Mid tom'), (48, 'High tom'),
    (49, 'Crash'), (51, 'Ride'), (54, 'Tambourine'),
    (56, 'Cowbell'), (75, 'Claves'),
)


def value(number, label):
    if type(number) is not int or not 0 <= number <= 127:
        raise ValueError(f'{label} ต้องเป็นจำนวนเต็ม 0–127')
    return number


def normalized(raw):
    """Return a *copy* with canonical string keys, reject invalid untrusted data.

    Sparse keys mean no override, so a song's original controllers remain
    authoritative for channels the user has not edited.
    """
    if raw is None:
        return {'channels': {}, 'drums': {}}
    if not isinstance(raw, dict):
        raise ValueError('ข้อมูลโทนเสียง MIDI ไม่ถูกต้อง')
    if set(raw) - {'channels', 'drums'}:
        raise ValueError('พบช่องข้อมูลโทนเสียง MIDI ที่ไม่รู้จัก')
    result = {'channels': {}, 'drums': {}}
    for group, limit, defaults in (
        ('channels', 15, CHANNEL_DEFAULT), ('drums', 127, DRUM_DEFAULT)
    ):
        entries = raw.get(group, {})
        if not isinstance(entries, dict):
            raise ValueError('รายการโทนเสียง MIDI ต้องเป็นรูปแบบตาราง')
        for key, state in entries.items():
            try:
                number = int(key)
            except (TypeError, ValueError):
                raise ValueError('หมายเลขช่อง/กลองไม่ถูกต้อง') from None
            if isinstance(key, bool) or str(number) != str(key) or not 0 <= number <= limit:
                raise ValueError('หมายเลขช่อง/กลองเกินช่วงที่รองรับ')
            if str(number) in result[group]:
                raise ValueError('ช่อง MIDI หรือกลองซ้ำกัน')
            if not isinstance(state, dict) or set(state) != set(defaults):
                raise ValueError('ค่าปรับโทนเสียงไม่ครบ')
            result[group][str(number)] = {
                name: value(state[name], name) for name in defaults
            }
    return result


def apply_to_player(player, preset):
    """Apply saved settings only to BASSMIDI. No-op for an empty preset.

    A Windows MIDI device cannot provide deterministic per-key filter control;
    tell the user instead of claiming to have processed the instrument.
    """
    preset = normalized(preset)
    if not any(preset.values()):
        return False
    if not hasattr(player.output, 'set_channel_tone'):
        raise OSError('โทนเสียงแยกเครื่องดนตรีต้องเลือก BASSMIDI และ SoundFont')
    for channel, settings in preset['channels'].items():
        player.set_channel_tone(int(channel), **settings)
    for note, settings in preset['drums'].items():
        player.set_drum_tone(int(note), **settings)
    return True


def changed(preset, group, index, state):
    result = normalized(preset)
    defaults = CHANNEL_DEFAULT if group == 'channels' else DRUM_DEFAULT
    if group not in ('channels', 'drums'):
        raise ValueError('ไม่รู้จักกลุ่มโทนเสียง')
    maximum = 15 if group == 'channels' else 127
    if type(index) is not int or not 0 <= index <= maximum:
        raise ValueError('ช่องเครื่องดนตรีหรือหมายเลขกลองไม่ถูกต้อง')
    if not isinstance(state, dict) or set(state) != set(defaults):
        raise ValueError('ค่าปรับโทนเสียงไม่ครบ')
    result[group][str(index)] = {name: value(state[name], name) for name in defaults}
    return result


def get(preset, group, index):
    normalized_preset = normalized(preset)
    defaults = CHANNEL_DEFAULT if group == 'channels' else DRUM_DEFAULT
    return copy.deepcopy(normalized_preset[group].get(str(index), defaults))
