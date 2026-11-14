"""Bounded structural MIDI validator for audit; never a playback event source.
Checks every event and payload while retaining only metadata/timing needed by quality.
"""
from dataclasses import dataclass
import struct
from .lyrics import Lyrics,decode_text,midi_lyrics
from .smf import MidiSong
from .inspection_errors import ReviewRequired


def vlq(data,pos,end):
    value=0
    for _ in range(4):
        if pos>=end:raise ValueError('MIDI ถูกตัดระหว่างอ่านเวลา/ความยาว')
        byte=data[pos];pos+=1;value=(value<<7)|(byte&127)
        if not byte&128:return value,pos
    raise ValueError('MIDI variable-length value เกิน 4 ไบต์')


@dataclass
class MidiStructure:
    duration:float
    division:int
    tempo_map:list
    lyrics:Lyrics
    title:str=''
    artist:str=''
    key_signature:str=''
    initial_bpm:float=120.
    has_notes:bool=False
    tick_seconds=MidiSong.tick_seconds
    seconds_tick=MidiSong.seconds_tick


def parse_structure(data,legacy=True):
    size=len(data)
    if size<14:raise ValueError('MIDI header ไม่สมบูรณ์')
    if data[:4] not in ((b'MThd',b'NCN1') if legacy else (b'MThd',)):raise ReviewRequired('ส่วนหัว MIDI เป็นรูปแบบที่ยังไม่รองรับ ต้องตรวจเพิ่ม')
    header=struct.unpack_from('>I',data,4)[0]
    if header<6 or 8+header>size:raise ValueError('MIDI header ไม่สมบูรณ์')
    fmt,tracks,division=struct.unpack_from('>HHH',data,8)
    if fmt not in (0,1) or not tracks or not division:raise ValueError('รองรับ Standard MIDI format 0/1 เท่านั้น')
    if fmt==0 and tracks!=1:raise ValueError('MIDI format 0 ต้องมี 1 track')
    if division&0x8000:
        code=(division>>8)-256
        if code not in (-24,-25,-29,-30) or not division&255:raise ValueError('MIDI SMPTE division ไม่ถูกต้อง')
    pos=8+header;sequence=0;final_tick=0;has_notes=False;metas=[];tempos=[]
    for _ in range(tracks):
        if pos+8>size or data[pos:pos+4]!=b'MTrk':raise ValueError('ไม่พบ MIDI track')
        length=struct.unpack_from('>I',data,pos+4)[0];pos+=8;end=pos+length
        if end>size:raise ValueError('ไฟล์ MIDI ไม่สมบูรณ์: track ถูกตัด')
        tick=0;running=None;ended=False
        while pos<end:
            delta,pos=vlq(data,pos,end);tick+=delta
            if pos>=end:raise ValueError('MIDI event ถูกตัด')
            status=data[pos]
            if status>=128:pos+=1
            else:
                if running is None:raise ValueError('MIDI running status ไม่มีสถานะก่อนหน้า')
                status=running
            if status==0xff:
                if not legacy:running=None
                if pos>=end:raise ValueError('MIDI meta event ถูกตัด')
                kind=data[pos];pos+=1;count,pos=vlq(data,pos,end)
                if pos+count>end:raise ValueError('MIDI meta payload ถูกตัด')
                payload=data[pos:pos+count];pos+=count
                if kind==0x51:
                    if count!=3 or int.from_bytes(payload,'big')==0:raise ValueError('MIDI tempo ไม่ถูกต้อง')
                    tempos.append((tick,sequence,int.from_bytes(payload,'big')))
                elif kind==0x59:
                    if count!=2 or not -7<=int.from_bytes(payload[:1],'big',signed=True)<=7 or payload[1] not in (0,1):raise ValueError('MIDI key signature ไม่ถูกต้อง')
                if kind in (1,3,5,6,0x59):metas.append((tick,sequence,kind,payload))
                if kind==0x2f:
                    if count!=0:raise ValueError('MIDI End of Track ไม่ถูกต้อง')
                    ended=True;final_tick=max(final_tick,tick);break
            elif status in (0xf0,0xf7):
                running=None;count,pos=vlq(data,pos,end)
                if pos+count>end:raise ValueError('MIDI SysEx ถูกตัด')
                pos+=count
            elif 0x80<=status<0xf0:
                running=status;count=1 if status&0xf0 in (0xc0,0xd0) else 2
                if pos+count>end:raise ValueError('MIDI channel event ถูกตัด')
                if data[pos]>127 or count==2 and data[pos+1]>127:raise ValueError('MIDI channel data ไม่ถูกต้อง')
                if status&0xf0==0x90 and data[pos+1]>0:has_notes=True
                pos+=count
            else:raise ValueError('MIDI event ไม่รองรับ: '+hex(status))
            final_tick=max(final_tick,tick);sequence+=1
        if not ended:raise ValueError('MIDI ไม่มี End of Track ชุดข้อมูลอาจถูกตัด')
        pos=end
    tempo_map=[(0,0.,500000)];previous=0;seconds=0.;tempo=500000
    for tick,_,following in sorted(tempos):
        if not division&0x8000:seconds+=(tick-previous)*tempo/division/1e6
        tempo_map.append((tick,seconds,following));previous=tick;tempo=following
    song=MidiStructure(0.,division,tempo_map,Lyrics(),has_notes=has_notes)
    song.duration=max(.05,song.tick_seconds(final_tick))
    if tempos:song.initial_bpm=60e6/sorted(tempos)[0][2]
    text_events=[];lyric_events=[]
    for tick,_,kind,payload in sorted(metas):
        if kind==0x59:
            if not song.key_signature:
                offset=int.from_bytes(payload[:1],'big',signed=True)+7
                notes=('Cb Gb Db Ab Eb Bb F C G D A E B F# C#' if payload[1]==0 else 'Ab Eb Bb F C G D A E B F# C# G# D# A#').split()
                song.key_signature=notes[offset]+('m' if payload[1] else '')
            continue
        text=decode_text(payload);when=song.tick_seconds(tick)
        if kind==5:lyric_events.append((when,text))
        elif kind==1:text_events.append((when,text))
        elif not song.title:song.title=text
    if not lyric_events and any(text.startswith(('@KMIDI','@K','/','\\')) for _,text in text_events):lyric_events=text_events
    headers=[text[2:].strip() for _,text in text_events if text.startswith('@T')]
    if headers:song.title=headers[0] or song.title;song.artist=headers[1] if len(headers)>1 else ''
    song.lyrics=midi_lyrics(lyric_events)
    return song
