"""Shared non-mutating validation for persisted player settings."""
import math


def validate_settings(value):
    if not isinstance(value,dict):raise ValueError('ไฟล์ตั้งค่าต้องเป็น JSON object')
    def finite(item):
        if isinstance(item,float) and not math.isfinite(item):raise ValueError('ค่าตั้งมีตัวเลขที่ไม่เป็น finite')
        if isinstance(item,dict):
            for child in item.values():finite(child)
        elif isinstance(item,list):
            for child in item:finite(child)
    finite(value)
    for name,low,high,integer in [('volume',0,100,False),('font_size',1,512,True),('stage_monitor',-1,64,True),('midi_device',-1,65535,True),('background_dim',0,1,False),('lyric_layout_version',0,1000000,True)]:
        if name not in value:continue
        item=value[name]
        if isinstance(item,bool):raise ValueError(f'ค่าตั้ง {name} ต้องเป็นตัวเลข')
        try:number=float(item)
        except (TypeError,ValueError,OverflowError) as error:raise ValueError(f'ค่าตั้ง {name} ต้องเป็นตัวเลข') from error
        if not math.isfinite(number) or not low<=number<=high or (integer and not number.is_integer()):
            raise ValueError(f'ค่าตั้ง {name} อยู่นอกช่วงที่รองรับ')
        if name=='lyric_layout_version' and type(item) is not int:raise ValueError('lyric_layout_version ต้องเป็นจำนวนเต็ม')
    for name in ('auto_next','main_fullscreen','transport_pinned','soundfont_follow_song'):
        if name in value:
            item=value[name]
            if not (type(item) is bool or type(item) is int and item in (0,1) or isinstance(item,str) and item.casefold() in ('true','false','yes','no','on','off','0','1')):
                raise ValueError(f'ค่าตั้ง {name} ต้องเป็น boolean')
    for name in ('graphic_eq','song_eq','soundfont_audio'):
        if name in value and not isinstance(value[name],dict):raise ValueError(f'ค่าตั้ง {name} ต้องเป็น object')
    if 'song_folders' in value:
        roots=value['song_folders']
        if not isinstance(roots,list):raise ValueError('song_folders ต้องเป็น list')
        kinds={'ทุกประเภท','NCN / MIDI / KAR','EMK','เพลงเสียง MP3 / WAV / WMA','วิดีโอ'}
        for row in roots:
            if not isinstance(row,dict) or not isinstance(row.get('path'),str) or not row['path'].strip() or any(c in row['path'] for c in ('\0','\r','\n')):raise ValueError('ตำแหน่งแหล่งเพลงไม่ถูกต้อง')
            if 'type' in row and (not isinstance(row['type'],str) or row['type'] not in kinds):raise ValueError('ประเภทแหล่งเพลงไม่ถูกต้อง')
    if 'legacy_root' in value and not isinstance(value['legacy_root'],str):raise ValueError('legacy_root ต้องเป็นข้อความ')
    if 'song_locations_migrated' in value and type(value['song_locations_migrated']) is not bool:raise ValueError('song_locations_migrated ต้องเป็น boolean')
    return value
