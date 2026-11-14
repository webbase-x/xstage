"""Conservative starting settings from local resources; not an audio benchmark."""
from __future__ import annotations
import ctypes
import os
import platform
from pathlib import Path

GIB = 1024 ** 3


class MemoryStatus(ctypes.Structure):
    _fields_ = [('length', ctypes.c_uint32), ('load', ctypes.c_uint32)] + [
        (name, ctypes.c_uint64) for name in
        ('total', 'available', 'page_total', 'page_available',
         'virtual_total', 'virtual_available', 'extended')]


def machine_specs():
    result = dict(cpu=platform.processor() or platform.machine() or 'ไม่ทราบรุ่น',
                  threads=os.cpu_count() or 1, total=0, available=0)
    try:
        if os.name == 'nt':
            state = MemoryStatus()
            state.length = ctypes.sizeof(state)
            fn = ctypes.WinDLL('kernel32', use_last_error=True).GlobalMemoryStatusEx
            fn.argtypes = [ctypes.POINTER(MemoryStatus)]
            fn.restype = ctypes.c_int
            if fn(ctypes.byref(state)):
                result.update(total=state.total, available=state.available)
        else:
            # Development/offline hosts only; desktop playback is Windows.
            values = {}
            for line in Path('/proc/meminfo').read_text().splitlines():
                key, value = line.split(':', 1)
                values[key] = int(value.strip().split()[0]) * 1024
            result.update(total=values['MemTotal'], available=values['MemAvailable'])
    except (OSError, ValueError, KeyError, AttributeError):
        pass
    return result


def recommend(fonts, specs=None):
    specs = machine_specs() if specs is None else specs
    total = max(0, specs.get('total', 0)) / GIB
    available = max(0, specs.get('available', 0)) / GIB
    threads = max(1, specs.get('threads', 1))
    size = 0
    unknown = False
    for row in fonts:
        path = Path(row['path'])
        try:
            size += path.stat().st_size
        except OSError:
            unknown = True
        # SFZ refers to external samples: its text size is not sample memory.
        unknown |= path.suffix.lower() == '.sfz'
    font_gib = size / GIB
    # File size is a pressure hint, not an estimate of exact resident samples.
    reserve = max(2.0, font_gib * 1.5 + 1.0)
    if not total or not available:
        tier, reason = 'safe', 'อ่านข้อมูล RAM ไม่ได้ ใช้ค่าเผื่อความเสถียร'
    elif available < reserve or total < 4 or threads < 4:
        tier, reason = 'light', 'ทรัพยากรหรือ RAM ว่างจำกัดเมื่อเทียบกับชุดเสียง'
    elif threads >= 8 and total >= 15 and available >= max(4, reserve) and not unknown:
        tier, reason = 'high', 'จำนวนเธรดและ RAM ผ่านเกณฑ์เริ่มต้นสำหรับคุณภาพสูง'
    else:
        tier, reason = 'safe', 'เลือก Sinc 8 เพื่อเผื่อกำลังให้การเล่นเพลงและหน้าจอ'
    if unknown:
        reason += ' • ขนาดตัวอย่างเสียงไม่ครบ (SFZ/ไฟล์อ่านไม่ได้)'
    presets = {
        'high': dict(quality=2, voices=512, buffer_ms=100),
        'safe': dict(quality=1, voices=256, buffer_ms=150),
        'light': dict(quality=0, voices=128, buffer_ms=200),
    }
    return dict(**presets[tier], tier=tier, reason=reason, specs=dict(specs),
                font_bytes=size, unknown_samples=bool(unknown))


def summary(result):
    s = result['specs']
    ram = (f"{s['total']/GIB:.1f} GB / ว่าง {s['available']/GIB:.1f} GB"
           if s.get('total') else 'อ่าน RAM ไม่ได้')
    return (f"{s.get('cpu', 'CPU')} • {s.get('threads', 1)} เธรด • RAM {ram}\n"
            f"คุณภาพ {result['quality']} • {result['voices']} เสียง • "
            f"บัฟเฟอร์ {result['buffer_ms']} ms — {result['reason']}\n"
            "เป็นค่าประเมินจากสเปก ไม่ใช่ผลทดสอบเสียงจริง; ประเมินใหม่ก่อนเริ่มเพลง")


def resolve_options(options):
    if options.get('quality_mode') != 'auto':
        return dict(options)
    result = recommend(options['fonts'])
    return {**options, **{k: result[k] for k in ('quality', 'voices', 'buffer_ms')},
            'auto_assessment': result}
