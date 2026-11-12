"""Windows integration smoke test: portable runtime + MIDI + audio->M4A, no network."""
import importlib.util
import os
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit("Usage: python test_songstudio_ready.py path/to/Ready/Bundle")
root = Path(sys.argv[1]).resolve()
if not (root / ".engine-ready-manifest.json").is_file():
    raise SystemExit("No ready bundle manifest present")

spec = importlib.util.spec_from_file_location("songstudio_ready_engine", root / "engine.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)

assert engine.ffmpeg_binary() is not None, "FFmpeg is missing"
assert engine.fluidsynth_binary() is not None, "FluidSynth is missing"
assert engine.sf_available(), "Default SoundFont is not selected"
assert engine.DEFAULT_SOUNDFONT.is_file(), "SoundFont is not present"

with tempfile.TemporaryDirectory(prefix="xstage-songstudio-ready-") as scratch:
    temp = Path(scratch)
    input_wav = temp / "demo.wav"
    with wave.open(str(input_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"\x00\x00" * 22050)
    row_audio = {"path": str(input_wav), "title": "demo", "artist": "test"}
    audio_out = temp / "audio.m4a"
    engine.convert(row_audio, audio_out)
    assert audio_out.stat().st_size > 1000
    print("PASS: WAV -> M4A using portable FFmpeg")

    # Standard MIDI File, one C4 note for quarter note at tempo 120 bpm
    ev = bytes.fromhex(
        "00 C0 00"
        " 00 90 3C 64"
        " 83 60 80 3C 00"
        " 00 FF 2F 00"
    )
    midi = b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480)
    midi += b"MTrk" + struct.pack(">I", len(ev)) + ev
    midi_file = temp / "test.mid"
    midi_file.write_bytes(midi)
    midi_out = temp / "midi.m4a"
    engine.convert({"path": str(midi_file), "title": "MIDI demo"}, midi_out)
    assert midi_out.stat().st_size > 1000
    print("PASS: MIDI -> SoundFont synth -> WAV -> M4A using portable FluidSynth/FFmpeg")

    probe = subprocess.run([
        engine.ffmpeg_binary().replace("ffmpeg.exe", "ffprobe.exe"),
        "-v", "error", "-show_entries", "stream=codec_name",
        "-of", "default=noprint_wrappers=1", str(midi_out)
    ], capture_output=True, text=True, check=True)
    assert "aac" in probe.stdout, f"Output is not AAC: {probe.stdout}"
    print("PASS: Portable M4A output contains AAC codec")
    assert engine.ai_available(), "Offline bundled AI model/runtime must be present"
    ai_output = temp / "ai-instrumental.m4a"
    engine.separate_ai(row_audio, ai_output, preview=False)
    vocal_output = temp / "ai-instrumental - vocals.m4a"
    assert ai_output.stat().st_size > 1000, "AI instrumental M4A missing"
    assert vocal_output.stat().st_size > 1000, "AI vocals M4A missing"
    print("PASS: Offline AI separated synthetic WAV into instrumental + vocals M4A")
print("Ready bundle integration smoke test passed.")
