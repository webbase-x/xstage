"""X-Stage standalone offline karaoke Web Asset Generator.

Read source MIDI/NCN bundles without modifying them. Export local M4A/AAC,
word-timed lyrics JSON and an atomic database.json. This module does NOT
upload content to Google Drive and never needs Google credentials.

Usage: python -m karaoke.offline_generator --input /songs --soundfont /GM.sf2 --output /public
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import multiprocessing
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .ingest import Inspector
from .smf import load_midi
from .web_assets import BatchRenderer, init_render_worker, render_worker_song, signature, file_hash
from .windows_process import silent_subprocess_options

SCHEMA_VERSION = 1
SUPPORTED = {'.mid', '.kar'}


@dataclass
class Job:
    code: str
    song: dict
    parts: dict
    origin: str
    filename: str
    bucket: str


def atomic_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # The random temporary name protects concurrent converter invocations from
    # overwriting each other's half-written temp file. Main process writes DB.
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.xstage-', suffix='.partial',
                                     delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path, value):
    atomic_bytes(path, json.dumps(value, ensure_ascii=False, sort_keys=True,
                                 separators=(',', ':')).encode('utf-8'))


def metadata_map(path):
    if not path:
        return {}
    path = Path(path)
    if path.suffix.lower() == '.csv':
        with path.open('r', encoding='utf-8-sig', newline='') as stream:
            items = list(csv.DictReader(stream))
    elif path.suffix.lower() == '.dbf':
        from .legacy import dbf_records
        items = list(dbf_records(path))
    elif path.suffix.lower() == '.json':
        items = json.loads(path.read_text(encoding='utf-8-sig'))
        if isinstance(items, dict):
            items = [dict(row, code=code) for code, row in items.items()]
    else:
        raise ValueError('Metadata ต้องเป็น CSV, JSON หรือ SONG.DBF')
    if not isinstance(items, list):
        raise ValueError('Metadata ต้องเป็นรายการเพลง')
    result = {}
    for row in items:
        if not isinstance(row, dict):
            raise ValueError('แถว Metadata ไม่ถูกต้อง')
        lower = {str(k).lower(): v for k, v in row.items()}
        code = str(lower.get('code', '')).strip()
        if code:
            result[code] = {'title': str(lower.get('title') or '').strip(),
                            'artist': str(lower.get('artist') or '').strip()}
    return result


def discover(root, *, output=None, cache=None, metadata=None):
    """Discover NCN triplets in flat or Song/Lyrics/Cursor folder layouts."""
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Input ต้องเป็นโฟลเดอร์')
    exclusions = [Path(x).resolve() for x in (output, cache) if x]
    inspector = Inspector()
    extra = metadata or {}
    prepared, rejected = [], []
    for midi_path in sorted((p for p in root.rglob('*') if p.is_file() and
                             p.suffix.lower() in SUPPORTED), key=lambda x: str(x).casefold()):
        path = midi_path.resolve()
        if any(path.is_relative_to(x) for x in exclusions):
            continue
        code = path.stem
        rel = str(path.relative_to(root)).replace('\\', '/')
        if not code or len(code) > 64 or any(x not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for x in code):
            rejected.append((code, rel, 'รหัสเพลงต้องเป็น A-Z, 0-9, _ หรือ - และยาวไม่เกิน 64 ตัว'))
            continue
        lyr, cur = inspector.ncn_pair(path)
        try:
            if lyr.is_file() != cur.is_file():
                raise ValueError('ชุด NCN ไม่ครบ: ต้องมีทั้ง LYR และ CUR')
            parts = {'media': path}
            title, artist = '', ''
            if lyr.is_file():
                parts['lyrics'], parts['cursor'] = lyr, cur
                info = inspector.lyric_metadata(lyr.read_bytes())
                title, artist = info.get('title') or '', info.get('artist') or ''
            # MIDI metadata is fallback for normal MID/KAR files; no fake title.
            if not title or not artist:
                midi = load_midi(path)
                title = title or midi.title or ''
                artist = artist or midi.artist or ''
            override = extra.get(code) or {}
            title = override.get('title') or title or code
            artist = override.get('artist') or artist
            prepared.append((code, {'id': len(prepared) + 1, 'code': code,
                                    'title': title, 'artist': artist,
                                    'format': 'NCN' if 'cursor' in parts else 'MIDI'},
                             parts, rel))
        except (OSError, ValueError, UnicodeError, EOFError) as exc:
            rejected.append((code, rel, str(exc)))
    # Preserve the requested filename for unique codes; disambiguate code
    # collisions deterministically without overwriting either song.
    counts = {}
    for code, *_ in prepared:
        counts[code.casefold()] = counts.get(code.casefold(), 0) + 1
    jobs = []
    for code, song, parts, rel in prepared:
        stem = code if counts[code.casefold()] == 1 else code + '-' + hashlib.sha256(rel.encode('utf-8')).hexdigest()[:12]
        jobs.append(Job(code, song, parts, rel, stem, code[0].upper()))
    return jobs, rejected


def _check_aac(path, ffprobe):
    """Require a genuinely decodable AAC stream, not just an M4A extension."""
    result = subprocess.run([str(ffprobe), '-v', 'error', '-select_streams', 'a:0',
                             '-show_entries', 'stream=codec_name',
                             '-of', 'default=noprint_wrappers=1:nokey=1', str(path)],
                            capture_output=True, text=True, timeout=45,
                            **silent_subprocess_options())
    if result.returncode or result.stdout.strip() != 'aac':
        raise ValueError('M4A ไม่ผ่านการตรวจ AAC: ' + result.stderr.strip()[-500:])


def _ffprobe_path(ffmpeg):
    location = Path(str(ffmpeg))
    probe = location.with_name('ffprobe.exe' if os.name == 'nt' else 'ffprobe')
    if location.parent != Path('.') and probe.is_file():
        return probe
    tool = shutil.which('ffprobe')
    if not tool:
        raise FileNotFoundError('ต้องติดตั้ง ffprobe จาก FFmpeg เพื่อยืนยันคุณภาพ M4A')
    return tool


def _atomic_copy(source, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.xstage-copy-',
                                     suffix='.partial', delete=False) as stream:
        temp = Path(stream.name)
    try:
        shutil.copyfile(source, temp)
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)


def _ram_bytes():
    if os.name == 'nt':
        import ctypes
        class MemoryStatus(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('memory_load', ctypes.c_ulong),
                        ('total_phys', ctypes.c_ulonglong), ('avail_phys', ctypes.c_ulonglong),
                        ('total_page', ctypes.c_ulonglong), ('avail_page', ctypes.c_ulonglong),
                        ('total_virtual', ctypes.c_ulonglong), ('avail_virtual', ctypes.c_ulonglong),
                        ('avail_ext', ctypes.c_ulonglong)]
        info = MemoryStatus();info.length = ctypes.sizeof(info)
        return int(info.avail_phys) if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(info)) else None
    try:
        return os.sysconf('SC_AVPHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
    except (AttributeError, ValueError, OSError):
        return None


def choose_workers(requested, soundfont):
    if requested != 'auto':
        count = int(requested)
        if not 1 <= count <= 16:
            raise ValueError('--workers ต้องอยู่ระหว่าง 1 ถึง 16')
        return count
    # Each Windows spawned process loads its OWN SF2. Never pass native handles
    # across processes. Be conservative when RAM is unknown or insufficient.
    ram = _ram_bytes()
    if ram is None:
        return 1
    font = Path(soundfont).stat().st_size
    per_worker = max(768 * 1024**2, font * 3 + 256 * 1024**2)
    return max(1, min(4, max(1, (os.cpu_count() or 2) // 2), int(ram * .6 // per_worker)))


def _status(done, total, code, status, *, bar=None, callback=None):
    if callback:
        callback(done, total, code, status)
    if bar:
        bar.update(1)
        bar.set_postfix_str(f'{status} {code}', refresh=False)
    elif not callback:
        print(f'\rX-Stage Web Assets: {done}/{total} ({100*done/max(1,total):.1f}%) [{status}] {code[:20]:20}',
              end='\n' if done == total else '', flush=True)


def convert_directory(source, soundfont, output, *, metadata=None, native=None, ffmpeg='ffmpeg',
                      workers=1, cache=None, error_log=None, renderer_factory=None,
                      validate_audio=True, callback=None, show_progress=True):
    """Render a folder, reuse matching local outputs and atomically publish DB.

    renderer_factory may be injected for isolated tests, but production always
    uses BASSMIDI. No Google Drive credentials, uploads or deletions are involved.
    """
    source, soundfont, output = Path(source).resolve(), Path(soundfont).resolve(), Path(output).resolve()
    if not source.is_dir() or not soundfont.is_file():
        raise ValueError('ไม่พบโฟลเดอร์เพลงหรือ SoundFont ที่ระบุ')
    cache = Path(cache).resolve() if cache else output.parent / '.xstage-web-cache'
    error_log = Path(error_log).resolve() if error_log else output.parent / 'xstage-web-errors.log'
    state_path = output.parent / '.xstage-generator-state.json'
    output.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    if validate_audio:
        ffprobe = _ffprobe_path(ffmpeg)
    else:
        ffprobe = None
    if renderer_factory is None:
        from .soundfont import inspect_font
        inspect_font(soundfont)
        if not native:
            native = Path(__file__).resolve().parents[1] / 'native' / 'x64'
        if not Path(native).is_dir():
            raise ValueError('ไม่พบโฟลเดอร์ BASS native DLL')
        if not shutil.which(str(ffmpeg)) and not Path(ffmpeg).is_file():
            raise FileNotFoundError('ไม่พบ FFmpeg กรุณาติดตั้ง ffmpeg.exe และ ffprobe.exe')
    workers = choose_workers(workers, soundfont)
    extra = metadata_map(metadata)
    jobs, rejected = discover(source, output=output, cache=cache, metadata=extra)
    try:
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if not isinstance(state, dict) or state.get('schemaVersion') != SCHEMA_VERSION:
            state = {}
    except (OSError, ValueError):
        state = {}
    receipts = state.get('songs', {}) if isinstance(state.get('songs'), dict) else {}
    active = {}
    pending = []
    failures = list(rejected)
    summary = {'total': len(jobs) + len(rejected), 'processed': 0, 'success': 0,
               'skipped_unchanged': 0, 'failed': 0, 'workers': workers, 'catalog': str(output/'database.json')}
    bar = None
    if show_progress and not callback:
        try:
            from tqdm import tqdm
            bar = tqdm(total=summary['total'], unit='song', desc='X-Stage Web Assets')
        except ImportError:
            pass
    def progress(code, status):
        summary['processed'] += 1
        _status(summary['processed'], summary['total'], code, status,
                bar=bar, callback=callback)
    def complete(job, digest, cached_audio, cached_lyrics, duration):
        out_audio = output/'audio'/job.bucket/(job.filename+'.m4a')
        out_lyrics = output/'lyrics'/job.bucket/(job.filename+'.json')
        doc = json.loads(Path(cached_lyrics).read_text(encoding='utf-8'))
        if doc.get('schemaVersion') != SCHEMA_VERSION or not isinstance(doc.get('lines'), list):
            raise ValueError('Lyrics JSON มีโครงสร้างไม่ถูกต้อง')
        if doc.get('id') != job.code:
            raise ValueError('Lyrics ID ไม่ตรงกับรหัสเพลง')
        if Path(cached_audio).stat().st_size <= 256:
            raise ValueError('ไฟล์ M4A เล็กผิดปกติ')
        if validate_audio:
            _check_aac(cached_audio, ffprobe)
        doc['title'], doc['artist'] = job.song['title'], job.song['artist']
        lyric_data = json.dumps(doc, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        # Copy through a temporary file; database is published only after both
        # files exist and their checksums are verified on disk.
        if not out_audio.is_file() or file_hash(out_audio) != file_hash(cached_audio):
            _atomic_copy(cached_audio, out_audio)
        if not out_lyrics.is_file() or out_lyrics.read_bytes() != lyric_data:
            atomic_bytes(out_lyrics, lyric_data)
        audio_hash, lyric_hash = file_hash(out_audio), file_hash(out_lyrics)
        if audio_hash != file_hash(cached_audio) or lyric_hash != hashlib.sha256(lyric_data).hexdigest():
            raise IOError('ไฟล์ที่คัดลอกไม่ผ่าน SHA-256')
        audio_rel = out_audio.relative_to(output).as_posix()
        lyric_rel = out_lyrics.relative_to(output).as_posix()
        row = {'webSongId': job.filename, 'id': job.code, 'code': job.code,
               'title': job.song['title'], 'artist': job.song['artist'], 'type': job.song['format'],
               'duration': float(duration), 'sourceSignature': digest,
               'audio': {'path':audio_rel, 'sha256':audio_hash, 'size':out_audio.stat().st_size,
                         'mimeType':'audio/mp4'},
               'lyrics': {'path':lyric_rel, 'sha256':lyric_hash, 'schemaVersion':SCHEMA_VERSION}}
        receipts[job.origin] = {'signature':digest, 'song':row}
        atomic_json(state_path, {'schemaVersion':SCHEMA_VERSION, 'songs':receipts})
        active[job.origin] = row
        summary['success'] += 1
    try:
        for bad_code, bad_origin, _ in rejected:
            progress(str(bad_code), 'skip')
        for job in jobs:
            try:
                digest = signature(job.parts, soundfont, {'soundfont': str(soundfont)})
                old = receipts.get(job.origin, {})
                old_row = old.get('song') or {}
                if (old.get('signature') == digest and old_row.get('title') == job.song['title'] and
                    old_row.get('artist') == job.song['artist'] and
                    old_row.get('webSongId') == job.filename):
                    audio = output / (old_row.get('audio') or {}).get('path', '')
                    lyric = output / (old_row.get('lyrics') or {}).get('path', '')
                    if (audio.is_file() and lyric.is_file() and
                        file_hash(audio) == (old_row.get('audio') or {}).get('sha256') and
                        file_hash(lyric) == (old_row.get('lyrics') or {}).get('sha256')):
                        active[job.origin] = old_row
                        summary['success'] += 1
                        summary['skipped_unchanged'] += 1
                        progress(job.code, 'unchanged')
                        continue
                pending.append(job)
            except Exception as exc:
                failures.append((job.code, job.origin, str(exc)))
                progress(job.code, 'error')
        if renderer_factory is not None or workers == 1:
            # Deterministic mock renderer in tests; BASS holds one SF2 per batch.
            factory = renderer_factory or BatchRenderer
            with factory(native, {'soundfont':str(soundfont)}, soundfont, cache, ffmpeg=ffmpeg) as renderer:
                for job in pending:
                    try:
                        complete(job, *renderer.build(job.song, job.parts))
                        progress(job.code, 'done')
                    except Exception as exc:
                        failures.append((job.code, job.origin, str(exc)))
                        progress(job.code, 'error')
        else:
            ctx = multiprocessing.get_context('spawn')
            with ProcessPoolExecutor(max_workers=workers, mp_context=ctx,
                                     initializer=init_render_worker,
                                     initargs=(native, {'soundfont':str(soundfont)}, soundfont,
                                               cache, ffmpeg)) as executor:
                iterator = iter(pending)
                ongoing = {}
                def schedule():
                    try:
                        job = next(iterator)
                    except StopIteration:
                        return False
                    ongoing[executor.submit(render_worker_song, job.song, job.parts)] = job
                    return True
                for _ in range(min(len(pending), workers * 2)):
                    schedule()
                while ongoing:
                    finished, _ = wait(ongoing, return_when=FIRST_COMPLETED)
                    for future in finished:
                        job = ongoing.pop(future)
                        try:
                            complete(job, *future.result())
                            progress(job.code, 'done')
                        except Exception as exc:
                            failures.append((job.code, job.origin, str(exc)))
                            progress(job.code, 'error')
                        schedule()
        if failures:
            error_log.parent.mkdir(parents=True, exist_ok=True)
            with error_log.open('a', encoding='utf-8') as stream:
                stream.write('# X-Stage Web Assets '+datetime.now(timezone.utc).isoformat()+'\n')
                for code, origin, reason in failures:
                    stream.write(f'{code}\t{origin}\t{str(reason).replace(chr(10)," ")[:3000]}\n')
        # Commit only after all current jobs finish; no failed item is published.
        catalog = {'schemaVersion': SCHEMA_VERSION,
                   'generatedAt': datetime.now(timezone.utc).isoformat(),
                   'totalSongs': len(active),
                   'songs': sorted(active.values(), key=lambda v: (v['code'],v['webSongId']))}
        atomic_json(output/'database.json', catalog)
        summary['failed'] = len(failures)
        summary['error_log'] = str(error_log) if failures else None
        return summary
    finally:
        if bar:
            bar.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description='X-Stage Offline NCN/MIDI to M4A + Lyrics JSON')
    parser.add_argument('--input', required=True, help='โฟลเดอร์ MID/LYR/CUR')
    parser.add_argument('--soundfont', required=True, help='SF2 เสียงสำหรับ BASSMIDI')
    parser.add_argument('--output', default='public', help='โฟลเดอร์ปลายทาง เช่น public/')
    parser.add_argument('--metadata', help='CSV, JSON หรือ SONG.DBF สำหรับชื่อเพลง/ศิลปิน')
    parser.add_argument('--native', help='โฟลเดอร์ native/x64 (Windows DLL)')
    parser.add_argument('--ffmpeg', default='ffmpeg', help='ไฟล์ ffmpeg.exe หรือคำสั่ง ffmpeg ใน PATH')
    parser.add_argument('--workers', default='auto', help='auto หรือ 1-16 (SF2 โหลดแยกต่อ Worker)')
    parser.add_argument('--cache', help='โฟลเดอร์เก็บผลเรนเดอร์ชั่วคราว/ใช้ซ้ำ')
    args = parser.parse_args(argv)
    try:
        result = convert_directory(args.input, args.soundfont, args.output,
                                   metadata=args.metadata, native=args.native,
                                   ffmpeg=args.ffmpeg, workers=args.workers,
                                   cache=args.cache)
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, 'ERROR: '+str(error)+'\n')
    print('\nCreated '+result['catalog']+'\n'+
          f"Success: {result['success']} / Failed: {result['failed']} / Unchanged: {result['skipped_unchanged']}")
    if result['error_log']:
        print('Error log: '+result['error_log'])
    return 0 if result['failed']==0 else 1


if __name__ == '__main__':
    sys.exit(main())
