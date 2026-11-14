"""Read-only, bounded media inspection shared by every import route."""
from pathlib import Path
import re
import os
import wave
from functools import lru_cache
from .lyrics import decode_text, parse_lrc, ncn_text_bytes
from .smf import parse_midi
from .emk import unpack_emk
from .inspection_errors import ReviewRequired


def bounded(path, limit):
    with Path(path).open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ReviewRequired('ไฟล์ใหญ่เกินขอบเขตที่รองรับ')
    return data


def id3_metadata(path):
    """Read bounded ID3v2.3/2.4 text frames; reject truncated tag envelopes."""
    with path.open('rb') as stream:
        header = stream.read(10)
        if header[:3] != b'ID3':
            return {}, []
        if len(header) < 10 or any(v & 128 for v in header[6:10]):
            raise ValueError('ส่วนหัว ID3 ไม่สมบูรณ์')
        size = sum(v << (7*(3-i)) for i,v in enumerate(header[6:10]))
        if size > 4*1024*1024 or size + 10 >= path.stat().st_size:
            raise ValueError('ขนาด ID3 ไม่ถูกต้องหรือไม่มีข้อมูลเสียงตามหลัง')
        raw = stream.read(size)
    if header[3] not in (3,4) or header[5] != 0:
        return {}, ['ID3 รุ่นหรือ flags นี้ยังไม่รองรับการอ่านแท็ก ใช้ข้อมูล LRC/ชื่อไฟล์แทน']
    result, offset = {}, 0
    while offset + 10 <= len(raw) and raw[offset]:
        name, length_raw = raw[offset:offset+4], raw[offset+4:offset+8]
        if header[3] == 4 and any(v & 128 for v in length_raw):
            raise ValueError('ขนาดเฟรม ID3 ไม่ถูกต้อง')
        length = sum(v << (7*(3-i)) for i,v in enumerate(length_raw)) if header[3] == 4 else int.from_bytes(length_raw,'big')
        end = offset + 10 + length
        if end > len(raw) or not length:
            raise ValueError('เฟรม ID3 ถูกตัด')
        payload = raw[offset+10:end]
        if name in (b'TIT2', b'TPE1') and raw[offset+8:offset+10] == b'\0\0':
            encodings = {0:'cp874', 1:'utf-16', 2:'utf-16-be', 3:'utf-8'}
            if payload[0] in encodings:
                try:
                    result['title' if name == b'TIT2' else 'artist'] = payload[1:].decode(encodings[payload[0]]).strip('\0 ')
                except UnicodeError:
                    pass
        offset = end
    return result, []


