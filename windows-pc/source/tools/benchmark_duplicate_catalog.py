"""Repeatable, self-contained synthetic identical-content song benchmark."""
import json, platform, sys, tempfile, time, wave
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from karaoke.fast_catalog import build_fast_catalog
from karaoke.library import SongLibrary

def run(songs=500):
    if not 1 <= songs <= 10000:
        raise ValueError('songs must be from 1 to 10000')
    with tempfile.TemporaryDirectory(prefix='xstage-duplicates-0935-') as t:
        root=Path(t);folder=root/'Songs';folder.mkdir()
        for i in range(songs):
            f=folder/f'{i:07}.wav'
            with wave.open(str(f),'wb') as wav:
                wav.setparams((1,2,8000,0,'NONE','not compressed'))
                wav.writeframes(b'\x00\x01'*100)
            f.with_suffix('.lrc').write_text('[ti:เพลงเดียวกัน]\n[ar:นักร้อง]\n[key:C]\n[00:00.00]ทดสอบ',encoding='utf8')
        lib=SongLibrary(root/'Data'/'songs.sqlite3')
        result={'version':'0.9.36','synthetic':True,'songs':songs,'data_type':'identical WAV+LRC',
                'platform':platform.platform(),'trials':[]}
        for label in ('first_build','second_build'):
            t0=time.perf_counter()
            data=build_fast_catalog(lib,folder,folder)
            result['trials'].append({'name':label,'seconds':round(time.perf_counter()-t0,3),
                                     'visible_count':lib.count(),'duplicates':data.metrics['duplicates'],
                                     'hashed':data.metrics['hashed'],
                                     'reports_reused':data.metrics['reports_reused']})
        return result

if __name__=='__main__':
    n=int(sys.argv[1]) if len(sys.argv)>1 else 500
    print(json.dumps(run(n),ensure_ascii=False,indent=2))
