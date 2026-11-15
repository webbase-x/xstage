"""Read-only dBase III catalog and NCN adapter; never execute the old player.

DBF is a public table format. NCN cursor24 uses little-endian uint16 values
at 24 units per MIDI quarter note. EMK legacy is handled by a separate reader.
"""
from __future__ import annotations

import os
import struct
import re
from functools import lru_cache
from pathlib import Path

DEFAULT_LEGACY = Path(r'D:\newKaraoke\eXtreme Karaoke 2026.10\eXtreme Karaoke 2026')
DEFAULT_DESTINATION = Path(r'D:\newKaraoke\Karaoke')


def dbf_records(path):
    """Yield live records, streaming bounded chunks; preserve source file bytes."""
    with Path(path).open('rb') as stream:
        header = stream.read(32)
        if len(header) != 32 or header[0] not in (3, 0x30, 0x31, 0x83):
            raise ValueError('ไม่ใช่ดัชนี DBF ที่รองรับ')
        count, header_size, record_size = struct.unpack_from('<IHH', header, 4)
        if not 33 <= header_size <= 65535 or not 2 <= record_size <= 65535:
            raise ValueError('ส่วนหัว DBF ไม่ถูกต้อง')
        descriptors = stream.read(header_size - 32)
        fields, offset = [], 1
        for start in range(0, len(descriptors) - 31, 32):
            if descriptors[start] == 13:
                break
            item = descriptors[start:start + 32]
            name = item[:11].split(b'\0')[0].decode('ascii', errors='strict')
            width = item[16]
            if not width or offset + width > record_size:
                raise ValueError('ขนาดฟิลด์ DBF ไม่ถูกต้อง')
            fields.append((name, offset, width))
            offset += width
        stream.seek(header_size)
        for index in range(count):
            record = stream.read(record_size)
            if len(record) != record_size:
                raise ValueError(f'DBF ถูกตัดที่รายการ {index + 1}')
            if record[:1] == b'*':
                continue
            result = {}
            for name, offset, width in fields:
                raw = record[offset:offset + width].rstrip(b' \0')
                try:
                    result[name] = raw.decode('cp874')
                except UnicodeDecodeError:
                    result[name] = raw.decode('cp874', errors='replace')
            yield result


def catalog_location(root):
    root = Path(root)
    if root.is_file() and root.suffix.lower() == '.dbf':
        return root, root.parent.parent
    candidates = [root / 'Data' / 'SONG.DBF', root / 'SONG.DBF']
    for candidate in candidates:
        if candidate.is_file():
            return candidate, root
    raise ValueError('ไม่พบ Data\\SONG.DBF กรุณาเลือกโฟลเดอร์โปรแกรมเดิม')


def safe_code(value):
    value = value.strip()
    if not value or value in ('.', '..') or any(ch in value for ch in '/\\:\0'):
        raise ValueError('รหัสเพลงในดัชนีไม่ถูกต้อง')
    return value


@lru_cache(maxsize=32)
def ncn_root(root):
    folder = root / 'Songs' / 'MIDI' / 'NCN'
    return root if not folder.is_dir() and (root / 'Song').is_dir() else folder


def legacy_asset(root, row):
    """Resolve the documented folder convention; never trust catalog traversal."""
    code = safe_code(row.get('CODE', ''))
    subtype = row.get('SUB_TYPE', '').strip().upper()
    media_type = row.get('TYPE', 'MIDI').strip().upper()
    filename = Path(row.get('FILE_NAME', '').replace('\\', '/')).name
    if filename in ('', '.', '..'):
        filename = code + '.mid'
    if subtype == 'NCN':
        folder = ncn_root(root)
        file = folder / 'Song' / code[0] / filename
        if filename.casefold() != (code + '.mid').casefold() and not file.is_file():
            file = folder / 'Song' / code[0] / (code + '.mid')
        return file, 'MIDI', 'NCN24', True
    if subtype in ('EMK', 'XMK', 'KMID', 'RMS'):
        extension = {'KMID': '.mid', 'RMS': '.rms'}.get(subtype, '.' + subtype.lower())
        file = root / 'Songs' / 'MIDI' / subtype / code[0] / (code + extension)
        return file, 'MIDI' if subtype in ('EMK', 'KMID') else subtype, subtype, subtype in ('EMK', 'KMID')
    extension = Path(filename).suffix.lower()
    media_kind = 'VIDEO' if media_type == 'VIDEO' else 'AUDIO'
    file = root / 'Songs' / media_kind / subtype / code[0] / filename
    return file, media_kind, subtype or extension.lstrip('.').upper(), extension in {'.mid', '.kar', '.wav', '.mp3', '.wma', '.mp4', '.avi', '.mpg', '.wmv', '.mkv', '.mov'}


