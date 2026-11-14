"""Windows playback through documented WinMM APIs, with no vendor DLLs."""
from __future__ import annotations

import bisect
import ctypes
import os
import time
import uuid
import wave
import threading
from functools import wraps
from pathlib import Path
from .smf import MidiSong, load_midi


def mci_path(path):
    """Legacy MCI drivers can reject long paths; use an existing 8.3 alias."""
    from ctypes import wintypes as w
    dll = ctypes.WinDLL("kernel32", use_last_error=True)
    dll.GetShortPathNameW.argtypes = [w.LPCWSTR, w.LPWSTR, w.DWORD]
    dll.GetShortPathNameW.restype = w.DWORD
    buffer = ctypes.create_unicode_buffer(32768)
    length = dll.GetShortPathNameW(str(path), buffer, len(buffer))
    return buffer.value if 0 < length < len(buffer) else str(path)


class WinMidi:
    def __init__(self, device=-1):
        if os.name != "nt":
            raise OSError("MIDI playback รุ่นนี้ใช้ได้บน Windows")
        from ctypes import wintypes as w
        self.dll = ctypes.WinDLL("winmm")
        self.dll.midiOutOpen.argtypes = [ctypes.POINTER(ctypes.c_void_p), w.UINT,
                                        ctypes.c_size_t, ctypes.c_size_t, w.DWORD]
        self.dll.midiOutOpen.restype = w.UINT
        self.dll.midiOutShortMsg.argtypes = [ctypes.c_void_p, w.DWORD]
        self.dll.midiOutShortMsg.restype = w.UINT
        self.dll.midiOutReset.argtypes = [ctypes.c_void_p]
        self.dll.midiOutClose.argtypes = [ctypes.c_void_p]
        self.handle = ctypes.c_void_p()
        error = self.dll.midiOutOpen(ctypes.byref(self.handle), device & 0xFFFFFFFF, 0, 0, 0)
        if error:
            raise OSError(f"เปิด MIDI output ไม่ได้ (รหัส {error}) กรุณาปิดโปรแกรมที่ใช้ MIDI หรือเลือกอุปกรณ์อื่น")

    @staticmethod
    def devices():
        if os.name != "nt":
            return []
        from ctypes import wintypes as w
        class Caps(ctypes.Structure):
            _fields_ = [("mid", w.WORD), ("pid", w.WORD), ("version", w.DWORD),
                        ("name", w.WCHAR * 32), ("technology", w.WORD),
                        ("voices", w.WORD), ("notes", w.WORD), ("channel_mask", w.WORD),
                        ("support", w.DWORD)]
        dll = ctypes.WinDLL("winmm")
        dll.midiOutGetDevCapsW.argtypes = [ctypes.c_size_t, ctypes.POINTER(Caps), w.UINT]
        result = [(-1, "ค่าเริ่มต้นของ Windows")]
        for index in range(dll.midiOutGetNumDevs()):
            caps = Caps()
            if not dll.midiOutGetDevCapsW(index, ctypes.byref(caps), ctypes.sizeof(caps)):
                result.append((index, caps.name))
        return result

    def send(self, data: bytes):
        if self.handle.value and data:
            packed = int.from_bytes(data.ljust(4, b"\0"), "little")
            error = self.dll.midiOutShortMsg(self.handle, packed)
            if error:
                raise OSError(f"ส่ง MIDI ไม่สำเร็จ (รหัส {error})")

    def reset(self):
        if self.handle.value:
            self.dll.midiOutReset(self.handle)

    def close(self):
        if self.handle.value:
            self.reset()
            self.dll.midiOutClose(self.handle)
            self.handle = ctypes.c_void_p()


