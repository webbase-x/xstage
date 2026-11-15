"""Illustrative local-only benchmark; not a Windows hardware qualification."""
import json
import tempfile
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from karaoke.library import QueueItem, SongLibrary, canonical
from karaoke.random_medley import build_preview


def main(total=20000):
    with tempfile.TemporaryDirectory() as base:
        folder = Path(base)
        db = SongLibrary(folder / 'songs.sqlite3')
        catalog = [dict(path=folder / f'{i:06d}.mid',title=f'เพลง {i}', artist='ทดสอบ',
                        key_signature='C', rhythm='ลูกทุ่ง', kind='midi',playable=1)
                   for i in range(total)]
        start=time.perf_counter()
        for offset in range(0,total,1000):
            db.upsert_catalog(catalog[offset:offset+1000])
        write_time=time.perf_counter()-start
        with db.connect() as cx:
            indexed = [(r['id'],r['path']) for r in cx.execute(
                'SELECT id,path FROM songs ORDER BY id LIMIT 5')]
        for _,path in indexed: Path(path).write_bytes(b'fake-midi-for-availability-check')
        now=datetime.now().astimezone().isoformat(timespec='seconds')
        history=[]
        for i in range(500):
            sid,path=indexed[i % len(indexed)]
            history.append({'time':now,'path':path,'title':'เพลง', 'artist':'ทดสอบ',
                            'status':'completed', 'item':asdict(QueueItem(sid))})
        history_file=folder / 'history.json'
        history_file.write_text(json.dumps(history,ensure_ascii=False),encoding='utf-8')
        start=time.perf_counter()
        result=build_preview(db.path,'popular',5,history_path=history_file)
        ranking_time=time.perf_counter()-start
        print(json.dumps({'catalog_songs':total,'history_rows':len(history),
              'catalog_build_seconds':round(write_time,3),'ranking_seconds':round(ranking_time,4),
              'ranked_songs':len(result.rows)},ensure_ascii=False))

if __name__=='__main__':main()
