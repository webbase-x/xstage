"""Live Song Studio karaoke: one audio clock, independent backing/SoundFont.

Never saves a preview audio file. Decode original audio to PCM, synthesize MIDI
in memory via bundled FluidSynth, mix per PCM block with live-adjustable gains,
encode one continuous low-latency MP3 stream for the browser. A MIDI-only track
uses the bundled default SoundFont for the original melody so moving the
*selected* SoundFont fader to zero never silences the original MIDI music.
"""
from __future__ import annotations

import array
import ctypes
import ctypes.util
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

AUDIO_SUFFIXES = {".mp3", ".m4a", ".mp4", ".aac", ".wav", ".wma", ".flac", ".ogg", ".oga"}
MIDI_SUFFIXES = {".mid", ".midi", ".kar"}
SAMPLE_RATE = 44100
CHUNK_FRAMES = 2048  # ~46ms: responsive faders/SoundFont changes
MAX_SECONDS = 45 * 60
SAMPLE_BYTES = 4  # signed stereo int16


def matching_sources(item, catalog):
    """Pair exact code/stem in same source directory, not unrelated tracks."""
    selected = Path(item["path"])
    if selected.suffix.lower() not in AUDIO_SUFFIXES | MIDI_SUFFIXES:
        raise ValueError("ไม่รองรับประเภทเพลงนี้ในการทดลองฟังแบบสด")
    if not selected.is_file() or selected.is_symlink():
        raise ValueError("ไม่พบเพลงต้นฉบับที่เลือก")
    same = []
    for row in catalog:
        path = Path(row["path"])
        if (path.parent == selected.parent
                and path.stem.casefold() == selected.stem.casefold()
                and path.is_file() and not path.is_symlink()):
            same.append(path)
    same.sort(key=lambda path: (path != selected, path.suffix.lower()))
    return (next((p for p in same if p.suffix.lower() in AUDIO_SUFFIXES), None),
            next((p for p in same if p.suffix.lower() in MIDI_SUFFIXES), None))


def find_library(runtime):
    if os.name == "nt":
        directory = runtime / "fluidsynth" / "bin"
        for glob in ("libfluidsynth*.dll", "fluidsynth*.dll"):
            for path in sorted(directory.glob(glob)):
                if path.is_file():
                    return str(path)
        raise RuntimeError("ไม่พบ FluidSynth DLL ในแพ็กเกจ PC Ready")
    library = ctypes.util.find_library("fluidsynth")
    if not library:
        raise RuntimeError("ไม่พบ FluidSynth ในระบบ")
    return library


class LiveControls:
    """Mutated by authenticated PC REST API without rebuilding the stream."""
    def __init__(self, music_volume=0.8, synth_volume=0.8,
                 soundfont=None, preset="balanced"):
        self.lock = threading.RLock()
        self.music_volume = float(music_volume)
        self.synth_volume = float(synth_volume)
        self.soundfont = Path(soundfont) if soundfont else None
        self.preset = str(preset)
        self.cancelled = threading.Event()
        self.active = False

    def update(self, *, music_volume=None, synth_volume=None,
               soundfont=None, preset=None):
        with self.lock:
            for key, val in (("music_volume", music_volume),
                             ("synth_volume", synth_volume)):
                if val is not None:
                    try:
                        n = float(val)
                    except (TypeError, ValueError) as exc:
                        raise ValueError("ระดับเสียงไม่ถูกต้อง") from exc
                    if not 0 <= n <= 1 or not __import__("math").isfinite(n):
                        raise ValueError("ระดับเสียงต้องอยู่ระหว่าง 0 ถึง 100%")
                    setattr(self, key, n)
            if preset is not None:
                if preset not in ("balanced", "warm", "bright"):
                    raise ValueError("รูปแบบเสียง MIDI ไม่ถูกต้อง")
                self.preset = preset
            if soundfont is not None:
                candidate = Path(soundfont).expanduser()
                if candidate.suffix.lower() not in (".sf2", ".sf3") or not candidate.is_file():
                    raise ValueError("SoundFont ที่เลือกไม่พบหรือไม่ใช่ .sf2/.sf3")
                self.soundfont = candidate
            return self.snapshot()

    def snapshot(self):
        with self.lock:
            return (self.music_volume, self.synth_volume,
                    self.soundfont, self.preset)