class MidiPlayer:
    """Playback clock and scheduler, driven every 10 ms by the UI.

    All output is on the UI thread; background library indexing never touches
    this object. Clock injection and output injection permit silent unit tests.
    """
    kind = "MIDI"

    def __init__(self, output=None, clock=time.perf_counter, device=-1):
        self.output = output if output is not None else WinMidi(device)
        from .midi_keyboard import NoteMonitor
        self.note_monitor = NoteMonitor()
        self.clock = clock
        self.song: MidiSong | None = None
        self.duration = 0.0
        self._position = 0.0
        self.anchor = self.clock()
        self.playing = False
        self.ended = False
        self.speed = 1.0
        self.key = 0
        self.volume = 0.75
        self.muted = set()
        self.channel_gain = [1.0] * 16
        self.channel_volume = [100] * 16
        self.cursor = 0
        self.times = []
        self.lock = threading.RLock()
        self._quit = threading.Event()
        self._scheduler = None
        self.scheduler_error = None
        self.solo = set()
        self.drum_muted = set()
        self.pan = [None] * 16
        self.program = [None] * 16
        self.loop_start = self.loop_end = None

    def enable_scheduler(self):
        if self._scheduler:
            return
        def work():
            while not self._quit.wait(.004):
                try:
                    self.pump()
                except Exception as error:
                    self.scheduler_error = error
                    self.playing = False
                    self._quit.set()
        self._scheduler = threading.Thread(target=work, name='midi-scheduler', daemon=True)
        self._scheduler.start()

    @property
    def position(self):
        extra = (self.clock() - self.anchor) * self.speed if self.playing else 0
        return min(self.duration, self._position + extra)

    def load(self, path: Path):
        self.stop()
        self.song = load_midi(path)
        self.lyric_warning = getattr(self.song, 'lyric_warning', '')
        try:
            from .legacy import ncn_lyrics
            lyrics = ncn_lyrics(path, self.song)
            if lyrics:
                self.song.lyrics = lyrics
        except (ValueError, OSError) as error:
            self.lyric_warning = str(error)
        self.duration = self.song.duration
        self.times = [event.at for event in self.song.events]
        self.seek(0)

    def _channel_level(self, channel):
        if channel in self.muted or (self.solo and channel not in self.solo):
            return 0
        return max(0, min(127, round(self.channel_volume[channel] * self.volume * self.channel_gain[channel])))

    def _output_send(self, data):
        self.output.send(data)
        self.note_monitor.feed(data)

    def _output_reset(self):
        self.output.reset()
        self.note_monitor.reset()

    def _send(self, data):
        status, channel = data[0] & 0xF0, data[0] & 15
        if status == 0xB0 and data[1] == 7:
            self.channel_volume[channel] = data[2]
            data = bytes([data[0], 7, self._channel_level(channel)])
        if status in (0x80, 0x90, 0xA0):
            if channel in self.muted or (self.solo and channel not in self.solo):
                return
            if channel == 9 and data[1] in self.drum_muted:
                return
            note = data[1] + (self.key if channel != 9 else 0)
            if not 0 <= note <= 127:
                return
            data = bytes([data[0], note, data[2]])
        if status == 0xB0 and data[1] == 10 and self.pan[channel] is not None:
            data = bytes([data[0], 10, self.pan[channel]])
        if status == 0xC0 and self.program[channel] is not None:
            data = bytes([data[0], self.program[channel]])
        self._output_send(data)

    def _reset_state(self):
        self._output_reset()
        self.channel_volume = [100] * 16
        for channel in range(16):
            self._output_send(bytes([0xB0 | channel, 121, 0]))
            self._output_send(bytes([0xB0 | channel, 0, 0]))
            self._output_send(bytes([0xB0 | channel, 32, 0]))
            self._output_send(bytes([0xC0 | channel, 0]))
            self._output_send(bytes([0xE0 | channel, 0, 64]))
            self._output_send(bytes([0xB0 | channel, 7, self._channel_level(channel)]))

    def play(self):
        if not self.song:
            return
        if self.position >= self.duration:
            self.seek(0)
        if not self.playing:
            self.anchor = self.clock()
            self.playing = True
            self.ended = False

    def pause(self):
        self._position = self.position
        self.playing = False
        self._output_reset()

    def stop(self):
        self.playing = False
        self._position = 0.0
        self.cursor = 0
        self.ended = False
        if self.song:
            self._reset_state()
        else:
            self._output_reset()

    def seek(self, seconds):
        self._position = max(0.0, min(float(seconds), self.duration))
        self.anchor = self.clock()
        self.ended = False
        self.cursor = bisect.bisect_left(self.times, self._position)
        self._reset_state()
        # Restore instrument/controller state, without triggering historical notes.
        if self.song:
            for event in self.song.events[:self.cursor]:
                if event.data[0] & 0xF0 not in (0x80, 0x90, 0xA0):
                    self._send(event.data)

    def set_speed(self, value):
        self._position = self.position
        self.anchor = self.clock()
        self.speed = max(0.5, min(1.5, float(value)))

    def set_key(self, value):
        self.key = max(-12, min(12, int(value)))
        self._output_reset()

    def set_volume(self, value):
        self.volume = max(0.0, min(1.0, float(value)))
        for channel in range(16):
            self._output_send(bytes([0xB0 | channel, 7, self._channel_level(channel)]))

    def set_channel(self, channel, gain=None, muted=None):
        if gain is not None:
            self.channel_gain[channel] = max(0.0, min(1.0, gain))
        if muted is not None:
            self.muted.discard(channel) if not muted else self.muted.add(channel)
            if muted:
                self._output_send(bytes([0xB0 | channel, 120, 0]))
                self._output_send(bytes([0xB0 | channel, 123, 0]))
        self._output_send(bytes([0xB0 | channel, 7, self._channel_level(channel)]))

    def set_pan(self, channel, value):
        self.pan[channel] = max(0, min(127, int(value)))
        self._output_send(bytes([0xB0 | channel, 10, self.pan[channel]]))

    def set_program(self, channel, value):
        self.program[channel] = None if value is None else max(0, min(127, int(value)))
        if value is not None:
            self._output_send(bytes([0xC0 | channel, self.program[channel]]))

    def set_solo(self, channel, enabled):
        self.solo.add(channel) if enabled else self.solo.discard(channel)
        for index in range(16):
            if self.solo and index not in self.solo:
                self._output_send(bytes([0xB0 | index, 120, 0]))
            self._output_send(bytes([0xB0 | index, 7, self._channel_level(index)]))

    def set_drum_muted(self, note, muted):
        self.drum_muted.add(note) if muted else self.drum_muted.discard(note)
        self._output_send(bytes([0xB9, 120, 0]))

    def set_loop(self, start=None, end=None):
        if start is None or end is None:
            self.loop_start = self.loop_end = None
            return
        if not 0 <= start < end <= self.duration:
            raise ValueError('ช่วงวนเพลงต้องมีจุดเริ่มก่อนจุดจบ')
        self.loop_start, self.loop_end = float(start), float(end)

    def pump(self):
        if not self.playing or not self.song:
            return
        position = self.position
        if self.loop_end is not None and position >= self.loop_end:
            self.seek(self.loop_start)
            position = self.position
        while self.cursor < len(self.song.events) and self.song.events[self.cursor].at <= position:
            self._send(self.song.events[self.cursor].data)
            self.cursor += 1
        if position >= self.duration:
            self._position = self.duration
            self.playing = False
            self.ended = True
            self._output_reset()

    def close(self):
        self._quit.set()
        if self._scheduler and self._scheduler is not threading.current_thread():
            self._scheduler.join(timeout=2)
        self.stop()
        self.output.close()


