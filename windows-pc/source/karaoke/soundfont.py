"""Validated, JSON-serializable SoundFont settings and bounded SF2 inspection."""
from __future__ import annotations

import math
import struct
from pathlib import Path


PROFILES = {
    'stable': {'quality': 1, 'voices': 256, 'buffer_ms': 150},
    'balanced': {'quality': 1, 'voices': 256, 'buffer_ms': 60},
    'high': {'quality': 2, 'voices': 512, 'buffer_ms': 80},
    'light': {'quality': 0, 'voices': 128, 'buffer_ms': 100},
}
PROFILE_NAMES = {'stable': 'เน้นเสียงต่อเนื่อง', 'high': 'คุณภาพสูง', 'balanced': 'สมดุล', 'light': 'ประหยัด CPU'}


def bounded(value, low, high, label, integer=False):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{label}: กรุณาระบุเป็นตัวเลข') from None
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError(f'{label}: ต้องอยู่ระหว่าง {low} ถึง {high}')
    if integer and result != int(result):
        raise ValueError(f'{label}: ต้องเป็นจำนวนเต็ม')
    return int(result) if integer else result


def normalize_audio(settings, require_files=False):
    """Migrate the old single-font path without changing unrelated settings."""
    raw = settings.get('soundfont_audio', {})
    if not isinstance(raw, dict):
        raise ValueError('การตั้งค่า SoundFont ไม่ถูกต้อง')
    fonts = raw.get('fonts')
    if fonts is None:
        fonts = [{'path': settings['soundfont'], 'gain_db': -6.0}] if settings.get('soundfont') else []
    if not isinstance(fonts, list) or len(fonts) > 16:
        raise ValueError('เลือก SoundFont ได้ไม่เกิน 16 ไฟล์')
    result_fonts, seen = [], set()
    for row in fonts:
        if not isinstance(row, dict) or not isinstance(row.get('path'), str) or not row['path'].strip():
            raise ValueError('กรุณาเลือกไฟล์ SoundFont')
        path = Path(row['path'])
        if path.suffix.lower() not in ('.sf2', '.sfz'):
            raise ValueError('รองรับไฟล์ SF2 และ SFZ')
        key = str(path).replace('\\', '/').casefold()
        if key in seen:
            raise ValueError('มีไฟล์ SoundFont ซ้ำในรายการ')
        seen.add(key)
        if require_files:
            inspect_font(path)
        result_fonts.append({'path': str(path), 'gain_db': bounded(row.get('gain_db', -6), -24, 0, 'ระดับเสียง SoundFont')})
    if require_files and not result_fonts:
        raise ValueError('กรุณาเลือก SoundFont อย่างน้อยหนึ่งไฟล์')
    return {
        'fonts': result_fonts,
        'quality_mode': 'auto' if raw.get('quality_mode') == 'auto' else 'manual',
        'quality': bounded(raw.get('quality', 2), 0, 2, 'คุณภาพ', True),
        'voices': bounded(raw.get('voices', 512), 64, 1024, 'จำนวนเสียงพร้อมกัน', True),
        'buffer_ms': bounded(raw.get('buffer_ms', 80), 40, 200, 'บัฟเฟอร์', True),
        'effects_mode': raw.get('effects_mode') if raw.get('effects_mode') in ('song', 'custom') else 'song',
        'reverb': bounded(raw.get('reverb', 40), 0, 127, 'รีเวิร์บ', True),
        'chorus': bounded(raw.get('chorus', 12), 0, 127, 'คอรัส', True),
    }


def inspect_font(path):
    """Read metadata only, not the potentially gigabytes of sample data."""
    path = Path(path)
    size = path.stat().st_size
    if path.suffix.lower() == '.sfz':
        if not size:
            raise ValueError('ไฟล์ SFZ ว่าง')
        return {'name': path.stem, 'size': size, 'presets': None,
                'summary': 'SFZ: เก็บไฟล์ตัวอย่างเสียงไว้ตามโครงสร้างเดิม'}
    if path.suffix.lower() != '.sf2':
        raise ValueError('รองรับไฟล์ SF2 และ SFZ')
    presets = []
    with path.open('rb') as stream:
        header = stream.read(12)
        if len(header) != 12 or header[:4] != b'RIFF' or header[8:] != b'sfbk':
            raise ValueError('ไม่ใช่ไฟล์ SoundFont SF2 มาตรฐาน')
        limit = struct.unpack_from('<I', header, 4)[0] + 8
        if limit > size or limit < 12:
            raise ValueError('ไฟล์ SF2 ไม่สมบูรณ์')
        def chunks(start, end):
            while start + 8 <= end:
                stream.seek(start)
                tag, length = struct.unpack('<4sI', stream.read(8))
                stop = start + 8 + length
                if stop > end:
                    raise ValueError('ขนาดข้อมูลใน SF2 ไม่ถูกต้อง')
                yield tag, start + 8, length
                start = stop + (length & 1)
        for tag, offset, length in chunks(12, limit):
            if tag != b'LIST' or length < 4:
                continue
            stream.seek(offset)
            if stream.read(4) != b'pdta':
                continue
            for subtag, suboffset, sublength in chunks(offset + 4, offset + length):
                if subtag == b'phdr':
                    if sublength < 76 or sublength % 38 or sublength > 38 * 65536:
                        raise ValueError('ตารางเสียง SF2 ไม่ถูกต้อง')
                    stream.seek(suboffset)
                    data = stream.read(sublength)
                    for pos in range(0, sublength - 38, 38):
                        name, program, bank = struct.unpack_from('<20sHH', data, pos)
                        raw_name=name.split(b'\0')[0]
                        try:preset_name=raw_name.decode('utf-8')
                        except UnicodeDecodeError:preset_name=raw_name.decode('latin1')
                        presets.append((bank, program, preset_name))
    if not presets:
        raise ValueError('ไม่พบรายการเครื่องดนตรีใน SF2')
    gm = len({program for bank, program, _ in presets if bank == 0 and program < 128})
    drums = sum(bank == 128 for bank, _, _ in presets)
    return {'name': path.stem, 'size': size, 'presets': presets,
            'summary': f'{len(presets)} เสียง • GM {gm}/128 • ชุดกลอง {drums}'}
