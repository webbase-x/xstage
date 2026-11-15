"""Self-contained synthetic Fast Catalog benchmark; never touches real songs.

Usage: python tools/benchmark_fast_catalog.py --songs 1000
"""
import argparse
import json
import platform
import tempfile
import time
import wave
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from karaoke.fast_catalog import build_fast_catalog
from karaoke.library import SongLibrary


def run(songs):
    with tempfile.TemporaryDirectory(prefix='xstage-benchmark-0934-') as location:
        root = Path(location)
        folder = root/'Songs'
        folder.mkdir()
        for i in range(songs):
            media = folder / f'{i:07d}.wav'
            with wave.open(str(media), 'wb') as output:
                output.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
                output.writeframes((i % 256).to_bytes(1, 'little') * (64 + 2*i))
            media.with_suffix('.lrc').write_text(
                f'[ti:เพลง {i}]\n[ar:ศิลปิน {i}]\n[key:C]\n[00:00.00]ตัวอย่าง {i}', encoding='utf-8')
        library = SongLibrary(root/'Data'/'songs.sqlite3')
        result = dict(version='0.9.36', platform=platform.platform(), synthetic=True,
                      songs=songs, data_type='synthetic WAV + LRC, different bundle sizes', trials=[])
        for trial in ('first_build', 'second_build'):
            before=time.perf_counter()
            build=build_fast_catalog(library, folder, folder, 'fast')
            seconds=time.perf_counter()-before
            result['trials'].append(dict(name=trial, seconds=round(seconds,3),
                                         songs_per_second=round(songs/seconds,1),
                                         metrics={key:value for key,value in build.metrics.items() if key!='warnings'}))
        return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--songs',type=int,default=1000)
    args=parser.parse_args()
    if not 1<=args.songs<=10000:parser.error('songs must be between 1 and 10000')
    print(json.dumps(run(args.songs),ensure_ascii=False,indent=2))
