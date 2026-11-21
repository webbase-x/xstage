"""BASSMIDI output: float mixing, sinc interpolation, layered SoundFonts.

Official native libraries and SoundFonts are installed separately. The MIDI
scheduler still owns tempo, transpose, seek, mixer and the lyrics clock.
The decode path allows offline PCM validation without an audio device.
"""
from __future__ import annotations
import ctypes
import os
import struct
import threading
from pathlib import Path
from .soundfont import normalize_audio
from .audio_auto import resolve_options

BASS_SAMPLE_FLOAT = 0x100
BASS_STREAM_DECODE = 0x200000
BASS_UNICODE = 0x80000000
BASS_CONFIG_BUFFER = 0
BASS_CONFIG_UPDATEPERIOD = 1
BASS_ATTRIB_BUFFER = 13
BASS_ATTRIB_MIDI_VOICES = 0x12003
BASS_ATTRIB_MIDI_SRC = 0x12006
BASS_MIDI_EVENTS_RAW = 0x10000
# BASSMIDI 2.4 native events, scoped to one MIDI channel or one drum key.
MIDI_EVENT_CUTOFF = 25
MIDI_EVENT_RESONANCE = 26
MIDI_EVENT_DRUM_CUTOFF = 55
MIDI_EVENT_DRUM_RESONANCE = 56
MIDI_EVENT_DRUM_LEVEL = 57
UINT = ctypes.c_uint32
BOOL = ctypes.c_int
PTR = ctypes.c_void_p


class Font(ctypes.Structure):
    _fields_ = [('font', UINT), ('preset', ctypes.c_int), ('bank', ctypes.c_int)]


class FontEx(ctypes.Structure):
    _fields_ = [('font', UINT)] + [(n, ctypes.c_int) for n in ('spreset','sbank','dpreset','dbank','dbanklsb')]