def dbf_count(path, cancelled=None, events=None):
    """Count active DBF records using record flags, without decoding metadata twice."""
    count=0
    with Path(path).open('rb') as stream:
        header=stream.read(32)
        if len(header)!=32 or header[0] not in (3,0x30,0x31,0x83):
            raise ValueError('ไม่ใช่ดัชนี DBF ที่รองรับ')
        total,offset,width=struct.unpack_from('<IHH',header,4)
        if not 33<=offset<=65535 or not 2<=width<=65535:
            raise ValueError('ส่วนหัว DBF ไม่ถูกต้อง')
        stream.seek(offset)
        remaining=total
        while remaining:
            if cancelled and cancelled.is_set():break
            records=min(remaining,max(1,1024*1024//width))
            block=stream.read(records*width)
            if len(block)!=records*width:raise ValueError('DBF ถูกตัดระหว่างนับรายการ')
            count+=sum(block[i]!=42 for i in range(0,len(block),width))
            remaining-=records
            if events:events(dict(type='progress',done=count,total=None,path=str(path)))
    return count


def import_catalog(root, library, progress=None, cancelled=None, errors=None, events=None, log_items=True, inspect_media=True):
    dbf, root = catalog_location(root)
    root = root.resolve()
    source_catalog = str(dbf.resolve())
    from .ingest import Inspector
    inspector = Inspector()
    if events:events(dict(type='phase',phase='นับรายการในคลังเดิม',total=None))
    target=dbf_count(dbf,cancelled,events) if events else None
    if events:events(dict(type='phase',phase='อ่านคลังเพลงเดิม',total=target,**({'target':target} if log_items else {})))
    processed=0
    imported, unsupported, invalid, batch = 0, 0, 0, []
    for row in dbf_records(dbf):
        if cancelled and cancelled.is_set():
            break
        processed+=1
        if events:events(dict(type='progress',done=processed-1,total=target,path=row.get('CODE','')))
        try:
            file, kind, profile, playable = legacy_asset(root, row)
            details = {}
            if playable and inspect_media:
                try:
                    details, notes = inspector.inspect(file)
                    if errors is not None:
                        errors.extend(f'คำเตือน: {file}: {note}' for note in notes)
                    profile, kind = details['format'], details['kind']
                except (OSError, ValueError, EOFError) as error:
                    if errors is not None:
                        errors.append(f'ข้ามการเล่น: {file}: {error}')
                    playable = False
                    invalid += 1
            batch.append(dict(path=os.path.abspath(file), code=row.get('CODE', ''),
                title=row.get('TITLE', '') or details.get('title') or row.get('CODE', ''), artist=row.get('ARTIST', '') or details.get('artist', ''),
                kind=kind, format=profile, playable=int(playable) if inspect_media else 0,
                first_lyric=row.get('LYR_TITLE', '') or details.get('first_lyric', ''), rhythm=row.get('RHYTHM', ''),
                key_signature=row.get('KEY', '') or details.get('key_signature', ''), bpm=row.get('TEMPO', '') or details.get('bpm', ''),
                source_catalog=source_catalog))
            unsupported += not playable
            if events:
                if log_items:events(dict(type='item',ok=bool(playable),path=str(file),code=row.get('CODE',''),title=row.get('TITLE',''),artist=row.get('ARTIST',''),note='' if playable else 'นำเข้าข้อมูลได้ แต่ไฟล์ยังไม่พร้อมเล่น'))
                else:events(dict(type='progress',done=processed,total=target,path=str(file)))
        except (ValueError, OSError) as error:
            invalid += 1
            if errors is not None:
                errors.append(f'ดัชนีเดิม: {error}')
            if events:
                if log_items:events(dict(type='item',ok=False,path=row.get('CODE',''),title=row.get('TITLE',''),note=str(error)))
                else:events(dict(type='progress',done=processed,total=target))
        if len(batch) >= 1000:
            imported += library.upsert_catalog(batch,preserve_playable=not inspect_media)
            batch.clear()
            if progress:
                progress(imported)
    imported += library.upsert_catalog(batch,preserve_playable=not inspect_media)
    return imported, unsupported, invalid


def ncn_pair(midi):
    from .ingest import Inspector
    return Inspector().ncn_pair(Path(midi))


def ncn_lyrics(midi, song):
    """Explicit NCN24 profile: four headers; one line marker then CP874 bytes.

    Historical files may contain surplus cursor entries. We read only the
    matching text span and never invent cue times for a short cursor file.
    """
    from .lyrics import Lyrics, LyricLine
    lyr, cur = ncn_pair(midi)
    if not lyr.is_file() or not cur.is_file():
        return None
    result = parse_ncn_lyrics(lyr.read_bytes(), cur.read_bytes(), song)
    result.source_files = [str(lyr), str(cur)]
    return result


def ncn_body(raw):
    from .lyrics import ncn_text_bytes
    rows = ncn_text_bytes(raw).splitlines()
    if len(rows) < 4:
        raise ValueError('LYR มีส่วนหัวไม่ครบ 4 บรรทัด')
    text_rows = rows[4:]
    removed_footer = 0
    # Old collections append an un-timed application credit after the song.
    # It has no CUR entry. Never discard the timed lyrics because of that tail.
    footer = re.compile(r'^(?:nick[\s_-]*karaoke(?:\s+professional)?|นิค[\s_-]*คาราโอเกะ)\s*$', re.I)
    while text_rows:
        last = text_rows[-1].strip(b' \0\x1a')
        if not last or footer.fullmatch(last.decode('cp874', errors='replace')):
            text_rows.pop()
            removed_footer += 1
        else:
            break
    # NCN uses one cursor entry for the line marker, not two for Windows CRLF.
    raw = b'\n' + b'\n'.join(text_rows) if text_rows else b''
    return raw,removed_footer


def parse_ncn_lyrics(raw, cursor, song):
    from .lyrics import Lyrics, LyricLine
    if len(raw) > 1024*1024 or len(cursor) > 2*1024*1024:
        raise ValueError('LYR/CUR ใหญ่เกินขอบเขตที่รองรับ')
    if not song.division or song.division & 0x8000:
        raise ValueError('NCN24 ต้องใช้ MIDI แบบ PPQ')
    raw,removed_footer=ncn_body(raw)
    warnings = []
    if len(cursor) % 2:
        if cursor[-1:] == b'\xff':
            cursor = cursor[:-1]  # Historical NCN end marker, one byte.
        elif len(cursor) // 2 >= len(raw):
            cursor = cursor[:-1]
            warnings.append('ข้ามไบต์ท้าย CUR ที่ไม่มีคู่')
        else:
            cursor = cursor[:-1]
            warnings.append('CUR จบด้วยข้อมูลไม่ครบหนึ่งค่าเวลา')
    values = [item[0] for item in struct.iter_unpack('<H', cursor)]
    if len(values) < len(raw):
        warnings.append(f'ข้อความท้าย {len(raw)-len(values)} อักขระไม่มีเวลา; แสดงเฉพาะช่วงที่มีเวลา')
    lines, words, text, start = [], [], '', 0.0
    previous = 0
    for index, byte in enumerate(raw[:len(values)]):
        value = values[index]
        if byte in (10, 13):
            if text.strip():
                lines.append(LyricLine(start, text, words))
                text, words = '', []
            continue
        if value == 65535:
            continue
        if value < previous:
            value = previous
        previous = value
        at = song.tick_seconds(value * song.division / 24)
        if at > song.duration + 10:
            warnings.append('ข้อมูลเวลา CUR ท้ายเพลงเกินช่วง MIDI; ใช้เฉพาะช่วงก่อนหน้า')
            break
        char = bytes([byte]).decode('cp874', errors='replace')
        if not text:
            start = at
        # Thai marks paint with their base glyph, without changing cursor index.
        if words and (char in '\u0e31\u0e34\u0e35\u0e36\u0e37\u0e38\u0e39\u0e3a\u0e47\u0e48\u0e49\u0e4a\u0e4b\u0e4c\u0e4d\u0e4e'):
            when, previous_text = words[-1]
            words[-1] = (when, previous_text + char)
        else:
            words.append((at, char))
        text += char
    if text.strip():
        lines.append(LyricLine(start, text, words))
    if raw and not lines:
        raise ValueError('ไม่พบข้อมูลเวลาเนื้อร้องที่จับคู่ได้')
    result = Lyrics(lines)
    result.profile = 'NCN24-u16le-cp874'
    result.warnings = warnings
    result.removed_footer_lines = removed_footer
    result.source_character_count = len(raw)
    result.cursor_count = len(values)
    return result
