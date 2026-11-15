"""Conservative static MIDI/SF2 coverage, not a report of actual rendered audio."""
from pathlib import Path
from .soundfont import inspect_font
from .font_mapping import extended_entries


def requirements(events):
    pending=[[0,0] for _ in range(16)]
    active=[(128 if ch==9 else 0,0,0) for ch in range(16)]
    found=set();sysex=False
    for event in events:
        data=event.data
        if not data:continue
        status=data[0]&0xf0;ch=data[0]&15
        if status==0xf0:sysex=True;continue
        if status==0xb0 and len(data)>=3 and data[1] in (0,32):pending[ch][data[1]==32]=data[2]
        elif status==0xc0 and len(data)>=2:active[ch]=(128 if ch==9 else pending[ch][0],pending[ch][1],data[1])
        elif status==0x90 and len(data)>=3 and data[2]:found.add((ch,*active[ch]))
    return sorted(found),sysex


def check_song(path,settings):
    from .smf import load_midi
    song=load_midi(Path(path));needed,sysex=requirements(song.events)
    fonts=settings['soundfont_audio']['fonts'];catalogs=[];warnings=[]
    for font in fonts:
        try:
            presets=inspect_font(font['path'])['presets']
            catalogs.append(None if presets is None else {(b,p):n for b,p,n in presets})
        except (OSError,ValueError) as error:
            catalogs.append(None);warnings.append(str(error))
    mapping={} if settings.get('soundfont_follow_song') else settings.get('instrument_fonts',{})
    mapping_error=False
    try:entries=extended_entries({'fonts':fonts},list(range(len(fonts))),mapping) if mapping else []
    except (OSError,ValueError) as error:entries=[];mapping_error=True;warnings.append('ตรวจการจับคู่ไม่ได้: '+str(error))
    rows=[]
    for ch,bank,lsb,program in needed:
        match=None
        if not lsb:
            for h,sp,sb,dp,db,dl in entries:
                if dp==program and db==bank and dl==lsb:
                    match=(h,(catalogs[h] or {}).get((sb,sp),'Preset ที่จับคู่'));break
            if match is None:
                for i,catalog in enumerate(catalogs):
                    if catalog is not None and (bank,program) in catalog:match=(i,catalog[(bank,program)]);break
        if lsb:
            status='ต้องตรวจเพิ่มเติม';name='มี Bank LSB • ไม่ยืนยันการเลือกเสียง';source=''
        elif match:
            status=('ตรวจไม่ครบ' if mapping_error or any(c is None for c in catalogs[:match[0]+1]) else ('พบตรง' if not mapping else 'พบตามชุด/การจับคู่'))
            source=Path(fonts[match[0]]['path']).name;name=match[1]
        else:
            fallback=next(((i,c[(0,program)]) for i,c in enumerate(catalogs) if c is not None and (0,program) in c),None)
            status='ตรวจไม่ครบ' if any(c is None for c in catalogs) else 'ไม่พบตรง'
            name=('มีเสียง Bank 0: '+fallback[1]+' (ยังไม่ยืนยันว่าใช้จริง)') if fallback and bank!=128 else 'อาจเงียบหรือใช้เสียงสำรอง'
            source=Path(fonts[fallback[0]]['path']).name if fallback and bank!=128 else ''
        rows.append((ch+1,bank,lsb,program,status,name,source))
    if sysex:warnings.append('เพลงมี SysEx • การเปลี่ยนโหมดเครื่องดนตรีเฉพาะผู้ผลิตไม่อยู่ในการตรวจนี้')
    warnings.append('ตรวจข้อมูลในไฟล์เท่านั้น ไม่รวม Mixer override, GS/XG พิเศษ หรือยืนยันเสียงสำรองที่ระบบเล่นจริง')
    return rows,warnings
