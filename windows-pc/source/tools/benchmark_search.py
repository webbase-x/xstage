"""Read-only real-catalog search benchmark; no cache-flush or disk-cold claim."""
import json
from pathlib import Path
import sqlite3
import statistics
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from karaoke.library import SearchReader, normalize


def benchmark(path):
    path = Path(path).resolve()
    start = time.perf_counter()
    reader = SearchReader(path)
    opened_ms = (time.perf_counter()-start)*1000
    start = time.perf_counter()
    count = reader.warm_up()
    warm_ms = (time.perf_counter()-start)*1000
    report = {'database_rows': count, 'connection_open_ms': round(opened_ms,2),
              'index_warm_ms': round(warm_ms,2), 'queries': [],
              'scope': 'Read-only; OS file cache is uncontrolled; not a disk-cold or hardware guarantee'}
    for query in ('ร', 'รั', 'รัก', 'รักน้องพร', '20120', 'รักน้องพร บาซู'):
        start = time.perf_counter()
        rows = reader.search(query, limit=200, playable_only=True)
        first = (time.perf_counter()-start)*1000
        timings = []
        for _ in range(5):
            start = time.perf_counter()
            reader.search(query, limit=200, playable_only=True)
            timings.append((time.perf_counter()-start)*1000)
        report['queries'].append({'query':query, 'first_ms':round(first,2),
            'cached_median_ms':round(statistics.median(timings),2),
            'top_codes':[row['code'] for row in rows[:5]], 'returned':len(rows)})
    assert reader.search('รักน้องพร', limit=1, playable_only=True)[0]['code'] == '20120'
    started = time.perf_counter()
    try:
        reader.search('ไม่พบคำค้นทดสอบตัวเก่า', cancelled=lambda: time.perf_counter()-started>.01)
    except Exception:
        pass
    assert reader.search('20120')[0]['code'] == '20120'
    reader.close()
    return report


if __name__ == '__main__':
    print(json.dumps(benchmark(sys.argv[1]), ensure_ascii=True, indent=2))