class StreamingSynth:
    """FluidSynth sample-clock MIDI synth, reconfigurable without restart."""
    def __init__(self, midi, soundfont, runtime, preset="balanced"):
        if not midi.is_file() or midi.suffix.lower() not in MIDI_SUFFIXES:
            raise ValueError("ไม่มีไฟล์ MIDI/KAR ที่ใช้ได้")
        if not soundfont or not soundfont.is_file() or soundfont.suffix.lower() not in (".sf2", ".sf3"):
            raise ValueError("กรุณาเลือกไฟล์ SoundFont .sf2/.sf3")
        self.scope = None
        if os.name == "nt" and hasattr(os, "add_dll_directory"):
            self.scope = os.add_dll_directory(str(runtime / "fluidsynth" / "bin"))
        try:
            self.lib = ctypes.CDLL(find_library(runtime))
        except Exception:
            if self.scope:
                self.scope.close()
            raise
        v, i, c, d = ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_double
        defs = {
            "new_fluid_settings": (v, []),
            "fluid_settings_setnum": (i, [v, c, d]),
            "fluid_settings_setint": (i, [v, c, i]),
            "fluid_settings_setstr": (i, [v, c, c]),
            "new_fluid_synth": (v, [v]),
            "fluid_synth_sfload": (i, [v, c, i]),
            "new_fluid_player": (v, [v]),
            "fluid_player_add": (i, [v, c]),
            "fluid_player_play": (i, [v]),
            "fluid_player_get_status": (i, [v]),
            "fluid_synth_write_s16": (i, [v, i, v, i, i, v, i, i]),
            "delete_fluid_player": (None, [v]),
            "delete_fluid_synth": (None, [v]),
            "delete_fluid_settings": (None, [v]),
        }
        for name, (restype, argtypes) in defs.items():
            func = getattr(self.lib, name)
            func.restype, func.argtypes = restype, argtypes
        self.settings = self.synth = self.player = None
        self.font_path = None
        self.preset = None
        try:
            self.settings = self.lib.new_fluid_settings()
            if not self.settings:
                raise RuntimeError("เปิดตั้งค่า FluidSynth ไม่สำเร็จ")
            self.lib.fluid_settings_setnum(self.settings, b"synth.sample-rate", SAMPLE_RATE)
            self.lib.fluid_settings_setnum(self.settings, b"synth.gain", 0.42)
            self.lib.fluid_settings_setint(self.settings, b"synth.polyphony", 256)
            self.lib.fluid_settings_setstr(self.settings, b"player.timing-source", b"sample")
            self.synth = self.lib.new_fluid_synth(self.settings)
            if not self.synth:
                raise RuntimeError("เริ่ม FluidSynth ไม่สำเร็จ")
            self.change_font(soundfont)
            self.change_preset(preset)
            self.player = self.lib.new_fluid_player(self.synth)
            if not self.player or self.lib.fluid_player_add(self.player, os.fsencode(midi)) != 0:
                raise RuntimeError("ไม่สามารถอ่านไฟล์ MIDI/KAR")
            if self.lib.fluid_player_play(self.player) != 0:
                raise RuntimeError("เริ่มเล่น MIDI/KAR ไม่สำเร็จ")
        except Exception:
            self.close()
            raise

    def change_font(self, path):
        path = Path(path)
        if self.font_path == path:
            return
        if not path.is_file() or path.suffix.lower() not in (".sf2", ".sf3"):
            raise ValueError("ไม่พบไฟล์ SoundFont ที่เลือก")
        # Load new soundfont before unloading the old bank, so a failed load
        # does not silence an already playing track.
        loaded = self.lib.fluid_synth_sfload(self.synth, os.fsencode(path), 1)
        if loaded < 0:
            raise RuntimeError("เปลี่ยน SoundFont ไม่สำเร็จ: " + str(path))
        old = getattr(self, "font_id", None)
        if old is not None and hasattr(self.lib, "fluid_synth_sfunload"):
            unload = self.lib.fluid_synth_sfunload
            unload.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
            unload.restype = ctypes.c_int
            unload(self.synth, old, 1)
        self.font_id, self.font_path = loaded, path

    def change_preset(self, preset):
        if preset == self.preset:
            return
        levels = {"balanced": .42, "warm": .36, "bright": .51}
        if preset not in levels:
            raise ValueError("โทนเสียงไม่ถูกต้อง")
        if hasattr(self.lib, "fluid_synth_set_gain"):
            fn = self.lib.fluid_synth_set_gain
            fn.argtypes, fn.restype = [ctypes.c_void_p, ctypes.c_float], None
            fn(self.synth, levels[preset])
        # Reverb/chorus are applied to MIDI timbre, not the original audio.
        for name, on in (("fluid_synth_set_reverb_on", int(preset != "bright")),
                         ("fluid_synth_set_chorus_on", int(preset == "warm"))):
            if hasattr(self.lib, name):
                fn = getattr(self.lib, name)
                fn.argtypes, fn.restype = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int], None
                fn(self.synth, -1, on)
        self.preset = preset

    def next_pcm(self):
        pcm = (ctypes.c_short * (CHUNK_FRAMES * 2))()
        ret = self.lib.fluid_synth_write_s16(
            self.synth, CHUNK_FRAMES, ctypes.cast(pcm, ctypes.c_void_p), 0, 2,
            ctypes.cast(pcm, ctypes.c_void_p), 1, 2)
        if ret != 0:
            raise RuntimeError("FluidSynth สร้างเสียงไม่สำเร็จ")
        return bytes(pcm)

    def ended(self):
        return bool(self.lib.fluid_player_get_status(self.player) == 3)

    def frames(self, cancelled):
        # API preserved for the older tests and callers.
        tail = 0
        while not cancelled.is_set() and tail < SAMPLE_RATE * 2:
            yield self.next_pcm()
            tail = tail + CHUNK_FRAMES if self.ended() else 0

    def close(self):
        if self.player:
            self.lib.delete_fluid_player(self.player)
            self.player = None
        if self.synth:
            self.lib.delete_fluid_synth(self.synth)
            self.synth = None
        if self.settings:
            self.lib.delete_fluid_settings(self.settings)
            self.settings = None
        if self.scope:
            self.scope.close()
            self.scope = None


