"""Read-only real-library verification; all generated data stays in temp."""
import json
import sys
import tempfile
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from karaoke.legacy import DEFAULT_LEGACY, import_catalog, ncn_lyrics
from karaoke.library import SongLibrary
from karaoke.smf import load_midi

def verify(include_catalog=True):
    results = {'source': str(DEFAULT_LEGACY), 'samples': [], 'errors': [], 'ncn_midi_read':0, 'ncn_attempts':0, 'emk_attempts':0, 'emk_midi_read':0, 'emk_lyrics_read':0, 'lyric_warnings':[]}
    root = DEFAULT_LEGACY/'Songs'/'MIDI'/'NCN'/'Song'
    paths = []
    for folder in root.iterdir():
        if folder.is_dir():
            files = list(folder.glob('*.mid'))
            if files:
                paths.extend(files[:2] + files[len(files)//2:len(files)//2+1])
    for file in paths[:80]:
        results['ncn_attempts']+=1
        try:
            song = load_midi(file)
            results['ncn_midi_read']+=1
            lyrics = ncn_lyrics(file, song)
            assert song.events and song.duration > 0
            assert lyrics and lyrics.lines
            results['samples'].append(dict(code=file.stem, duration=round(song.duration,3), lines=len(lyrics.lines), last_cue=round(lyrics.lines[-1].start,3)))
        except Exception as error:
            results['errors'].append({'file': str(file), 'error': str(error)})
    emk_results = []
    emk_root = DEFAULT_LEGACY/'Songs'/'MIDI'/'EMK'
    for folder in emk_root.iterdir():
        if not folder.is_dir():
            continue
        files = list(folder.glob('*.emk'))
        for file in (files[:1]+files[len(files)//2:len(files)//2+1]+files[-1:]):
            results['emk_attempts']+=1
            try:
                song=load_midi(file)
                assert song.events
                results['emk_midi_read']+=1
                if song.lyrics.lines:
                    results['emk_lyrics_read']+=1
                elif getattr(song,'lyric_warning',''):
                    results['lyric_warnings'].append({'file':str(file),'error':song.lyric_warning})
                emk_results.append({'code':file.stem,'seconds':round(song.duration,3),'lines':len(song.lyrics.lines)})
            except Exception as error:
                results['errors'].append({'file':str(file),'error':str(error)})
    results['emk_samples']=emk_results
    if not include_catalog:
        return results
    with tempfile.TemporaryDirectory() as temporary:
        library = SongLibrary(Path(temporary)/'catalog.sqlite3')
        started = time.perf_counter()
        def progress(count):
            if count % 20000 == 0:
                print(json.dumps({'progress': count}),flush=True)
        results['catalog'] = import_catalog(DEFAULT_LEGACY, library, progress=progress)
        results['import_seconds'] = round(time.perf_counter()-started,3)
        results['count'] = library.count()
        results['search'] = []
        for query in ['00001','ทำได้เพียง','ดวง','รัก','25 Hours']:
            started=time.perf_counter()
            rows=library.search(query,limit=60)
            results['search'].append({'query':query,'ms':round((time.perf_counter()-started)*1000,2),'returned':len(rows)})
        results['sqlite_bytes'] = library.path.stat().st_size
    return results

if __name__=='__main__':
    print(json.dumps(verify(),ensure_ascii=True,indent=2))