def _synchronized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return call


for _name in ('load', 'play', 'pause', 'stop', 'seek', 'set_speed', 'set_key', 'set_volume',
              'set_channel', 'set_pan', 'set_program', 'set_solo', 'set_drum_muted', 'set_loop', 'pump'):
    setattr(MidiPlayer, _name, _synchronized(getattr(MidiPlayer, _name)))


class MediaPlayer:
    """Local audio/video through Windows MCI. Codec availability is OS-specific."""
    kind = "MEDIA"

    def __init__(self):
        if os.name != "nt":
            raise OSError("Audio/video playback รุ่นนี้ใช้ได้บน Windows")
        from ctypes import wintypes as w
        self.dll = ctypes.WinDLL("winmm")
        self.dll.mciSendStringW.argtypes = [w.LPCWSTR, w.LPWSTR, w.UINT, w.HWND]
        self.dll.mciSendStringW.restype = w.DWORD
        self.dll.mciGetErrorStringW.argtypes = [w.DWORD, w.LPWSTR, w.UINT]
        self.alias = "nk" + uuid.uuid4().hex[:10]
        self.opened = False
        self.duration = 0.0
        self.playing = False
        self.ended = False
        self.started = False
        self.speed = 1.0
        self.has_video = False
        self.last_position = 0.0

    def command(self, command):
        result = ctypes.create_unicode_buffer(1024)
        error = self.dll.mciSendStringW(command, result, len(result), None)
        if error:
            message = ctypes.create_unicode_buffer(512)
            self.dll.mciGetErrorStringW(error, message, len(message))
            raise OSError(f"Windows media ({error}): {message.value}")
        return result.value

    def load(self, path, video_handle=0, video=False):
        self.close()
        self.has_video = video
        self.started = self.ended = False
        self.last_position = 0.0
        path = mci_path(Path(path).resolve())
        if '"' in path or "\n" in path or "\r" in path:
            raise ValueError("ชื่อไฟล์ไม่ถูกต้อง")
        # MPEGVideo supports system codecs and per-player volume. Fall back to
        # the native WaveAudio driver for WAV on systems without that decoder.
        types = ["mpegvideo", "waveaudio"] if path.lower().endswith(".wav") else ["mpegvideo"]
        error = None
        for media_type in types:
            parent = f" parent {int(video_handle)} style child" if video and video_handle else ""
            try:
                self.command(f'open "{path}" type {media_type} alias {self.alias}{parent}')
                self.opened = True
                break
            except OSError as exc:
                error = exc
        if not self.opened:
            hint = "\nลองย้ายไฟล์ไปโฟลเดอร์สั้น เช่น D:\\Songs" if len(path) > 127 else ""
            raise OSError(f"เปิดสื่อไม่ได้ ระบบ Windows อาจไม่มี codec ของไฟล์นี้{hint}\n{error}")
        try:
            self.command(f"set {self.alias} time format milliseconds")
            self.duration = int(self.command(f"status {self.alias} length")) / 1000
            if video and video_handle:
                self.command(f"window {self.alias} handle {int(video_handle)}")
        except Exception:
            self.close()
            raise

    @property
    def position(self):
        if not self.opened:
            return 0.0
        return int(self.command(f"status {self.alias} position")) / 1000

    def play(self):
        if self.opened:
            if self.position >= self.duration:
                self.seek(0)
            self.command(f"play {self.alias}")
            self.playing = self.started = True
            self.ended = False

    def pause(self):
        if self.opened:
            self.command(f"pause {self.alias}")
            self.playing = False

    def stop(self):
        if self.opened:
            self.command(f"stop {self.alias}")
            self.command(f"seek {self.alias} to start")
        self.playing = self.started = self.ended = False

    def seek(self, seconds):
        if self.opened:
            active = self.playing
            target = round(max(0, min(seconds, self.duration)) * 1000)
            self.command(f"seek {self.alias} to {target}")
            self.last_position = target / 1000
            self.ended = False
            if active:
                self.command(f"play {self.alias}")

    def set_speed(self, value):
        value = max(0.5, min(1.5, float(value)))
        self.command(f"set {self.alias} speed {round(value * 1000)}")
        self.speed = value

    def set_volume(self, value):
        self.command(f"setaudio {self.alias} volume to {round(max(0, min(1, value)) * 1000)}")

    def set_audio_mode(self,mode):
        if mode not in ('stereo','left','right'):raise ValueError('ช่องเสียงไม่ถูกต้อง')
        old=getattr(self,'audio_mode','stereo')
        def send(value):
            self.command(f"setaudio {self.alias} left {'off' if value=='right' else 'on'}")
            self.command(f"setaudio {self.alias} right {'off' if value=='left' else 'on'}")
        try:send(mode)
        except OSError:
            try:send(old)
            except OSError:pass
            raise
        self.audio_mode=mode

    def set_audio_track(self,track):
        if not isinstance(track,int) or not 1<=track<=32:raise ValueError('แทร็กต้องอยู่ระหว่าง 1–32')
        self.command(f"setaudio {self.alias} stream to {track}")
        self.audio_track=track

    def resize(self, width, height):
        if self.opened and self.has_video:
            self.command(f"put {self.alias} window at 0 0 {max(1, int(width))} {max(1, int(height))}")

    def set_window(self, handle):
        if self.opened and self.has_video:
            self.command(f"window {self.alias} handle {int(handle)}")

    def pump(self):
        if self.opened and self.playing:
            self.last_position = self.position
            mode = self.command(f"status {self.alias} mode")
            if mode == "stopped":
                if self.started and self.duration > 0 and self.last_position >= self.duration - 0.3:
                    self.ended = True
                self.playing = False

    def close(self):
        if self.opened:
            self.command(f"close {self.alias}")
        self.opened = False
        self.playing = False


