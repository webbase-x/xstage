"""Versioned bounded backups; validate every curve before modifying settings."""
import copy
import json
from pathlib import Path
from .graphic_eq import validate
from .song_eq import key
FORMAT='xstage-song-eq'
MAX_BYTES=10*1024*1024
MAX_SONGS=10000

def decode(value):
    if not isinstance(value,dict) or value.get('format')!=FORMAT or value.get('version')!=1:raise ValueError('รูปแบบสำรอง EQ ไม่รองรับ')
    songs=value.get('songs')
    if not isinstance(songs,dict) or len(songs)>MAX_SONGS:raise ValueError('จำนวนรายการไม่ถูกต้อง')
    result={}
    for path,state in songs.items():
        if not isinstance(path,str) or not path.strip() or '\x00' in path or len(path)>32767:raise ValueError('ตำแหน่งไฟล์ไม่ถูกต้อง')
        identity=key({'path':path})
        if identity in result:raise ValueError('มีตำแหน่งไฟล์ซ้ำหลังปรับรูปแบบ')
        result[identity]=validate(state)
    return result

def encode(songs):
    value={'format':FORMAT,'version':1,'songs':copy.deepcopy(songs)}
    value['songs']=decode(value)
    if len(json.dumps(value,ensure_ascii=False,indent=2).encode('utf-8'))>MAX_BYTES:raise ValueError('ข้อมูลสำรองใหญ่เกิน 10 MB')
    return value

def load(path):
    with Path(path).open('rb') as stream:data=stream.read(MAX_BYTES+1)
    if len(data)>MAX_BYTES:raise ValueError('ไฟล์สำรองใหญ่เกิน 10 MB')
    return decode(json.loads(data.decode('utf-8-sig')))

def merge(existing,incoming,overwrite=False):
    result=copy.deepcopy(existing)
    for path,state in incoming.items():
        if overwrite or path not in result:result[path]=copy.deepcopy(state)
    return result
