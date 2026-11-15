"""Estimate playback bounds while keeping the original media timeline intact."""
from collections import Counter
from dataclasses import dataclass, replace
import math


@dataclass(frozen=True)
class TrimBounds:
    start: float
    end: float
    duration: float
    first_note: float | None = None


# Short gaps are often intentional breathing room. Trim only longer gaps and
# keep a margin either side of any onset, final release, or lyric cue.
MIN_GAP = .75
HEAD_MARGIN = .35
PCM_TAIL_MARGIN = .65
MIDI_TAIL_MARGIN = 2.0
LYRIC_LEAD = .8
LYRIC_HOLD = 2.0
PCM_EDGE_SECONDS = 8.0
PCM_QUIET_PEAK = .00001


def protect_lyrics(bounds, lyrics, offset_ms=0):
    """Widen estimated bounds for the displayed line and word cue timings."""
    if lyrics is None or not lyrics.lines:
        return bounds
    shift = (lyrics.offset_ms + offset_ms) / 1000
    if not math.isfinite(shift):
        return replace(bounds, start=0., end=bounds.duration)
    first, last = math.inf, -math.inf
    for line in lyrics.lines:
        first, last = min(first, line.start), max(last, line.start)
        for when, _ in line.words:
            first, last = min(first, when), max(last, when)
    return replace(bounds, start=max(0., min(bounds.start, first-shift-LYRIC_LEAD)),
                   end=min(bounds.duration, max(bounds.end, last-shift+LYRIC_HOLD)))


def _edges(duration, onset, release, tail_margin, first_note=None):
    start = onset - HEAD_MARGIN if onset is not None else 0.
    end = release + tail_margin if release is not None else duration
    if start < MIN_GAP:
        start = 0.
    if duration - end < MIN_GAP:
        end = duration
    return TrimBounds(start, end, duration, first_note)


def midi_bounds(song, lyrics=None):
    """Find note extents and leave room for pedals and SoundFont decay."""
    pressed = [Counter() for _ in range(16)]
    pedals = [set() for _ in range(16)]
    sustained = set()
    long_release = set()
    first_note = last_release = None
    for event in song.events:
        status = event.data[0] & 0xF0
        channel = event.data[0] & 15
        if status == 0x90 and event.data[2]:
            if first_note is None:
                first_note = event.at
            pressed[channel][event.data[1]] += 1
        elif status in (0x80, 0x90):
            note = event.data[1]
            if pressed[channel][note] > 0:
                pressed[channel][note] -= 1
                if not pressed[channel][note]:
                    del pressed[channel][note]
                if pedals[channel]:
                    sustained.add(channel)
                last_release = event.at
        elif status == 0xB0:
            controller, value = event.data[1:3]
            if controller in (64, 66, 69):  # Sustain, sostenuto, hold 2.
                if value >= 64:
                    pedals[channel].add(controller)
                else:
                    pedals[channel].discard(controller)
            elif controller == 121:  # Reset controllers, including pedals.
                pedals[channel].clear()
            elif controller == 120:  # All sound off.
                if pressed[channel] or channel in sustained:
                    pressed[channel].clear()
                    sustained.discard(channel)
                    last_release = event.at
            elif controller in (123, 124, 125, 126, 127) and pressed[channel]:
                pressed[channel].clear()
                if pedals[channel]:
                    sustained.add(channel)
                last_release = event.at
            elif controller == 72 and value > 64:
                # A synthesizer can extend a release past our fixed margin.
                long_release.add(channel)
            if not pedals[channel] and channel in sustained:
                sustained.remove(channel)
                last_release = event.at
    if any(pressed) or sustained or long_release:
        last_release = None
    bounds = _edges(song.duration, first_note, last_release, MIDI_TAIL_MARGIN, first_note)
    return protect_lyrics(bounds, song.lyrics if lyrics is None else lyrics)


def _pcm_activity(region, *, reverse=False):
    if region is None:
        return None
    start, end, decoded = region
    samples = memoryview(decoded).cast('f')
    sequence = reversed(samples) if reverse else samples
    for index, sample in enumerate(sequence):
        if not -PCM_QUIET_PEAK <= sample <= PCM_QUIET_PEAK:
            if not math.isfinite(sample):
                return None
            offset = index * (end-start) / len(samples)
            return end-offset if reverse else start+offset
    # An edge that is entirely silent gives no reliable cut point.
    return None


def pcm_bounds(path, duration, lyrics=None, *, decoder=None, scan_tail=True):
    """Check decoded samples at the file edges. An uncertain edge is kept."""
    head = tail = None
    if decoder is not None and duration > MIN_GAP:
        try:
            leading, trailing = decoder.sample_regions(path, PCM_EDGE_SECONDS, scan_tail=scan_tail)
            head = _pcm_activity(leading)
            # An estimated VBR MP3 duration can disagree with the scanned source.
            if trailing is not None and abs(trailing[1]-duration) < .05:
                tail = _pcm_activity(trailing, reverse=True)
        except (OSError, ValueError, AttributeError):
            pass
    if head is not None and head >= duration:
        head = None
    return protect_lyrics(_edges(duration, head, tail, PCM_TAIL_MARGIN), lyrics)
