"""Bounded, silent decoder-open probe in an owned child process."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from .library import SearchCancelled


def direct(path):
    from .playback import MediaPlayer
    player=MediaPlayer()
    try:
        video=Path(path).suffix.lower() in {'.avi','.mp4','.mkv','.mov','.mpg','.mpeg','.wmv'}
        player.load(path,video=video)
        result=dict(status='valid' if player.duration>0 else 'invalid',duration=player.duration)
        if video:
            try:
                player.command('window '+player.alias+' state hide')
                dimensions=[int(x) for x in player.command('where '+player.alias+' source').split()]
                if len(dimensions)!=4 or dimensions[2]<=0 or dimensions[3]<=0:return dict(status='review',reason='ตรวจขนาดภาพวิดีโอไม่ได้')
                result['dimensions']=dimensions
            except (OSError,ValueError):return dict(status='review',reason='ตัวถอดรหัสไม่ยืนยันภาพวิดีโอ')
        return result
    except (OSError,ValueError) as error:return dict(status='review',reason='ตัวถอดรหัสเปิดสื่อไม่ได้: '+str(error))
    finally:player.close()


def probe(path,cancelled=None,timeout=12):
    if os.name!='nt':return dict(status='review',reason='ต้องตรวจตัวถอดรหัสบน Windows')
    with tempfile.TemporaryDirectory(prefix='xstage-probe-') as directory:
        result=Path(directory)/'result.json'
        if getattr(sys,'frozen',False):command=[sys.executable,'--probe-media',str(path),'--probe-result',str(result)]
        else:command=[sys.executable,'-B',str(Path(__file__).resolve().parents[1]/'main.py'),'--probe-media',str(path),'--probe-result',str(result)]
        process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        start=time.monotonic()
        try:
            while process.poll() is None:
                if cancelled and cancelled.is_set():raise SearchCancelled()
                if time.monotonic()-start>timeout:return dict(status='review',reason='ตัวถอดรหัสตอบช้าเกินเวลา ยังไม่สรุปว่าไฟล์เสีย')
                time.sleep(.05)
            if process.returncode or not result.is_file():return dict(status='review',reason='ตัวตรวจสื่อไม่คืนผลที่ยืนยันได้')
            value=json.loads(result.read_text(encoding='utf-8'))
            if value.get('status') not in ('valid','invalid','review'):return dict(status='review',reason='ผลตัวตรวจสื่อผิดรูปแบบ')
            return value
        finally:
            if process.poll() is None:process.terminate()
            process.wait(timeout=5)


def main(path,result):
    value=direct(path)
    Path(result).write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    return 0
