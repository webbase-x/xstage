"""Bounded legacy SFDS/EMK archive reader, independently implemented.

Only the documented historical fixed-format profile is accepted. There is no
key search, dongle access, executable patching, or XMK/XSF license handling.
Format reference: docs.rs/crate/emk-rs/0.2.0/source/emk-spec.md.
The directory layout was also checked against the user's existing old files.
"""
from __future__ import annotations
import hashlib
import io
import struct
import zlib
from .inspection_errors import ReviewRequired

LEGACY_MASK = bytes.fromhex('AFF24C9CE9EA9943')
MAX_ASSET = 8 * 1024 * 1024
_MASK_TABLES=tuple(bytes(value^mask for value in range(256)) for mask in LEGACY_MASK)


def exact(stream, length):
    value = stream.read(length)
    if len(value) != length:
        raise ValueError('EMK directory ไม่สมบูรณ์')
    return value


def integer(stream):
    tag = exact(stream, 1)[0]
    size = {2: 1, 3: 2, 4: 4}.get(tag)
    if not size:
        raise ReviewRequired(f'EMK integer type {tag} ยังไม่รองรับ')
    return int.from_bytes(exact(stream, size), 'little')


def string(stream):
    if exact(stream, 1) != b'\x06':
        raise ReviewRequired('EMK string type ยังไม่รองรับ')
    return exact(stream, exact(stream, 1)[0])


def unpack_emk(data):
    if len(data)>64*1024*1024:raise ReviewRequired('EMK ใหญ่เกินขอบเขตที่รองรับ')
    if len(data)<52:raise ValueError('ขนาด EMK ไม่อยู่ในขอบเขตที่รองรับ')
    if not data.startswith(b'.SFDS'):
        expanded=bytearray(len(data))
        for offset,table in enumerate(_MASK_TABLES):expanded[offset::8]=data[offset::8].translate(table)
        data=bytes(expanded)
    if not data.startswith(b'.SFDS'):
        raise ReviewRequired('ไม่ใช่ legacy EMK profile ที่รองรับ ต้องตรวจเพิ่ม')
    directory_start, directory_end = struct.unpack_from('<QQ', data, 0x22)
    if not 50 <= directory_start < directory_end <= len(data):
        raise ValueError('ตำแหน่ง EMK directory ไม่ถูกต้อง')
    directory = io.BytesIO(data[directory_start:directory_end])
    assets = {}
    while directory.tell() < directory_end - directory_start:
        if exact(directory, 4) != b'SFDS':
            raise ValueError('ไม่พบ SFDS entry marker')
        tag = string(directory).decode('ascii')
        size, reserved, start, end, compression, flags = [integer(directory) for _ in range(6)]
        digest = exact(directory, 16)
        string(directory)
        integer(directory)
        if tag not in ('MIDI_DATA', 'LYRIC_DATA', 'CUR_DATA', 'CURSOR_DATA', 'HEADER', 'SONG_INFO'):
            continue
        if size>MAX_ASSET:raise ReviewRequired('EMK asset ใหญ่เกินขอบเขตที่รองรับ')
        if tag in assets or size<0 or not 50 <= start <= end <= directory_start:
            raise ValueError('EMK entry size/offset ไม่ถูกต้อง')
        payload = data[start:end]
        if compression == 1:
            inflater = zlib.decompressobj()
            try:
                payload = inflater.decompress(payload, size + 1)
            except zlib.error as error:
                raise ValueError('EMK compressed entry เสียหาย') from error
            if len(payload) != size or inflater.unconsumed_tail or not inflater.eof:
                raise ValueError('EMK compressed entry ไม่สมบูรณ์หรือใหญ่เกินกำหนด')
        elif compression!=0:raise ReviewRequired('EMK compression profile ยังไม่รองรับ')
        elif len(payload)!=size:raise ValueError('EMK entry ถูกตัด')
        # SFDS stores the MD5 bytes of the expanded entry. Used for integrity,
        # not for authentication or for obtaining any external authorization.
        if hashlib.md5(payload).digest() != digest:
            raise ValueError('EMK checksum ไม่ตรงกับข้อมูล')
        assets[tag] = payload
    if 'MIDI_DATA' not in assets:
        raise ValueError('EMK ไม่มี MIDI_DATA')
    return assets


def parse_emk(data):
    from .smf import parse_midi
    from .legacy import parse_ncn_lyrics
    assets = unpack_emk(data)
    song = parse_midi(assets['MIDI_DATA'], legacy=True)
    cursor = assets.get('CURSOR_DATA', assets.get('CUR_DATA'))
    if 'LYRIC_DATA' in assets and cursor is not None:
        try:
            song.lyrics = parse_ncn_lyrics(assets['LYRIC_DATA'], cursor, song)
            song.lyrics.profile = 'EMK-legacy-SFDS-NCN24'
        except ValueError as error:
            song.lyric_warning = str(error)
    else:
        song.lyric_warning = 'EMK มี MIDI แต่ไม่มี LYR/CUR ครบ'
    return song
