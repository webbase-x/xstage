"""One completeness policy for pre-import and post-import review; no file mutations."""
import math
import ntpath
from pathlib import Path
import wave
from .library import MIDI_EXT,VIDEO_EXT,SUPPORTED,SearchCancelled,canonical
from .ingest import Inspector,bounded
from .lyrics import parse_lrc,decode_text
from .name_duplicates import identity,musical_key
from .inspection_errors import ReviewRequired

REVISION='quality-090-4'


def check_cancel(cancelled):
    if cancelled and cancelled.is_set():raise SearchCancelled()


def available_parts(path,inspector=None):
    inspector=inspector or Inspector();path=Path(path)
    parts={'media':path}
    if path.suffix.lower() in MIDI_EXT- {'.emk'}:
        for role,file in zip(('lyrics','cursor'),inspector.ncn_pair(path)):
            if file.is_file():parts[role]=file
    for ext in ('.lrc','.snf'):
        file=inspector.sibling(path.with_suffix(ext))
        if file.is_file():parts[ext[1:]]=file
    return parts


def assess(path,record=None,cancelled=None,inspector=None,probe=None,crosscheck_metadata=False):
    check_cancel(cancelled);path=Path(path);inspector=inspector or Inspector()
    def result(status,*reasons,**extra):return dict(status=status,reasons=list(reasons),policy=REVISION,**extra)
    try:
        if ':' in ntpath.splitdrive(str(path))[1]:return result('review','ตำแหน่งเป็น alternate data stream ต้องตรวจเพิ่ม')
        if path.suffix.lower() not in SUPPORTED:return result('review','รูปแบบนี้ยังไม่มีตัวตรวจความสมบูรณ์')
        if path.is_symlink() or any(getattr(p,'is_junction',lambda:False)() or p.is_symlink() for p in path.parents):return result('review','ไฟล์/โฟลเดอร์เป็นลิงก์ ต้องตรวจผู้ใช้ร่วมก่อน')
        if not path.exists():
            if not Path(path.anchor).exists():return result('review','ไดรฟ์ยังไม่พร้อมตรวจ')
            return result('invalid','ไม่พบไฟล์เพลง')
        file_size=path.stat().st_size
        if file_size==0:return result('invalid','ไฟล์เพลงว่าง')
        if path.suffix.lower() in MIDI_EXT and file_size>64*1024*1024:return result('review','MIDI/EMK ใหญ่เกินขอบเขตตัวตรวจ')
        inspector.capture_for_quality=True
        try:parsed,warnings=inspector.inspect(path);capsule=getattr(inspector,'last_quality',None)
        finally:inspector.capture_for_quality=False
        data=dict(parsed)
        if crosscheck_metadata and record and not record.get('user_edited'):
            rich=parsed.get('_rich',set())
            for field,label in (('title','ชื่อเพลง'),('artist','นักร้อง'),('key_signature','คีย์')):
                if field not in rich or not str(record.get(field,'')).strip() or not str(parsed.get(field,'')).strip():continue
                left=musical_key(record[field]) if field=='key_signature' else identity(record[field],'x','C')
                right=musical_key(parsed[field]) if field=='key_signature' else identity(parsed[field],'x','C')
                if left!=right:return result('review',label+' ในไฟล์กับคลังไม่ตรงกัน: '+str(parsed[field])+' / '+str(record[field]))
        if record:
            for key,value in record.items():
                if value not in ('',None) and not key.startswith('_'):data[key]=value
        duration=0.;lines=[];ext=path.suffix.lower();parts=available_parts(path,inspector)
        if ext in MIDI_EXT:
            from .smf import load_midi
            song=capsule['song'] if capsule else load_midi(path);duration=song.duration
            if not (song.has_notes if hasattr(song,'has_notes') else any(event.data[0]&0xf0==0x90 and len(event.data)>2 and event.data[2]>0 for event in song.events)):return result('invalid','ไม่มีโน้ตที่ส่งเสียงใน MIDI')
            lines=song.lyrics.lines
            if ext=='.emk':
                assets=capsule.get('assets',{}) if capsule else {}
                if not assets.get('LYRIC_DATA') or not assets.get('CURSOR_DATA',assets.get('CUR_DATA')):return result('invalid','EMK ไม่มี LYR/CUR ครบ')
                if capsule.get('ncn_error'):return result('invalid',capsule['ncn_error'])
                lyrics=capsule.get('ncn_lyrics')
                if lyrics is None:return result('invalid','EMK ไม่มีเวลาเนื้อร้องที่อ่านได้')
                if any('ไม่มีเวลา' in warning or 'เกินช่วง' in warning or 'ไม่ครบ' in warning for warning in getattr(lyrics,'warnings',[])):return result('invalid','เนื้อร้อง EMK จับคู่เวลาไม่ครบ')
                lines=lyrics.lines
            if ext!='.emk' and ('lyrics' in parts or 'cursor' in parts):
                if not {'lyrics','cursor'}<=parts.keys():return result('invalid','ชุด NCN ไม่ครบ LYR/CUR')
                from .legacy import parse_ncn_lyrics
                if capsule and capsule.get('ncn_error'):return result('invalid',capsule['ncn_error'])
                lyrics=capsule.get('ncn_lyrics') if capsule else None
                if lyrics is None:lyrics=parse_ncn_lyrics(bounded(parts['lyrics'],1024*1024),bounded(parts['cursor'],2*1024*1024),song)
                if any('ไม่มีเวลา' in warning or 'เกินช่วง' in warning or 'ไม่ครบ' in warning for warning in getattr(lyrics,'warnings',[])):return result('invalid','เนื้อร้อง NCN จับคู่เวลาไม่ครบ')
                lines=lyrics.lines
        elif ext=='.wav':
            with wave.open(str(path),'rb') as audio:
                expected=audio.getnframes()*audio.getnchannels()*audio.getsampwidth();read=0
                duration=audio.getnframes()/audio.getframerate()
                while True:
                    check_cancel(cancelled);block=audio.readframes(65536)
                    if not block:break
                    read+=len(block)
                if read!=expected:return result('invalid','ข้อมูลเสียง WAV ถูกตัด ไม่ครบตามส่วนหัว')
        else:
            if probe is None:
                from .media_probe import probe as decoder
            else:decoder=probe
            checked=decoder(path,cancelled)
            if checked.get('status')!='valid':return result(checked.get('status','review'),checked.get('reason','ยังยืนยันการเปิดสื่อไม่ได้'))
            duration=float(checked.get('duration',0))
        if 'lrc' in parts:
            lrc=parse_lrc(decode_text(bounded(parts['lrc'],1024*1024)))
            offset=lrc.offset_ms/1000
            if not math.isfinite(offset):return result('invalid','ค่า offset เนื้อร้องไม่ถูกต้อง')
            from .lyrics import LyricLine
            lines=[LyricLine(line.start-offset,line.text,[(when-offset,text) for when,text in line.words]) for line in lrc.lines]
        if not math.isfinite(duration) or duration<=0:return result('invalid','ระยะเวลาสื่อไม่ถูกต้อง')
        if ext not in VIDEO_EXT:
            usable=[line for line in lines if line.text.strip()]
            if not usable:return result('invalid','ไม่มีเนื้อร้องพร้อมเวลา')
            if any(not math.isfinite(line.start) or line.start< -2 or line.start>duration+2 for line in usable):return result('invalid','เวลาเนื้อร้องอยู่นอกเพลง')
        if ext not in VIDEO_EXT and any(not math.isfinite(when) or when< -2 or when>duration+2 for line in lines for when,text in line.words if text.strip()):return result('invalid','เวลารายคำอยู่นอกเพลง')
        if not str(data.get('title','')).strip() or data.get('title')==data.get('code') or not str(data.get('artist','')).strip():return result('review','ชื่อเพลง/นักร้องยังระบุไม่ครบ')
        if musical_key(data.get('key_signature')) is None:return result('review','ยังไม่ทราบคีย์เพลงที่ยืนยันได้')
        return result('valid',duration=duration,identity=identity(data['title'],data['artist'],data['key_signature']),metadata={k:data.get(k,'') for k in ('title','artist','key_signature')})
    except SearchCancelled:raise
    except ReviewRequired as error:return result('review',str(error))
    except FileNotFoundError:return result('invalid','ไม่พบไฟล์หรือส่วนประกอบเพลง')
    except (PermissionError,OSError) as error:return result('review','อ่านไฟล์ไม่ได้ ยังไม่สรุปว่าเสีย: '+str(error))
    except (ValueError,EOFError,wave.Error,OverflowError) as error:
        unsupported=any(word in str(error).lower() for word in ('codec','ไม่รองรับ','รองรับ standard midi format'))
        return result('review' if unsupported else 'invalid',str(error))
