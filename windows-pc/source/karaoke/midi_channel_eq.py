"""Sparse, validated 31-band EQ presets for independent BASSMIDI channels."""
from __future__ import annotations
from .graphic_eq import flat, validate


def normalized(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError('ข้อมูล EQ รายช่อง MIDI ไม่ถูกต้อง')
    result = {}
    for key, state in value.items():
        try:
            channel = int(key)
        except (TypeError, ValueError):
            raise ValueError('หมายเลขช่อง EQ ไม่ถูกต้อง') from None
        if type(key) is bool or str(channel) != str(key) or not 0 <= channel < 16:
            raise ValueError('หมายเลขช่อง EQ ต้องอยู่ระหว่าง 0–15')
        if str(channel) in result:
            raise ValueError('ช่อง EQ ซ้ำกัน')
        result[str(channel)] = validate(state)
    return result


def get(settings, channel):
    if type(channel) is not int or not 0 <= channel < 16:
        raise ValueError('หมายเลขช่อง EQ ไม่ถูกต้อง')
    return normalized(settings).get(str(channel), flat())


def changed(settings, channel, state):
    result = normalized(settings)
    if type(channel) is not int or not 0 <= channel < 16:
        raise ValueError('หมายเลขช่อง EQ ไม่ถูกต้อง')
    good = validate(state)
    if good == flat():
        result.pop(str(channel), None)
    else:
        result[str(channel)] = good
    return result


def apply_to_player(player, settings):
    states = normalized(settings)
    if not states:
        return False
    if not hasattr(player.output, 'set_channel_eq'):
        raise OSError('EQ 31 ย่านรายช่องต้องใช้ BASSMIDI + SoundFont')
    for channel, state in states.items():
        player.set_channel_eq(int(channel), state)
    return True
