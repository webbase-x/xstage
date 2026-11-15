"""Offline M4A + timed-lyrics assets, separate from any Google Drive backup.

Only catalog-visible MIDI/NCN files are candidates. Originals are read-only.
The BASSMIDI synthesizer is reused for a batch of songs in a single worker;
no native SoundFont handle is ever transferred between processes.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from functools import lru_cache

from .smf import load_midi
from .legacy import ncn_lyrics
from .visible_sync import visible_song_plan
from .windows_process import silent_subprocess_options

SCHEMA = 1
RENDER_VERSION = 'xstage-web-0944-bass-f32-aac256'
SAMPLE_RATE = 48000
AUDIO_TAIL = 1.5


def file_hash(path, algorithm='sha256'):
    digest = hashlib.new(algorithm)
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


@lru_cache(maxsize=32)
def _font_hash_cached(path, device, inode, size, mtime_ns):
    # Within a batch, never re-read multi-gigabyte SF2 for every song.
    return file_hash(path)


def font_hash(path):
    file = Path(path).resolve()
    st = file.stat()
    return _font_hash_cached(str(file),st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)


def online_song_type(song):
    """Classify only formats supported by the existing MIDI/NCN renderer."""
    fmt = str(song.get('format') or '').lower()
    return 'NCN' if 'ncn' in fmt else 'MIDI'


def local_candidates(db_path, roots=None, *, song_types=None, progress=None):
    """Use exactly the same visibility rule as desktop search, no full-folder scan."""
    songs, files, rejected = visible_song_plan(db_path, roots, progress=progress)
    allowed = {'NCN', 'MIDI'} if song_types is None else set(song_types)
    if allowed - {'NCN', 'MIDI'}:
        raise ValueError('ประเภทเพลงที่เลือกไม่รองรับการแปลงในรุ่นนี้')
    candidates = []
    for song in songs:
        media = files[song['files']['media']]
        if media.suffix.lower() not in ('.mid', '.kar'):
            rejected.append((song['id'], 'Web renderer v0.9.44 รองรับ MIDI/NCN ก่อน'))
            continue
        if online_song_type(song) not in allowed:
            continue  # User filter is not a broken file and must not be reported as one.
        is_ncn = 'ncn' in str(song.get('format', '')).lower()
        if is_ncn and not {'media', 'lyrics', 'cursor'} <= set(song['files']):
            rejected.append((song['id'], 'NCN ไม่ครบชุด MID/LYR/CUR'))
            continue
        parts = {role: files[rel] for role, rel in song['files'].items()}
        candidates.append((song, parts))
    return candidates, rejected


def signature(parts, soundfont, settings=None, bitrate=256):
    """Content-based signature, not filename/mtime. Changing SF2 causes rerender."""
    from .soundfont import normalize_audio
    options = normalize_audio(settings or {})
    all_fonts = [(font_hash(row['path']),row['gain_db']) for row in options['fonts']]
    if not all_fonts:
        all_fonts = [(font_hash(soundfont), -6.0)]
    data = {'schema': SCHEMA, 'renderer': RENDER_VERSION, 'encoder': 'aac-lc', 'bitrate': int(bitrate),
            'soundfonts': all_fonts,
            'audio_settings': {**options, 'fonts': all_fonts},
            'instrument_fonts': (settings or {}).get('instrument_fonts', {}),
            'files': {role: file_hash(path) for role, path in sorted(parts.items())}}
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def lyrics_document(song, midi, timed, duration):
    lines = []
    for i, line in enumerate(timed.lines):
        start = max(0.0, float(line.start))
        end = max(start, float(timed.lines[i + 1].start) if i + 1 < len(timed.lines) else duration)
        tokens = []
        if line.words:
            for index, (when, text) in enumerate(line.words):
                when = max(0., float(when))
                stop = min(end, float(line.words[index + 1][0])) if index + 1 < len(line.words) else end
                tokens.append({'text': str(text), 'start': round(when, 4),
                               'duration': round(max(0., stop - when), 4)})
        lines.append({'lineIndex': i, 'startTime': round(start, 4), 'endTime': round(end, 4),
                      'text': str(line.text), 'syllables': tokens})
    return {'schemaVersion': SCHEMA, 'id': str(song.get('code') or song['id']),
            'title': str(song.get('title') or ''), 'artist': str(song.get('artist') or ''),
            'duration': round(float(duration), 4), 'audioOffsetMs': 0, 'lines': lines}


def safe_stem(code, identifier):
    safe = re.sub(r'[^a-zA-Z0-9_-]', '_', str(code or 'song'))[:50].strip('_') or 'song'
    return safe + '-' + identifier[:20]


def render_audio(midi, output, native, settings, *, ffmpeg='ffmpeg', cancel=None, synth=None):
    """Render MIDI events at sample-accurate boundaries via BASS_STREAM_DECODE.

    Float32 stereo goes directly to ffmpeg stdin; never creates a giant WAV.
    A single BassSynth instance may serve successive songs (and loads SF2 once).
    """
    from .bass import BassSynth
    source = load_midi(Path(midi))
    if not source.events or source.duration <= 0 or source.duration > 4 * 3600:
        raise ValueError('MIDI ไม่มีโน้ตหรือมีความยาวผิดปกติ')
    owned = synth is None
    if owned:
        synth = BassSynth(Path(native), settings=settings, decode=True)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.stem + '.partial.m4a')
    temporary.unlink(missing_ok=True)
    process = None
    try:
        if hasattr(synth, 'start_offline_song'):
            synth.start_offline_song()
        else:
            synth.reset()
        args = [str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                '-f', 'f32le', '-ar', str(SAMPLE_RATE), '-ac', '2', '-i', 'pipe:0',
                '-vn', '-c:a', 'aac', '-profile:a', 'aac_low', '-b:a', '256k',
                '-movflags', '+faststart', '-f', 'ipod', str(temporary)]
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.PIPE, **silent_subprocess_options())
        frame = 0
        try:
            # Interleave time-accurate MIDI messages with 2048-frame BASS decodes.
            total = min(round((source.duration + AUDIO_TAIL) * SAMPLE_RATE), 4 * 3600 * SAMPLE_RATE)
            for event in [*source.events, None]:
                if cancel is not None and cancel.is_set():
                    raise RuntimeError('ยกเลิกการแปลงเพลง')
                point = total if event is None else min(total, max(frame, round(event.at * SAMPLE_RATE)))
                while frame < point:
                    frames = min(2048, point - frame)
                    pcm = synth.render(frames)
                    if len(pcm) != frames * 8:
                        raise OSError('BASS ส่งข้อมูล PCM ไม่ครบ')
                    process.stdin.write(pcm)
                    frame += frames
                if event is not None:
                    synth.send(event.data)
            process.stdin.close()
            reason = process.stderr.read(8192).decode('utf-8', 'replace')
            code = process.wait(timeout=120)
            if code or not temporary.is_file() or temporary.stat().st_size < 256:
                raise RuntimeError('FFmpeg AAC encode ไม่สำเร็จ: ' + reason[-1500:])
        except Exception:
            if process.poll() is None:
                process.kill()
            process.wait()
            raise
        os.replace(temporary, output)
        return source
    finally:
        # Popen pipes are OS resources even when wait() completed. Close them
        # explicitly for long-running batches and Windows file-handle hygiene.
        if process is not None:
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
            if process.stderr is not None:
                process.stderr.close()
        temporary.unlink(missing_ok=True)
        if owned:
            synth.close()


class BatchRenderer:
    """One synthesizer lifetime per batch; optional CPU multiprocessing can
    instantiate one BatchRenderer per child, never share a BASS native handle."""
    def __init__(self, native, settings, soundfont, cache_dir, *, ffmpeg='ffmpeg', encoder=None):
        self.native = Path(native)
        self.settings = dict(settings or {})
        self.soundfont = Path(soundfont)
        self.cache_dir = Path(cache_dir)
        self.ffmpeg = ffmpeg
        self.encoder = encoder  # deterministic injection for pure offline tests
        self.synth = None

    def close(self):
        if self.synth is not None:
            self.synth.close()
            self.synth = None

    def __enter__(self): return self
    def __exit__(self, *_): self.close()

    def build(self, song, parts, *, cancel=None):
        identity = signature(parts, self.soundfont, self.settings)
        stem = safe_stem(song.get('code'), identity)
        output = self.cache_dir / identity[:2]
        audio = output / (stem + '.m4a')
        lyrics = output / (stem + '.json')
        proof = output / (stem + '.proof.json')
        if audio.is_file() and lyrics.is_file() and proof.is_file() and audio.stat().st_size > 256:
            try:
                record = json.loads(lyrics.read_text(encoding='utf-8'))
                old = json.loads(proof.read_text(encoding='utf-8'))
                if (record.get('schemaVersion') == SCHEMA and
                    record.get('id') == str(song.get('code') or song['id']) and
                    old.get('fingerprint') == identity and
                    old.get('audio_sha256') == file_hash(audio) and
                    old.get('lyrics_sha256') == file_hash(lyrics)):
                    return identity, audio, lyrics, float(record.get('duration', 0))
            except (ValueError, OSError):
                pass
        output.mkdir(parents=True, exist_ok=True)
        midi = load_midi(Path(parts['media']))
        if not midi.events:
            raise ValueError('MIDI ไม่มีข้อมูลดนตรี')
        timed = ncn_lyrics(parts['media'], midi) if 'cursor' in parts and 'lyrics' in parts else midi.lyrics
        if timed is None or not timed.lines:
            raise ValueError('ไม่มีเนื้อร้องที่จับเวลาได้')
        if self.encoder is None:
            if self.synth is None:
                from .bass import BassSynth
                self.synth = BassSynth(self.native, settings=self.settings, decode=True)
            render_audio(parts['media'], audio, self.native, self.settings, ffmpeg=self.ffmpeg,
                         cancel=cancel, synth=self.synth)
        else:
            self.encoder(Path(parts['media']), audio)
        doc = lyrics_document(song, midi, timed, midi.duration + AUDIO_TAIL)
        temp = lyrics.with_name(lyrics.name + '.partial')
        try:
            temp.write_text(json.dumps(doc, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
            os.replace(temp, lyrics)
        finally:
            temp.unlink(missing_ok=True)
        proof_temp = proof.with_name(proof.name + '.partial')
        try:
            proof_temp.write_text(json.dumps({'fingerprint':identity,
                'audio_sha256':file_hash(audio), 'lyrics_sha256':file_hash(lyrics)}), encoding='utf-8')
            os.replace(proof_temp, proof)
        finally:
            proof_temp.unlink(missing_ok=True)
        return identity, audio, lyrics, float(doc['duration'])


# Process-local singleton: each Windows spawned worker loads its own SoundFont
# once, then reuses it for all songs assigned to that process. No shared handles.
_PROCESS_RENDERER = None


def init_render_worker(native, settings, soundfont, cache_dir, ffmpeg='ffmpeg'):
    global _PROCESS_RENDERER
    import atexit
    _PROCESS_RENDERER = BatchRenderer(native, settings, soundfont, cache_dir, ffmpeg=ffmpeg)
    atexit.register(_PROCESS_RENDERER.close)


def render_worker_song(song, parts):
    if _PROCESS_RENDERER is None:
        raise RuntimeError('ยังไม่ได้เริ่ม BASS Renderer ใน Worker นี้')
    return _PROCESS_RENDERER.build(song, parts)