class BassSynth:
    def __init__(self, native: Path, soundfont: Path | None = None, *, settings=None, decode=False, bindings=None):
        if ctypes.sizeof(ctypes.c_void_p) != 8:
            raise OSError('BASS backend นี้ต้องใช้ Python/โปรแกรม x64')
        self.options = normalize_audio(settings if settings is not None else
                                       {'soundfont': str(soundfont) if soundfont else ''}, require_files=True)
        self.options = resolve_options(self.options)
        from .font_mapping import font_entries, extended_entries
        mapping = {} if (settings or {}).get('soundfont_follow_song', False) else (settings or {}).get('instrument_fonts', {})
        # Reject stale mappings before acquiring any native audio resources.
        mapping_rows = extended_entries(self.options, list(range(len(self.options['fonts']))), mapping) if mapping else None
        self.stream = 0
        self.native = Path(native).resolve()
        self._fx_library = None
        self._channel_processors = {}
        self._font_config = None
        self._font_count = 0
        self.fonts = []
        self.initialized = False
        self.decode = decode
        self.lock = threading.RLock()
        self.dll_directory = None
        self.device = 0
        if bindings is not None:  # dependency injection for native ABI and failure-path tests
            self.dll, self.midi = bindings
        else:
            native = Path(native).resolve()
            if os.name == 'nt':
                for name in ('bass.dll', 'bassmidi.dll'):
                    self.validate_dll(native / name)
                self.dll_directory = os.add_dll_directory(str(native))
                try:
                    self.dll = ctypes.WinDLL(str(native / 'bass.dll'))
                    self.midi = ctypes.WinDLL(str(native / 'bassmidi.dll'))
                except Exception:
                    self.dll_directory.close()
                    raise
            elif decode:  # offline verification only; desktop remains Windows
                self.dll = ctypes.CDLL(str(native / 'libbass.so'), mode=ctypes.RTLD_GLOBAL)
                self.midi = ctypes.CDLL(str(native / 'libbassmidi.so'))
            else:
                raise OSError('เล่น SoundFont ผ่านอุปกรณ์เสียงได้บน Windows')
        try:
            self._bind()
            # Device 0 is BASS's no-sound device for offline decoding.
            from .audio_device import acquire
            self._device_key, self.device = acquire(self.dll, decode)
            self.initialized = True
            self.device = self.dll.BASS_GetDevice()
            if not decode:
                # BASS defaults to a 100ms refill period, longer than our
                # 40-80ms live MIDI buffers. Refill every 10ms, even when
                # retaining settings from an older installation.
                self.check(self.dll.BASS_SetConfig(BASS_CONFIG_UPDATEPERIOD, 10), 'ตั้งรอบเติมเสียง')
                # Set before creating the stream: its capacity caps BUFFER.
                self.check(self.dll.BASS_SetConfig(BASS_CONFIG_BUFFER, 500), 'เตรียมบัฟเฟอร์เสียง')
            flags = BASS_SAMPLE_FLOAT | (BASS_STREAM_DECODE if decode else 0)
            self.stream = self.midi.BASS_MIDI_StreamCreate(16, flags, 48000)
            self.check(self.stream, 'สร้างตัวสังเคราะห์เสียง')
            self.check(self.dll.BASS_ChannelSetAttribute(self.stream, BASS_ATTRIB_MIDI_SRC, self.options['quality']), 'ตั้งคุณภาพเสียง')
            self.check(self.dll.BASS_ChannelSetAttribute(self.stream, BASS_ATTRIB_MIDI_VOICES, self.options['voices']), 'ตั้งจำนวนเสียง')
            if not decode:
                self.check(self.dll.BASS_ChannelSetAttribute(self.stream, BASS_ATTRIB_BUFFER, self.options['buffer_ms'] / 1000), 'ตั้งบัฟเฟอร์')
            for row in self.options['fonts']:
                filename = str(Path(row['path']).resolve())
                data = ctypes.create_unicode_buffer(filename) if os.name == 'nt' else ctypes.create_string_buffer(filename.encode('utf-8'))
                handle = self.midi.BASS_MIDI_FontInit(ctypes.cast(data, PTR), BASS_UNICODE if os.name == 'nt' else 0)
                self.check(handle, f"โหลด SoundFont {Path(filename).name}")
                self.fonts.append(handle)
                self.check(self.midi.BASS_MIDI_FontSetVolume(handle, 10 ** (row['gain_db'] / 20)), 'ตั้งระดับเสียง SoundFont')
            if mapping_rows is not None:
                entries = [(self.fonts[row[0]], *row[1:]) for row in mapping_rows]
                config = (FontEx * len(entries))(*(FontEx(*entry) for entry in entries))
                count = len(config) | 0x1000000  # BASS_MIDI_FONT_EX
            else:
                entries = font_entries(self.options, self.fonts, mapping)
                config = (Font * len(entries))(*(Font(*entry) for entry in entries))
                count = len(config)
            self.check(self.midi.BASS_MIDI_StreamSetFonts(self.stream, config, count), 'จัดลำดับ SoundFont')
            self._font_config = config
            self._font_count = count
            self._apply_effects()
            if not decode:
                self.check(self.dll.BASS_ChannelPlay(self.stream, False), 'เริ่มระบบเสียง')
        except Exception:
            self.close()
            raise

    @staticmethod
    def validate_dll(path):
        if not path.is_file():
            raise OSError(f'ไม่พบ {path.name} (BASS x64) ที่ {path} กรุณาติดตั้ง X-Stage Karaoke PC รุ่นที่รวมระบบเสียงให้ครบถ้วนอีกครั้ง')
        try:
            with path.open('rb') as stream:
                if stream.read(2) != b'MZ':
                    raise ValueError()
                stream.seek(0x3c)
                pe = struct.unpack('<I', stream.read(4))[0]
                stream.seek(pe)
                if stream.read(4) != b'PE\0\0' or struct.unpack('<H', stream.read(2))[0] != 0x8664:
                    raise ValueError()
        except (ValueError, struct.error):
            raise OSError(f'{path.name}: ต้องเป็น DLL Windows x64 ทางการ') from None

    def _bind(self):
        signatures = {
            'BASS_SetConfig': ([UINT, UINT], BOOL),
            'BASS_Init': ([ctypes.c_int, UINT, UINT, PTR, PTR], BOOL),
            'BASS_GetDevice': ([], UINT), 'BASS_SetDevice': ([UINT], BOOL),
            'BASS_ErrorGetCode': ([], ctypes.c_int), 'BASS_Free': ([], BOOL),
            'BASS_ChannelPlay': ([UINT, BOOL], BOOL), 'BASS_StreamFree': ([UINT], BOOL),
            'BASS_ChannelSetAttribute': ([UINT, UINT, ctypes.c_float], BOOL),
            'BASS_ChannelGetData': ([UINT, PTR, UINT], UINT),
        }
        midi_signatures = {
            'BASS_MIDI_StreamCreate': ([UINT, UINT, UINT], UINT),
            'BASS_MIDI_FontInit': ([PTR, UINT], UINT),
            'BASS_MIDI_FontFree': ([UINT], BOOL),
            'BASS_MIDI_FontSetVolume': ([UINT, ctypes.c_float], BOOL),
            'BASS_MIDI_StreamSetFonts': ([UINT, PTR, UINT], BOOL),
            'BASS_MIDI_StreamEvents': ([UINT, UINT, PTR, UINT], UINT),
            'BASS_MIDI_StreamEvent': ([UINT, UINT, UINT, UINT], BOOL),
            'BASS_MIDI_StreamGetChannel': ([UINT, UINT], UINT),
        }
        for dll, table in ((self.dll, signatures), (self.midi, midi_signatures)):
            for name, (args, result) in table.items():
                fn = getattr(dll, name)
                fn.argtypes, fn.restype = args, result

    def check(self, result, operation='ประมวลผลเสียง'):
        if not result:
            code = self.dll.BASS_ErrorGetCode()
            detail = ' • มีระบบ BASS ใช้งานอยู่ กรุณาปิดการทดลองเสียงก่อน' if code == 14 else ''
            raise OSError(f'{operation} ไม่สำเร็จ (BASS {code}){detail}')

    def _raw(self, data):
        if self.stream and data:
            buffer = ctypes.create_string_buffer(data)
            count = self.midi.BASS_MIDI_StreamEvents(self.stream, BASS_MIDI_EVENTS_RAW, buffer, len(data))
            if count == 0xffffffff:
                self.check(0)

    def _apply_effects(self, channels=range(16)):
        if self.options['effects_mode'] == 'custom':
            for channel in channels:
                self._raw(bytes([0xb0 | channel, 91, self.options['reverb'],
                                 0xb0 | channel, 93, self.options['chorus']]))

    def send(self, data):
        with self.lock:
            # The scheduler sends one complete standard MIDI message at a time.
            if self.options['effects_mode'] == 'custom' and len(data) == 3 and data[0] & 0xf0 == 0xb0:
                if data[1] in (91, 93):
                    data = bytes([data[0], data[1], self.options['reverb' if data[1] == 91 else 'chorus']])
                self._raw(data)
                if data[1] == 121:
                    self._apply_effects([data[0] & 15])
            else:
                self._raw(data)

    def set_channel_tone(self, channel, cutoff=64, resonance=64):
        """Apply a SoundFont low-pass tone to ONE MIDI channel (0..15)."""
        from .instrument_tone import value
        if type(channel) is not int or not 0 <= channel < 16:
            raise ValueError('ช่อง MIDI ต้องอยู่ระหว่าง 1–16')
        cutoff = value(cutoff, 'Cutoff')
        resonance = value(resonance, 'Resonance')
        with self.lock:
            if not self.stream:
                raise OSError('ตัวสังเคราะห์เสียงไม่ได้เปิด')
            for event, number in ((MIDI_EVENT_CUTOFF, cutoff),
                                  (MIDI_EVENT_RESONANCE, resonance)):
                self.check(self.midi.BASS_MIDI_StreamEvent(
                    self.stream, channel, event, number), 'ปรับโทนเสียงเครื่องดนตรี')

    def set_drum_tone(self, note, cutoff=64, resonance=64, level=127):
        """Apply per-key drum filter/level on GM percussion channel 10."""
        from .instrument_tone import value
        note = value(note, 'หมายเลขกลอง')
        cutoff = value(cutoff, 'Cutoff')
        resonance = value(resonance, 'Resonance')
        level = value(level, 'Level')
        with self.lock:
            if not self.stream:
                raise OSError('ตัวสังเคราะห์เสียงไม่ได้เปิด')
            for event, number in ((MIDI_EVENT_DRUM_CUTOFF, cutoff),
                                  (MIDI_EVENT_DRUM_RESONANCE, resonance),
                                  (MIDI_EVENT_DRUM_LEVEL, level)):
                parameter = note | (number << 8)
                self.check(self.midi.BASS_MIDI_StreamEvent(
                    self.stream, 9, event, parameter), 'ปรับโทนเสียงกลอง')

    def _load_fx_library(self):
        if self._fx_library is not None:
            return self._fx_library
        path = (self.native / 'bass_fx.dll' if os.name == 'nt'
                else self.native / 'libbass_fx.so')
        if os.name == 'nt':
            self.validate_dll(path)
            self._fx_library = ctypes.WinDLL(str(path))
        elif self.decode:
            self._fx_library = ctypes.CDLL(str(path))
        else:
            raise OSError('EQ รายช่อง MIDI ใช้ได้บน Windows ผ่าน SoundFont')
        # Loading the add-on before BASS_ChannelSetFX registers its FX types.
        getter = self._fx_library.BASS_FX_GetVersion
        getter.argtypes = []
        getter.restype = UINT
        version = getter()
        if version >> 16 != 0x204:
            self._fx_library = None
            raise OSError('bass_fx.dll ต้องเป็น BASS FX 2.4')
        return self._fx_library

    def _remove_channel_eq(self, channel):
        item = self._channel_processors.pop(channel, None)
        if item is not None:
            handle, processor = item
            try:
                processor.close()
            finally:
                # A MIDI channel stream is owned by its parent. Explicitly free
                # idle channels to release CPU when the user returns to Flat.
                self.dll.BASS_StreamFree(handle)

    def set_channel_eq(self, channel, state):
        """Live 31-band FX on the dry mix of exactly one BASSMIDI channel.

        BASSMIDI_StreamGetChannel does not create a new MIDI clock. Do not
        allocate channel streams for Flat/Bypass; up to 16 can be enabled.
        """
        from .graphic_eq import flat, validate
        from .parametric_eq import Processor
        from types import SimpleNamespace
        if type(channel) is not int or not 0 <= channel < 16:
            raise ValueError('ช่อง MIDI ต้องอยู่ระหว่าง 1–16')
        state = validate(state)
        with self.lock:
            if not self.stream:
                raise OSError('ตัวสังเคราะห์เสียงไม่ได้เปิด')
            if state['bypass'] or state == flat():
                self._remove_channel_eq(channel)
                return
            current = self._channel_processors.get(channel)
            if current is not None:
                current[1].set(state)
                return
            # Do not alter master stream effects, audio device or other voices.
            self._load_fx_library()
            handle = self.midi.BASS_MIDI_StreamGetChannel(self.stream, channel)
            self.check(handle, 'สร้างช่องเสียง MIDI สำหรับ EQ')
            wrapper = SimpleNamespace(dll=self.dll, stream=handle, fx=self._fx_library)
            try:
                processor = Processor(wrapper, graphic=True, rate_override=48000)
                try:
                    processor.set(state)
                except BaseException:
                    processor.close()
                    raise
            except BaseException:
                self.dll.BASS_StreamFree(handle)
                raise
            self._channel_processors[channel] = (handle, processor)

    def _release_channel_eq(self):
        # Avoid orphan FX handles during an offline song change or shutdown.
        for channel in tuple(self._channel_processors):
            self._remove_channel_eq(channel)

    def reset(self):
        with self.lock:
            if self.stream:
                for channel in range(16):
                    self._raw(bytes([0xb0 | channel, 64, 0, 0xb0 | channel, 120, 0, 0xb0 | channel, 123, 0]))
                self._apply_effects()

    def start_offline_song(self):
        """Fresh MIDI stream per song while keeping the SoundFont handles.

        Prevent inherited instruments, controllers and reverb tails.
        """
        if not self.decode:
            raise ValueError('ใช้ได้เฉพาะตัวเรนเดอร์แบบ Offline')
        with self.lock:
            self._release_channel_eq()
            if self.stream:
                self.check(self.dll.BASS_StreamFree(self.stream), 'ปิด MIDI Stream เพลงก่อน')
                self.stream = 0
            self.stream = self.midi.BASS_MIDI_StreamCreate(
                16, BASS_SAMPLE_FLOAT | BASS_STREAM_DECODE, 48000)
            self.check(self.stream, 'เตรียม MIDI Stream เพลงใหม่')
            self.check(self.dll.BASS_ChannelSetAttribute(
                self.stream, BASS_ATTRIB_MIDI_SRC, self.options['quality']), 'ตั้งคุณภาพเสียง')
            self.check(self.dll.BASS_ChannelSetAttribute(
                self.stream, BASS_ATTRIB_MIDI_VOICES, self.options['voices']), 'ตั้งจำนวนเสียง')
            self.check(self.midi.BASS_MIDI_StreamSetFonts(
                self.stream, self._font_config, self._font_count), 'เลือก SoundFont เดิม')
            self._apply_effects()

    def render(self, frames):
        """Return interleaved stereo float32 PCM, for offline testing/export."""
        if not self.decode:
            raise ValueError('render ใช้กับโหมด offline เท่านั้น')
        if not 1 <= frames <= 48000 * 10:
            raise ValueError('จำนวนเฟรมไม่ถูกต้อง')
        with self.lock:
            if not self.stream:
                raise OSError('ตัวสังเคราะห์เสียงถูกปิดแล้ว')
            output = (ctypes.c_float * (frames * 2))()
            size = self.dll.BASS_ChannelGetData(self.stream, output, ctypes.sizeof(output))
            if size == 0xffffffff:
                self.check(0, 'ถอดเสียง')
            return bytes(output)[:size]

    def close(self):
        # Best-effort teardown: a failing FX processor must not strand the
        # MIDI stream, SoundFonts or the shared audio-device reference.
        with self.lock:
            first_error = None

            def cleanup(operation):
                nonlocal first_error
                try:
                    operation()
                except Exception as exc:
                    if first_error is None:
                        first_error = exc

            cleanup(self._release_channel_eq)
            if self.stream:
                stream = self.stream
                self.stream = 0
                cleanup(lambda: self.dll.BASS_StreamFree(stream))
            for handle in self.fonts:
                cleanup(lambda handle=handle: self.midi.BASS_MIDI_FontFree(handle))
            self.fonts.clear()
            if self.initialized:
                self.initialized = False
                from .audio_device import release
                cleanup(lambda: release(self.dll, self._device_key))
            if self.dll_directory is not None:
                directory = self.dll_directory
                self.dll_directory = None
                cleanup(directory.close)
            if first_error is not None:
                raise first_error