def blend_pcm(backing, overlay, music_volume, synth_volume):
    """Short PCM blocks can be mixed rapidly with no disk writes or extra deps."""
    if len(backing) != len(overlay):
        raise ValueError("PCM แทร็กดนตรีและ SoundFont ขนาดไม่ตรงกัน")
    if music_volume == 1 and synth_volume == 0:
        return backing
    if music_volume == 0 and synth_volume == 1:
        return overlay
    a, b = array.array("h"), array.array("h")
    a.frombytes(backing)
    b.frombytes(overlay)
    if sys.byteorder != "little":
        a.byteswap()
        b.byteswap()
    out = array.array("h", (
        max(-32768, min(32767, round(x * music_volume + y * synth_volume)))
        for x, y in zip(a, b)
    ))
    if sys.byteorder != "little":
        out.byteswap()
    return out.tobytes()



def read_pcm_block(stream, expected_bytes):
    """Read a whole aligned PCM frame block, even from short-reading pipes.

    Raw FFmpeg pipes can return fewer bytes than requested without EOF. Padding
    each such read with silence causes rhythmic dropouts during playback.
    Only the final true EOF block is padded.
    """
    pieces = []
    remaining = expected_bytes
    while remaining:
        part = stream.read(remaining)
        if not part:
            break
        pieces.append(part)
        remaining -= len(part)
    block = b"".join(pieces)
    if len(block) % SAMPLE_BYTES:
        block = block[:len(block) - (len(block) % SAMPLE_BYTES)]
    if block and len(block) < expected_bytes:
        block += b"\x00" * (expected_bytes - len(block))
    return block


