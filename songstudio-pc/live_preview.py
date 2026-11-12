"""Live Song Studio preview. Streaming FFmpeg MP3 + FluidSynth MIDI in RAM.

No output WAV/M4A/MP3 files. Backing audio and its same-folder same-stem
MIDI/KAR companion are mixed in one synchronized MP3 stream. Audio-only
tracks are played as-is (without claiming SoundFont synthesis).
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import subprocess
import threading
from pathlib import Path

AUDIO_SUFFIXES = {".mp3", ".m4a", ".mp4", ".aac", ".wav", ".wma", ".flac", ".ogg", ".oga"}
MIDI_SUFFIXES = {".mid", ".midi", ".kar"}
SAMPLE_RATE = 44100
CHUNK_FRAMES = 4096
MAX_SECONDS = 45 * 60


def matching_sources(item, catalog):
    """Only accept sources from the scanned catalog; pair exact stem in folder."""
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
    audio = next((path for path in same if path.suffix.lower() in AUDIO_SUFFIXES), None)
    midi = next((path for path in same if path.suffix.lower() in MIDI_SUFFIXES), None)
    return audio, midi


def find_library(runtime):
    if os.name == "nt":
        directory = runtime / "fluidsynth" / "bin"
        for glob in ("libfluidsynth*.dll", "fluidsynth*.dll"):
            for candidate in sorted(directory.glob(glob)):
                if candidate.is_file():
                    return str(candidate)
        raise RuntimeError("ไม่พบ FluidSynth DLL ในแพ็กเกจ PC Ready")
    library = ctypes.util.find_library("fluidsynth")
    if not library:
        raise RuntimeError("ไม่พบ FluidSynth ในระบบ")
    return library


class StreamingSynth:
    """Generate sample-clock-synchronized stereo PCM without audio file."""
    def __init__(self, midi, soundfont, runtime):
        if not midi.is_file() or midi.suffix.lower() not in MIDI_SUFFIXES:
            raise ValueError("ไม่มีไฟล์ MIDI/KAR ที่ใช้ได้")
        if not soundfont.is_file() or soundfont.suffix.lower() not in (".sf2", ".sf3"):
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
        specs = {
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
        for name, (restype, args) in specs.items():
            fn = getattr(self.lib, name)
            fn.restype, fn.argtypes = restype, args
        self.settings = None
        self.synth = None
        self.player = None
        try:
            self.settings = self.lib.new_fluid_settings()
            if not self.settings:
                raise RuntimeError("เปิดตั้งค่า FluidSynth ไม่สำเร็จ")
            self.lib.fluid_settings_setnum(self.settings, b"synth.sample-rate", SAMPLE_RATE)
            self.lib.fluid_settings_setnum(self.settings, b"synth.gain", 0.45)
            self.lib.fluid_settings_setint(self.settings, b"synth.polyphony", 256)
            self.lib.fluid_settings_setstr(self.settings, b"player.timing-source", b"sample")
            self.synth = self.lib.new_fluid_synth(self.settings)
            if not self.synth or self.lib.fluid_synth_sfload(self.synth, os.fsencode(soundfont), 1) < 0:
                raise RuntimeError("SoundFont โหลดไม่สำเร็จ")
            self.player = self.lib.new_fluid_player(self.synth)
            if not self.player or self.lib.fluid_player_add(self.player, os.fsencode(midi)) != 0:
                raise RuntimeError("ไม่สามารถอ่านไฟล์ MIDI/KAR")
            if self.lib.fluid_player_play(self.player) != 0:
                raise RuntimeError("เริ่มเล่น MIDI/KAR ไม่สำเร็จ")
        except Exception:
            self.close()
            raise

    def frames(self, cancelled):
        pcm = (ctypes.c_short * (CHUNK_FRAMES * 2))()
        produced, tail = 0, 0
        while not cancelled.is_set() and produced < MAX_SECONDS * SAMPLE_RATE:
            result = self.lib.fluid_synth_write_s16(
                self.synth, CHUNK_FRAMES, ctypes.cast(pcm, ctypes.c_void_p), 0, 2,
                ctypes.cast(pcm, ctypes.c_void_p), 1, 2)
            if result != 0:
                raise RuntimeError("FluidSynth สร้างเสียงไม่สำเร็จ")
            yield bytes(pcm)
            produced += CHUNK_FRAMES
            if self.lib.fluid_player_get_status(self.player) == 3:
                tail += CHUNK_FRAMES
                if tail >= SAMPLE_RATE * 2:
                    break

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


def stream_mp3(*, audio, midi, soundfont, ffmpeg, runtime, music_volume=0.8, synth_volume=0.8):
    """Return progressive MP3 bytes, mixing backing+SoundFont with FFmpeg."""
    if audio is None and midi is None:
        raise ValueError("ไม่พบเพลงทดลองฟัง")
    if audio and not audio.is_file():
        raise ValueError("ไม่พบไฟล์ดนตรี")
    music_volume = max(0, min(1, float(music_volume)))
    synth_volume = max(0, min(1, float(synth_volume)))
    synth = StreamingSynth(midi, soundfont, runtime) if midi else None
    ffargs = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin"]
    if synth:
        ffargs += ["-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "2", "-i", "pipe:0"]
    if audio:
        ffargs += ["-re", "-i", str(audio)]
    if audio and synth:
        ffargs += ["-filter_complex",
                   f"[0:a]volume={synth_volume:.3f}[sf];[1:a]volume={music_volume:.3f}[music];"
                   "[music][sf]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[out]",
                   "-map", "[out]"]
    else:
        ffargs += ["-af", f"volume={(music_volume if audio else synth_volume):.3f}"]
    ffargs += ["-vn", "-ar", str(SAMPLE_RATE), "-ac", "2", "-c:a", "libmp3lame",
               "-b:a", "192k", "-f", "mp3", "pipe:1"]
    opts = dict(stdin=subprocess.PIPE if synth else subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if os.name == "nt":
        opts["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        process = subprocess.Popen(ffargs, **opts)
    except Exception:
        if synth:
            synth.close()
        raise
    cancelled = threading.Event()
    failed = []

    def feed_synth():
        try:
            for frame in synth.frames(cancelled):
                if cancelled.is_set():
                    break
                process.stdin.write(frame)
        except (BrokenPipeError, OSError):
            pass
        except Exception as exc:
            failed.append(exc)
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass
            synth.close()

    worker = threading.Thread(target=feed_synth, daemon=True,
                              name="songstudio-fluid-live") if synth else None
    if worker:
        worker.start()

    def generator():
        try:
            while not cancelled.is_set():
                chunk = process.stdout.read(32768)
                if not chunk:
                    break
                yield chunk
            process.wait(timeout=10)
            if failed:
                raise failed[0]
            if process.returncode not in (0, None):
                raise RuntimeError("FFmpeg Live Preview ไม่สำเร็จ")
        finally:
            cancelled.set()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
            process.stdout.close()
            if worker:
                worker.join(timeout=3)
    return generator()