class Inspector:
    def __init__(self):
        # Cache directory listings only for this job, never between imports.
        self.listing = lru_cache(maxsize=64)(self._listing)

    @staticmethod
    def _listing(folder):
        try:
            with os.scandir(folder) as entries:
                return {entry.name.casefold():Path(entry.path) for entry in entries if entry.is_file() or entry.is_dir()}
        except OSError:
            return {}

    def sibling(self, path):
        return self.listing(path.parent).get(path.name.casefold(), path)

    def ncn_pair(self, midi):
        local = [self.sibling(midi.with_suffix(ext)) for ext in ('.lyr', '.cur')]
        # Flat Song/ and conventional Song/<initial>/ trees, any letter case.
        for parent in (midi.parent, midi.parent.parent):
            if parent.name.casefold() == 'song':
                relative = midi.relative_to(parent).with_suffix('')
                paired = []
                for folder, ext in (('Lyrics', '.lyr'), ('Cursor', '.cur')):
                    base = self.sibling(parent.parent / folder)
                    for part in relative.parent.parts:
                        base = self.sibling(base / part)
                    paired.append(self.sibling(base / (relative.name + ext)))
                return tuple(local[i] if local[i].is_file() else paired[i] for i in range(2))
        return tuple(local)

    @staticmethod
    def lyric_metadata(raw):
        rows = decode_text(ncn_text_bytes(raw)).replace('\x00', '').splitlines()
        if len(rows) < 4:
            raise ValueError('LYR มีส่วนหัวไม่ครบ 4 บรรทัด')
        return dict(title=rows[0].strip(), artist=rows[1].strip(), key_signature=rows[2].strip(),
                    first_lyric=' '.join(line.strip() for line in rows[4:] if line.strip())[:512])

    def inspect(self, item):
        from .library import SUPPORTED, MIDI_EXT, VIDEO_EXT, filename_info, canonical
        path = Path(item)
        ext = path.suffix.lower()
        if ext not in SUPPORTED:
            raise ValueError('ยังไม่รองรับรูปแบบ ' + ext)
        if not path.is_file():
            raise ValueError('ไม่พบไฟล์เพลง')
        if getattr(self,'capture_for_quality',False):self.last_quality=None
        code, title, artist = filename_info(path)
        code = code or (path.stem if re.fullmatch(r'[A-Za-z]*[0-9]+', path.stem) else '')
        record = dict(path=canonical(path), code=code, title=title, artist=artist,
                      kind='MIDI' if ext in MIDI_EXT else 'VIDEO' if ext in VIDEO_EXT else 'AUDIO',
                      format=ext[1:].upper(), playable=1)
        warnings, rich = [], set()
        def metadata(values):
            for key, value in values.items():
                if str(value).strip():
                    record[key] = value
                    rich.add(key)
        if ext in MIDI_EXT:
            data = bounded(path, 64 * 1024 * 1024)
            assets = unpack_emk(data) if ext == '.emk' else {}
            parser=parse_midi
            if getattr(self,'capture_for_quality',False):
                from .midi_structure import parse_structure
                parser=parse_structure
            song=parser(assets.get('MIDI_DATA',data),legacy=True)
            if getattr(self,'capture_for_quality',False):self.last_quality=dict(song=song,assets=assets,ncn_lyrics=None,ncn_error=None)
            metadata({'title': song.title, 'artist': song.artist, 'bpm': round(song.initial_bpm, 2),
                      'key_signature':song.key_signature, 'first_lyric': ' '.join(line.text for line in song.lyrics.lines)[:512]})
            raw, cursor = assets.get('LYRIC_DATA'), assets.get('CURSOR_DATA', assets.get('CUR_DATA'))
            if ext != '.emk':
                lyr, cur = self.ncn_pair(path)
                if lyr.is_file():
                    try:
                        raw = bounded(lyr, 1024 * 1024)
                    except (ValueError, OSError) as error:
                        warnings.append(str(error))
                if cur.is_file():
                    try:
                        cursor = bounded(cur, 2 * 1024 * 1024)
                    except (ValueError, OSError) as error:
                        warnings.append(str(error))
                if raw is not None or data[:4] == b'NCN1':
                    record['format'] = 'NCN24'
            if raw is not None:
                try:
                    metadata(self.lyric_metadata(raw))
                    if cursor is not None:
                        from .legacy import parse_ncn_lyrics
                        parser=parse_ncn_lyrics
                        if getattr(self,'capture_for_quality',False):
                            from .ncn_structure import validate_ncn
                            parser=validate_ncn
                        lyrics=parser(raw,cursor,song)
                        warnings.extend(getattr(lyrics, 'warnings', []))
                        if getattr(self,'capture_for_quality',False):self.last_quality['ncn_lyrics']=lyrics
                    else:
                        warnings.append('ไม่มี CUR: อ่านข้อมูลเพลงได้ แต่ยังไม่มีเวลาป้ายเนื้อร้อง NCN')
                except (ValueError, OSError) as error:
                    warnings.append(str(error))
                    if getattr(self,'capture_for_quality',False):self.last_quality['ncn_error']=str(error)
            elif ext == '.emk' or record['format'] == 'NCN24':
                warnings.append('ไม่มีข้อมูลเนื้อร้อง LYR')
        else:
            with path.open('rb') as stream:
                head = stream.read(4096)
            asf = bytes.fromhex('3026b2758e66cf11a6d900aa0062ce6c')
            matches = {
                '.wav': head[:4] == b'RIFF' and head[8:12] == b'WAVE',
                '.avi': head[:4] == b'RIFF' and head[8:12] == b'AVI ',
                '.mp3': head[:3] == b'ID3' or any(head[i] == 255 and head[i+1] & 224 == 224 and head[i+1] & 6 != 0 and head[i+2] >> 4 not in (0,15) for i in range(min(1024, len(head)-3))),
                '.wma': head.startswith(asf), '.wmv': head.startswith(asf),
                '.mp4': head[4:8] == b'ftyp', '.mov': head[4:8] in (b'ftyp', b'moov', b'mdat', b'wide'),
                '.mkv': head.startswith(bytes.fromhex('1a45dfa3')),
                '.mpg': head.startswith((b'\x00\x00\x01\xba', b'\x00\x00\x01\xb3')),
                '.mpeg': head.startswith((b'\x00\x00\x01\xba', b'\x00\x00\x01\xb3')),
            }
            if not matches.get(ext):
                raise ValueError('ส่วนหัวไฟล์ไม่ตรงกับนามสกุล ' + ext)
            if ext == '.wav':
                # wave verifies the RIFF fmt/data structure for PCM supported here.
                try:
                    with wave.open(str(path), 'rb') as audio:
                        if not audio.getnframes():
                            raise ValueError('WAV ไม่มีข้อมูลเสียง')
                except wave.Error as error:
                    raise ValueError('โครงสร้าง WAV เสียหายหรือ codec ยังไม่รองรับ: ' + str(error)) from error
            if ext == '.mp3':
                tagged, notes = id3_metadata(path)
                warnings.extend(notes)
                with path.open('rb') as stream:
                    stream.seek(max(0, path.stat().st_size - 128))
                    tag = stream.read(128)
                if tag[:3] == b'TAG' and len(tag) == 128:
                    metadata(dict(title=decode_text(tag[3:33].rstrip(b'\x00 ')), artist=decode_text(tag[33:63].rstrip(b'\x00 '))))
                metadata(tagged)
            warnings.append('ตรวจส่วนหัวคอนเทนเนอร์แล้ว; ต้องทดสอบตัวถอดรหัสบน Windows ขณะเล่น')
        lrc = self.sibling(path.with_suffix('.lrc'))
        if lrc.is_file():
            try:
                text = decode_text(bounded(lrc, 1024 * 1024))
                tags = dict((k.lower(), v.strip()) for k,v in re.findall(r'\[(ti|ar|key):([^\]\r\n]*)\]', text, re.I))
                metadata({'title': tags.get('ti', ''), 'artist': tags.get('ar', ''), 'key_signature':tags.get('key',''),
                          'first_lyric': ' '.join(line.text for line in parse_lrc(text).lines)[:512]})
            except (ValueError, OSError) as error:
                warnings.append(str(error))
        if 'title' not in rich and title == path.stem:
            warnings.append('ไม่พบชื่อเพลงในข้อมูลต้นทาง ใช้ชื่อไฟล์ชั่วคราว')
        record['_rich'] = rich
        return record, warnings