class WavePlayer(MediaPlayer):
    """PCM WAV via waveOut: avoids MCI codec/path limitations for WAV.

    Windows resamples PCM at the requested device rate. Speed consequently
    changes pitch; MIDI's key/tempo independence does not apply to WAV.
    """
    kind = "AUDIO"

    def __init__(self):
        from ctypes import wintypes as w
        class Format(ctypes.Structure):
            _pack_ = 2
            _fields_ = [("tag", w.WORD), ("channels", w.WORD), ("rate", w.DWORD),
                        ("byte_rate", w.DWORD), ("align", w.WORD), ("bits", w.WORD), ("size", w.WORD)]
        class Header(ctypes.Structure):
            _fields_ = [("data", ctypes.c_void_p), ("length", w.DWORD), ("recorded", w.DWORD),
                        ("user", ctypes.c_size_t), ("flags", w.DWORD), ("loops", w.DWORD),
                        ("next", ctypes.c_void_p), ("reserved", ctypes.c_size_t)]
        self.Format, self.Header = Format, Header
        self.dll = ctypes.WinDLL("winmm")
        self.dll.waveOutOpen.argtypes = [ctypes.POINTER(ctypes.c_void_p), w.UINT, ctypes.POINTER(Format),
                                        ctypes.c_size_t, ctypes.c_size_t, w.DWORD]
        for name in ("waveOutPrepareHeader", "waveOutUnprepareHeader", "waveOutWrite"):
            getattr(self.dll, name).argtypes = [ctypes.c_void_p, ctypes.POINTER(Header), w.UINT]
        for name in ("waveOutReset", "waveOutPause", "waveOutRestart", "waveOutClose"):
            getattr(self.dll, name).argtypes = [ctypes.c_void_p]
        self.dll.waveOutSetVolume.argtypes = [ctypes.c_void_p, w.DWORD]
        self.dll.waveOutGetPosition.argtypes = [ctypes.c_void_p, ctypes.c_void_p, w.UINT]
        self.handle = ctypes.c_void_p()
        self.header = None
        self.buffer = None
        self.pcm = b""
        self.opened = self.playing = self.ended = self.has_video = False
        self.speed = 1.0
        self.volume = 0.75
        self.duration = 0.0
        self.start_frame = 0
        self.rate = 44100
        self.channels = 2
        self.width = 2
        self.frames = 0

    def _check(self, error):
        if error:
            raise OSError(f"Windows PCM audio ไม่สำเร็จ (รหัส {error})")

    def _open_device(self):
        rate = round(self.rate * self.speed)
        align = self.channels * self.width
        fmt = self.Format(1, self.channels, rate, rate * align, align, self.width * 8, 0)
        self._check(self.dll.waveOutOpen(ctypes.byref(self.handle), 0xFFFFFFFF,
                    ctypes.byref(fmt), 0, 0, 0))
        self.opened = True
        self.set_volume(self.volume)

    def load(self, path, video_handle=0, video=False):
        self.close()
        if Path(path).stat().st_size > 512 * 1024 * 1024:
            raise ValueError("WAV รุ่นนี้รองรับไฟล์ไม่เกิน 512 MB")
        with wave.open(str(path), "rb") as source:
            if source.getcomptype() != "NONE":
                raise ValueError("WAV ต้องเป็น PCM ที่ไม่บีบอัด")
            self.rate, self.channels = source.getframerate(), source.getnchannels()
            self.width, self.frames = source.getsampwidth(), source.getnframes()
            self.pcm = source.readframes(self.frames)
        if not self.frames or self.channels not in (1, 2) or self.width not in (1, 2, 3, 4):
            raise ValueError("รูปแบบ WAV ไม่รองรับ: ต้องเป็น PCM mono/stereo 8–32 bit")
        if len(self.pcm) != self.frames * self.channels * self.width:
            raise ValueError("ไฟล์ WAV ไม่สมบูรณ์")
        self.duration = self.frames / self.rate
        self.start_frame = 0
        self.ended = False
        self._open_device()

    @property
    def position(self):
        if not self.header or not self.opened:
            return self.start_frame / self.rate
        # MMTIME is a DWORD plus an 8-byte union. TIME_BYTES is 4; drivers may
        # return TIME_SAMPLES or TIME_MS instead, so inspect the returned type.
        position = (ctypes.c_uint32 * 3)(4, 0, 0)
        self._check(self.dll.waveOutGetPosition(self.handle, ctypes.byref(position), ctypes.sizeof(position)))
        if position[0] == 4:
            frames = position[1] / (self.width * self.channels)
        elif position[0] == 2:
            frames = position[1]
        else:
            frames = position[1] / 1000 * self.rate * self.speed
        return min(self.duration, (self.start_frame + frames) / self.rate)

    def _clear_buffer(self):
        if self.handle.value and self.header:
            self._check(self.dll.waveOutReset(self.handle))
            self._check(self.dll.waveOutUnprepareHeader(self.handle, ctypes.byref(self.header), ctypes.sizeof(self.header)))
        self.header = self.buffer = None

    def play(self):
        if not self.opened:
            return
        if self.header and not self.header.flags & 1:
            self._check(self.dll.waveOutRestart(self.handle))
        else:
            if self.position >= self.duration:
                self.seek(0)
            self._clear_buffer()
            offset = self.start_frame * self.channels * self.width
            self.buffer = ctypes.create_string_buffer(self.pcm[offset:])
            self.header = self.Header()
            self.header.data = ctypes.addressof(self.buffer)
            self.header.length = len(self.pcm) - offset
            self._check(self.dll.waveOutPrepareHeader(self.handle, ctypes.byref(self.header), ctypes.sizeof(self.header)))
            self._check(self.dll.waveOutWrite(self.handle, ctypes.byref(self.header), ctypes.sizeof(self.header)))
        self.playing = True
        self.ended = False

    def pause(self):
        if self.opened:
            self._check(self.dll.waveOutPause(self.handle))
        self.playing = False

    def stop(self):
        self._clear_buffer()
        self.start_frame = 0
        self.playing = self.ended = False

    def seek(self, seconds):
        playing = self.playing
        self._clear_buffer()
        self.start_frame = max(0, min(self.frames, round(seconds * self.rate)))
        self.playing = self.ended = False
        if playing and self.start_frame < self.frames:
            self.play()

    def set_speed(self, value):
        value = max(0.5, min(1.5, float(value)))
        if value == self.speed:
            return
        position, playing = self.position, self.playing
        old = self.speed
        self.close()
        self.speed = value
        try:
            self._open_device()
        except OSError:
            self.speed = old
            self._open_device()
            self.seek(position)
            if playing:
                self.play()
            raise
        self.seek(position)
        if playing:
            self.play()

    def set_volume(self, value):
        self.volume = max(0.0, min(1.0, float(value)))
        if self.handle.value:
            gain = round(self.volume * 65535)
            self._check(self.dll.waveOutSetVolume(self.handle, gain | gain << 16))

    def pump(self):
        if self.playing and self.header and self.header.flags & 1:
            self._clear_buffer()
            self.start_frame = self.frames
            self.playing = False
            self.ended = True

    def close(self):
        self._clear_buffer()
        if self.handle.value:
            self._check(self.dll.waveOutClose(self.handle))
            self.handle = ctypes.c_void_p()
        self.opened = self.playing = False

def can_autoplay_search(engine, queued):
    """An empty waiting queue does not mean there is no current song."""
    if queued:
        return False
    if engine is None:
        return True
    if engine.playing:
        return False
    # Pause/Stop retain the loaded song. Only natural completion yields it.
    try:
        return engine.duration > 0 and engine.position >= engine.duration
    except OSError:
        return False