def stream_mp3(*, audio, midi, soundfont, ffmpeg, runtime,
               music_volume=0.8, synth_volume=0.8, controls=None):
    """Return progressively encoded MP3, honoring live controls every ~46ms.

    Single sample clock keeps source music and MIDI in sync. Changes to
    sliders/SF2/SF3/presets affect subsequent blocks, not whole-file render.
    """
    if audio is None and midi is None:
        raise ValueError("ไม่พบเพลงทดลองฟัง")
    if audio and not Path(audio).is_file():
        raise ValueError("ไม่พบไฟล์ดนตรีต้นฉบับ")
    state = controls or LiveControls(music_volume, synth_volume, soundfont)
    default_bank = Path(runtime) / "soundfonts" / "GeneralUser-GS.sf2"
    # MIDI-only music keeps a separate original default-bank voice so
    # muting the custom SoundFont never mutes the original melody.
    baseline_bank = default_bank if default_bank.is_file() else Path(soundfont) if soundfont else None
    base_synth = StreamingSynth(Path(midi), baseline_bank, Path(runtime)) if midi and not audio else None
    overlay_synth = StreamingSynth(Path(midi), Path(soundfont), Path(runtime),
                                   preset=state.snapshot()[3]) if midi else None
    decoder = None
    encoder = None
    writer = None
    bytes_per_block = CHUNK_FRAMES * SAMPLE_BYTES
    try:
        if audio:
            cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
                   "-i", str(audio), "-vn", "-ar", str(SAMPLE_RATE), "-ac", "2",
                   "-f", "s16le", "-acodec", "pcm_s16le", "pipe:1"]
            opts = dict(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, bufsize=0)
            if os.name == "nt":
                opts["creationflags"] = subprocess.CREATE_NO_WINDOW
            decoder = subprocess.Popen(cmd, **opts)
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
               "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "2", "-i", "pipe:0",
               "-vn", "-c:a", "libmp3lame", "-b:a", "192k",
               "-flush_packets", "1", "-f", "mp3", "pipe:1"]
        opts = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, bufsize=0)
        if os.name == "nt":
            opts["creationflags"] = subprocess.CREATE_NO_WINDOW
        encoder = subprocess.Popen(cmd, **opts)
        state.active = True

        def write_audio():
            block_count = 0
            midi_tail = 0
            clock_start = time.monotonic()
            try:
                while not state.cancelled.is_set() and block_count * CHUNK_FRAMES < MAX_SECONDS * SAMPLE_RATE:
                    original = read_pcm_block(decoder.stdout, bytes_per_block) if decoder else b""
                    orig_ended = decoder is None or not original
                    midi_ended = not midi or (overlay_synth and overlay_synth.ended())
                    if orig_ended and midi_ended and (not midi or midi_tail >= SAMPLE_RATE):
                        break
                    if midi_ended:
                        midi_tail += CHUNK_FRAMES
                    else:
                        midi_tail = 0
                    gains = state.snapshot()
                    if base_synth:
                        original = base_synth.next_pcm()
                    if not original:
                        original = b"\x00" * bytes_per_block
                    if overlay_synth:
                        if gains[2] and overlay_synth.font_path != gains[2]:
                            overlay_synth.change_font(gains[2])
                        if gains[3] != overlay_synth.preset:
                            overlay_synth.change_preset(gains[3])
                        extra = overlay_synth.next_pcm()
                    else:
                        extra = b"\x00" * bytes_per_block
                    encoder.stdin.write(blend_pcm(original, extra, gains[0], gains[1]))
                    block_count += 1
                    deadline = clock_start + block_count * CHUNK_FRAMES / SAMPLE_RATE
                    wait = deadline - time.monotonic()
                    if wait > 0:
                        state.cancelled.wait(wait)
            except (BrokenPipeError, OSError):
                pass
            except Exception as exc:
                state.failure = str(exc)
            finally:
                try:
                    encoder.stdin.close()
                except OSError:
                    pass
                if decoder:
                    if decoder.poll() is None:
                        decoder.terminate()
                    decoder.stdout.close()
                if base_synth:
                    base_synth.close()
                if overlay_synth:
                    overlay_synth.close()

        writer = threading.Thread(target=write_audio, daemon=True,
                                  name="xstage-live-mixer")
        writer.start()

        def generator():
            try:
                while not state.cancelled.is_set():
                    chunk = encoder.stdout.read(8192)
                    if not chunk:
                        break
                    yield chunk
                if not state.cancelled.is_set():
                    encoder.wait(timeout=10)
                    if getattr(state, "failure", None):
                        raise RuntimeError("Live audio: " + state.failure)
                    if encoder.returncode:
                        raise RuntimeError("FFmpeg ไม่สามารถเข้ารหัสเสียงสตรีมได้")
            finally:
                state.cancelled.set()
                if encoder.poll() is None:
                    encoder.terminate()
                    try:
                        encoder.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        encoder.kill()
                encoder.stdout.close()
                if writer:
                    writer.join(timeout=4)
                state.active = False
        return generator()
    except Exception:
        state.cancelled.set()
        if encoder and encoder.poll() is None:
            encoder.terminate()
        if decoder and decoder.poll() is None:
            decoder.terminate()
        if base_synth:
            base_synth.close()
        if overlay_synth:
            overlay_synth.close()
        raise
