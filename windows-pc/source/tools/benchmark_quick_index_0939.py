"""Synthetic quick/deep index timing, run on a disposable library only."""
from __future__ import annotations
import argparse, json, tempfile, time, wave
from pathlib import Path
from karaoke.fast_catalog import build_fast_catalog
from karaoke.library import SongLibrary
from karaoke.quick_catalog import pending_count


def run(n=1000, added=20):
    with tempfile.TemporaryDirectory(prefix='xstage-quick-bench-') as temporary:
        root=Path(temporary); songs=root/'Songs'; songs.mkdir(); lib=SongLibrary(root/'Data'/'songs.sqlite3')
        def make(i):
            path=songs/f'{i:07}.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setparams((1,2,8000,0,'NONE','not compressed'))
                wav.writeframes((i.to_bytes(4,'little',signed=False)+b'\0'*((i%7)+1))*2)
            path.with_suffix('.lrc').write_text(f'[ti:เพลง {i}]\n[ar:ศิลปิน {i}]\n[00:00.00]ทดสอบ',encoding='utf-8')
        for i in range(n):make(i)
        times={}
        for label, mode in [('quick_initial','quick'),('quick_noop','quick')]:
            t=time.perf_counter();result=build_fast_catalog(lib,songs,songs,mode)
            times[label]=round(time.perf_counter()-t,3)
        for i in range(n,n+added):make(i)
        t=time.perf_counter();result=build_fast_catalog(lib,songs,songs,'quick')
        times['quick_added']=round(time.perf_counter()-t,3)
        count=result.metrics['added']
        t=time.perf_counter();deep=build_fast_catalog(lib,songs,songs,'fast')
        times['deep_verify']=round(time.perf_counter()-t,3)
        return dict(items_initial=n,items_new=added,quick_added=count,pending_after_verify=pending_count(lib),
                    timings_seconds=times,notes='Synthetic tiny WAV+LRC. File creation excluded. Hardware-specific, not Windows proof.',
                    quick_metrics={k:v for k,v in result.metrics.items() if k in ('scanned','inventory_seconds','read_seconds','total_seconds','hashed','reports_deferred')},
                    deep_hashed=deep.metrics['hashed'])

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--songs',type=int,default=1000);p.add_argument('--added',type=int,default=20)
    a=p.parse_args();print(json.dumps(run(a.songs,a.added),ensure_ascii=False,indent=2))
