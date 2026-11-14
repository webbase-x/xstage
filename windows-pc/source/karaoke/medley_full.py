"""Playback bounds and a short SoundFont drum fill for full-song medley."""
import bisect
import logging

from .lyrics import Lyrics
from .smf import MidiEvent, MidiSong


def session(item):
    return getattr(item, 'medley_session', '')


def next_item(app):
    queue = getattr(app, 'song_queue', None)
    return queue.items[0] if queue and queue.items else None


def source_bounds(engine, path, scan_tail=True):
    from .medley_trim import midi_bounds, pcm_bounds
    from .pcm_player import PcmPlayer

    song = getattr(engine, 'song', None)
    if song is not None:
        return midi_bounds(song, Lyrics())
    if isinstance(engine, PcmPlayer) or path.suffix.lower() == '.wav':
        decoder = engine if isinstance(engine, PcmPlayer) else None
        return pcm_bounds(path, engine.duration, decoder=decoder, scan_tail=scan_tail)
    return None


def with_lyrics(bounds, lyrics, offset):
    from .medley_trim import protect_lyrics

    try:
        offset = int(offset)
    except (TypeError, ValueError, OverflowError):
        offset = 0
    return protect_lyrics(bounds, lyrics, offset)


def start_at_trimmed_edge(engine, lyrics, offset):
    bounds = getattr(engine, 'medley_bounds', None)
    if bounds is None:
        return 0.
    start = with_lyrics(bounds, lyrics, offset).start
    if not start:
        return 0.
    try:
        exact_seek = getattr(engine, 'seek_medley_start', None)
        if exact_seek:
            return exact_seek(start)
        engine.seek(start)
        return start
    except (OSError, ValueError):
        logging.warning('Medley head trim bypassed', exc_info=True)
        engine.seek(0)
        return 0.


def can_play_fill(engine, settings, first_note):
    from .soundfont import inspect_font

    preset = settings.get('midi_preset')
    mixer = [row if isinstance(row, dict) else {} for row in preset[:16]] if isinstance(preset, list) else []
    solo = {channel for channel, row in enumerate(mixer) if row.get('solo')}
    audible = set(range(16)) if not solo else solo
    for channel in set(audible):
        if channel < len(mixer):
            row = mixer[channel]
            try:
                silent = float(row.get('gain', 1)) <= 0
            except (TypeError, ValueError):
                return False
            if row.get('mute', False) or silent:
                audible.discard(channel)
        elif channel in engine.muted:
            audible.discard(channel)
    if 9 not in audible:
        return False
    for event in engine.song.events:
        if event.at > first_note + .001:
            return False
        if event.data[0] & 0xF0 == 0x90 and event.data[2] and (event.data[0] & 15) in audible:
            break
    else:
        return False

    mapping = settings.get('instrument_fonts', {})
    if (not settings.get('soundfont_follow_song') and isinstance(mapping, dict)
            and isinstance(mapping.get('drums'), dict)):
        return True  # The explicit bank and preset were validated when the deck opened.
    for font in engine.output.options['fonts']:
        try:
            presets = inspect_font(font['path'])['presets']
        except (OSError, ValueError):
            continue
        if presets and any(bank == 128 and program == 0 for bank, program, _ in presets):
            return True
    return False


def drum_fill(song, bounds, speed):
    """Build a one-bar fill only when the first MIDI note lies on a known downbeat."""
    if bounds is None or bounds.first_note is None or speed <= 0:
        return None
    if song.division & 0x8000 or not song.explicit_tempo or not song.explicit_meter:
        return None
    entry_tick = song.seconds_tick(bounds.first_note)
    signature_index = bisect.bisect_right([row[0] for row in song.signatures], entry_tick + .001) - 1
    origin, numerator, denominator = song.signatures[signature_index]
    if denominator == 4 and numerator in (2, 3, 4):
        beats = numerator
    elif denominator == 8 and numerator in (6, 9, 12):
        beats = numerator // 3
    else:
        return None
    bar_ticks = song.division * 4 * numerator / denominator
    bars = (entry_tick - origin) / bar_ticks
    if abs(entry_tick - origin - round(bars) * bar_ticks) > 1:
        return None

    tempo_index = bisect.bisect_right([row[0] for row in song.tempo_map], entry_tick + .001) - 1
    tempo = song.tempo_map[tempo_index][2]
    bar_seconds = bar_ticks * tempo / song.division / 1e6 / speed
    lead = (bounds.first_note - bounds.start) / speed
    if not .8 <= bar_seconds <= 3.5 or not 0 <= lead <= .7:
        return None
    beat_seconds = bar_seconds / beats
    duration = bar_seconds - lead
    if duration < .45:
        return None
    hits = [(0, 36, 62)]
    hits.extend((index * beat_seconds, 42, 52) for index in range(1, beats))
    hits.append(((beats - .65) * beat_seconds, 38, 68))

    events = []
    for at, note, velocity in hits:
        if at + .12 < duration:
            events.append(MidiEvent(at, bytes((0x99, note, velocity))))
            events.append(MidiEvent(at + .04, bytes((0x89, note, 0))))
    return MidiSong(events, duration, Lyrics(), initial_bpm=60e6 / tempo * speed)
