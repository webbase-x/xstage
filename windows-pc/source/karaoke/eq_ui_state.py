from .song_eq import remembered

def status(state,settings,song,supported,applied):
    if song and not supported:return 'เพลงนี้ไม่รองรับ EQ • ใช้ MIDI/SoundFont หรือ WAV/MP3 ผ่าน BASS'
    if song and not applied:return 'ยังไม่ได้ใช้ EQ กับเพลงนี้ • กดใช้ค่าเพื่อลองอีกครั้ง'
    if song:
        saved=remembered(settings,song)
        prefix='BYPASS • ' if state['bypass'] else 'EQ กำลังทำงาน • '
        if saved==state:return prefix+'★ บันทึกประจำเพลงแล้ว'
        return prefix+'ยังไม่บันทึกประจำเพลง • กดจำ EQ เพลงนี้'
    return 'EQ กลางสำหรับเพลงที่ไม่มีค่าประจำเพลง • มิเตอร์: เสียงรวม Windows'

def clamp_rack(rect,area):
    x,y,w,h=rect;l,t,r,b=area
    w=min(w,max(1,r-l));h=min(h,max(1,b-t))
    return max(l,min(x,r-w)),max(t,min(y,b-h)),w,h


def resize_size(desired, available, required_height):
    """Keep controls and a usable meter area, bounded by the current display."""
    aw,ah=(max(1,int(v)) for v in available)
    return (min(aw,max(760,int(desired[0]))),
            min(ah,max(340,int(required_height),int(desired[1]))))
