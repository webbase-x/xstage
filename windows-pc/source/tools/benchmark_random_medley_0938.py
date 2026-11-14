"""Synthetic catalog benchmark only. Does not use the user's real song library."""
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
import json, random, tracemalloc
from karaoke.library import SongLibrary
from karaoke.random_medley import build_preview


def run(size):
    with TemporaryDirectory() as directory:
        root = Path(directory)
        library = SongLibrary(root/'songs.sqlite3')
        records = []
        for i in range(size):
            file = root/f'{i}.mid'
            file.write_bytes(b'test')
            records.append((str(file),f'{i:07d}',f'Song {i}',f'Artist {i}',
                            'midi',f'Song {i} Artist {i}','Rock'))
        with library.connect() as db:
            db.executemany('INSERT INTO songs(path,code,title,artist,kind,search,rhythm,playable)'
                           ' VALUES (?,?,?,?,?,?,?,1)', records)
        tracemalloc.start()
        start = perf_counter()
        preview = build_preview(library.path, 'library', 10, rng=random.Random(1234))
        seconds = round(perf_counter()-start,4)
        _now,peak=tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return dict(catalog_songs=size, requested=10, returned=len(preview.rows),
                    matched=preview.matched, elapsed_seconds=seconds,
                    peak_python_mb=round(peak/1024/1024,3))

if __name__=='__main__':
    output={'benchmark':'v0.9.38 bounded preview synthetic Linux; file creation excluded',
            'results':[run(n) for n in (1000,5000,20000)]}
    print(json.dumps(output,indent=2))
