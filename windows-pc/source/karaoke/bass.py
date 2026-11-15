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
            raise OSError('ไม่พบ BASS x64 กรุณารัน Install-to-D.cmd เพื่อตรวจและซ่อมส่วนประกอบอัตโนมัติ')
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
        with self.lock:
            if self.stream:
                self.dll.BASS_StreamFree(self.stream)
                self.stream = 0
            for handle in self.fonts:
                self.midi.BASS_MIDI_FontFree(handle)
            self.fonts.clear()
            if self.initialized:
                from .audio_device import release
                release(self.dll, self._device_key)
                self.initialized = False
            if self.dll_directory is not None:
                self.dll_directory.close()
                self.dll_directory = None
