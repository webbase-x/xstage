"""Strict standard MIDI file reader. No proprietary formats or decryption.

Format 0 and synchronous format 1, metrical PPQN or SMPTE timing. SysEx is
parsed but not sent by the basic playback engine. No third-party dependency.
"""
from __future__ import annotations

import io
import struct
from dataclasses import dataclass
from dataclasses import field
import bisect
from pathlib import Path
from .lyrics import decode_text, midi_lyrics, Lyrics


@dataclass
class MidiEvent:
    at: float
    data: bytes


@dataclass
class MidiSong:
    events: list[MidiEvent]
    duration: float
    lyrics: Lyrics
    title: str = ""
    initial_bpm: float = 120.0
    division: int = 480
    tempo_map: list = field(default_factory=lambda: [(0, 0.0, 500000)])
    signatures: list = field(default_factory=lambda: [(0, 4, 4)])
    chords: list = field(default_factory=list)
    artist: str = ""
    key_signature: str = ""
    explicit_tempo: bool = False
    explicit_meter: bool = False

    def tick_seconds(self, tick):
        if self.division & 0x8000:
            code = (self.division >> 8) - 256
            fps = 30000 / 1001 if code == -29 else -code
            return tick / (fps * (self.division & 255))
        index = bisect.bisect_right([part[0] for part in self.tempo_map], tick) - 1
        origin, seconds, tempo = self.tempo_map[max(0, index)]
        return seconds + (tick - origin) * tempo / self.division / 1e6

    def seconds_tick(self, seconds):
        if self.division & 0x8000:
            code = (self.division >> 8) - 256
            fps = 30000 / 1001 if code == -29 else -code
            return seconds * fps * (self.division & 255)
        index = bisect.bisect_right([part[1] for part in self.tempo_map], seconds) - 1
        tick, origin, tempo = self.tempo_map[max(0, index)]
        return tick + (seconds - origin) * 1e6 * self.division / tempo

    def musical_position(self, seconds):
        tick = self.seconds_tick(seconds)
        signature = self.signatures[0]
        bar = 1
        for following in self.signatures[1:]:
            if following[0] > tick:
                break
            ticks_per_beat = self.division * 4 / signature[2]
            bar += int((following[0] - signature[0]) / (ticks_per_beat * signature[1]))
            signature = following
        ticks_per_beat = self.division * 4 / signature[2]
        beats = max(0, (tick - signature[0]) / ticks_per_beat)
        return bar + int(beats // signature[1]), int(beats % signature[1]) + 1, signature[1]


def read_exact(stream, count):
    data = stream.read(count)
    if len(data) != count:
        raise ValueError("ไฟล์ MIDI ไม่สมบูรณ์: ข้อมูลถูกตัด")
    return data


def read_vlq(stream):
    value = 0
    for _ in range(4):
        byte = read_exact(stream, 1)[0]
        value = (value << 7) | (byte & 127)
        if not byte & 128:
            return value
    raise ValueError("MIDI variable-length value เกิน 4 ไบต์")


def load_midi(path: Path) -> MidiSong:
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("ไฟล์ MIDI ใหญ่เกิน 64 MB")
    if path.suffix.lower() == '.emk':
        from .emk import parse_emk
        return parse_emk(path.read_bytes())
    return parse_midi(path.read_bytes(), legacy=True)


def parse_midi(data: bytes, legacy=False) -> MidiSong:
    stream = io.BytesIO(data)
    signature = read_exact(stream, 4)
    if signature != b"MThd" and not (legacy and signature == b'NCN1'):
        raise ValueError("ไม่ใช่ไฟล์ Standard MIDI (.mid/.kar)")
    header_len = struct.unpack(">I", read_exact(stream, 4))[0]
    header = read_exact(stream, header_len)
    if header_len < 6:
        raise ValueError("MIDI header ไม่สมบูรณ์")
    fmt, track_count, division = struct.unpack(">HHH", header[:6])
    if fmt not in (0, 1) or not division or not track_count:
        raise ValueError("รองรับ Standard MIDI format 0/1 เท่านั้น")
    if fmt == 0 and track_count != 1:
        raise ValueError("MIDI format 0 ต้องมี 1 track")
    raw_events = []
    sequence = 0
    final_tick = 0
    for _ in range(track_count):
        if read_exact(stream, 4) != b"MTrk":
            raise ValueError("ไม่พบ MIDI track")
        length = struct.unpack(">I", read_exact(stream, 4))[0]
        track = io.BytesIO(read_exact(stream, length))
        tick, running = 0, None
        while track.tell() < length:
            tick += read_vlq(track)
            status = read_exact(track, 1)[0]
            if status < 128:
                if running is None:
                    raise ValueError("MIDI running status ไม่มีสถานะก่อนหน้า")
                track.seek(-1, 1)
                status = running
            if status == 0xFF:
                if not legacy:
                    running = None
                meta_type = read_exact(track, 1)[0]
                payload = read_exact(track, read_vlq(track))
                if meta_type == 0x51:
                    if len(payload) != 3 or int.from_bytes(payload, "big") == 0:
                        raise ValueError("MIDI tempo ไม่ถูกต้อง")
                if meta_type==0x59 and (len(payload)!=2 or not -7<=int.from_bytes(payload[:1],'big',signed=True)<=7 or payload[1] not in (0,1)):
                    raise ValueError('MIDI key signature ไม่ถูกต้อง')
                raw_events.append((tick, sequence, "meta", meta_type, payload))
                if meta_type == 0x2F:
                    final_tick = max(final_tick, tick)
                    break
            elif status in (0xF0, 0xF7):
                running = None
                read_exact(track, read_vlq(track))
            elif 0x80 <= status < 0xF0:
                running = status
                count = 1 if status & 0xF0 in (0xC0, 0xD0) else 2
                payload = read_exact(track, count)
                if any(byte > 127 for byte in payload):
                    raise ValueError("MIDI channel data ไม่ถูกต้อง")
                raw_events.append((tick, sequence, "channel", status, payload))
            else:
                raise ValueError(f"MIDI event ไม่รองรับ: {status:02X}")
            final_tick = max(final_tick, tick)
            sequence += 1
    raw_events.sort(key=lambda event: (event[0], event[1]))
    smpte = None
    if division & 0x8000:
        frame_code = (division >> 8) - 256
        if frame_code not in (-24, -25, -29, -30) or not division & 255:
            raise ValueError("MIDI SMPTE division ไม่ถูกต้อง")
        fps = 30000 / 1001 if frame_code == -29 else -frame_code
        smpte = fps * (division & 255)
    tempo, previous, elapsed = 500000, 0, 0.0
    events, lyric_events, text_events = [], [], []
    title, initial_bpm, got_tempo = "", 120.0, False
    opening_tempo = opening_meter = False
    key_signature=''
    tempo_map, signatures, chords = [(0, 0.0, 500000)], [(0, 4, 4)], []
    for tick, _, kind, status, payload in raw_events:
        elapsed += (tick - previous) / smpte if smpte else (tick - previous) * tempo / division / 1e6
        previous = tick
        if kind == "channel":
            events.append(MidiEvent(elapsed, bytes([status]) + payload))
        elif status == 0x51:
            tempo = int.from_bytes(payload, "big")
            tempo_map.append((tick, elapsed, tempo))
            opening_tempo |= tick == 0
            if not got_tempo:
                initial_bpm, got_tempo = 60e6 / tempo, True
        elif status==0x59 and not key_signature:
            offset=int.from_bytes(payload[:1],'big',signed=True)+7
            notes=('Cb Gb Db Ab Eb Bb F C G D A E B F# C#' if payload[1]==0 else 'Ab Eb Bb F C G D A E B F# C# G# D# A#').split()
            key_signature=notes[offset]+('m' if payload[1] else '')
        elif status == 0x58 and len(payload) >= 2:
            if payload[0] and payload[1] <= 6:
                signatures.append((tick, payload[0], 2 ** payload[1]))
                opening_meter |= tick == 0
        elif status in (0x01, 0x03, 0x05, 0x06):
            text = decode_text(payload)
            if status in (0x01, 0x06) and text.startswith(('[chord:', '@CHORD:')):
                chords.append((elapsed, text.split(':', 1)[1].rstrip(']')))
            if status == 0x05:
                lyric_events.append((elapsed, text))
            elif status == 0x01:
                text_events.append((elapsed, text))
            elif not title:
                title = text
    elapsed += (final_tick - previous) / smpte if smpte else (final_tick - previous) * tempo / division / 1e6
    # Text events are lyrics only when explicitly marked as Soft Karaoke.
    if not lyric_events and any(text.startswith(("@KMIDI", "@K", "/", "\\")) for _, text in text_events):
        lyric_events = text_events
    headers = [text[2:].strip() for _, text in text_events if text.startswith("@T")]
    if headers:
        title = headers[0] or title
    return MidiSong(events, max(elapsed, 0.05), midi_lyrics(lyric_events), title, initial_bpm,
                    division, tempo_map, signatures, chords, headers[1] if len(headers) > 1 else '',
                    key_signature, opening_tempo, opening_meter)
