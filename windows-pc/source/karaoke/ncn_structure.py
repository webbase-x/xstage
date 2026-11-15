"""NCN completeness without allocating word-paint objects for every byte."""
import array
import sys
from .legacy import ncn_body
from .lyrics import Lyrics,LyricLine


def validate_ncn(raw,cursor,song):
    if len(raw)>1024*1024 or len(cursor)>2*1024*1024:raise ValueError('LYR/CUR ใหญ่เกินขอบเขตที่รองรับ')
    if not song.division or song.division&0x8000:raise ValueError('NCN24 ต้องใช้ MIDI แบบ PPQ')
    body,removed=ncn_body(raw)
    if len(cursor)%2:
        if cursor[-1:]==b'\xff':cursor=cursor[:-1]
        else:raise ValueError('CUR มีข้อมูลไม่ครบหนึ่งค่าเวลา')
    values=array.array('H');values.frombytes(cursor)
    if sys.byteorder!='little':values.byteswap()
    if len(values)<len(body):raise ValueError('ข้อความ LYR มีเวลา CUR จับคู่ไม่ครบ')
    lines=[];text=bytearray();start=None;previous=0
    def flush():
        nonlocal text,start
        if text.strip():lines.append(LyricLine(song.tick_seconds(start*song.division/24),text.decode('cp874',errors='replace')))
        text=bytearray();start=None
    # Match legacy timing clamps while rejecting missing/out-of-range content.
    last_allowed=song.seconds_tick(song.duration+2)*24/song.division
    for byte,value in zip(body,values):
        if byte in (10,13):flush();continue
        if value==65535:continue
        value=max(value,previous);previous=value
        if value>last_allowed:raise ValueError('เวลา CUR อยู่นอกช่วงเพลง')
        if start is None:start=value
        text.append(byte)
    flush()
    if body and not lines:raise ValueError('ไม่พบข้อมูลเวลาเนื้อร้องที่จับคู่ได้')
    result=Lyrics(lines);result.warnings=[];result.removed_footer_lines=removed
    return result
