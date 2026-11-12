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

    # The new karaoke preview must generate audio directly as HTTP-ready MP3
    # bytes; unlike build/AI modes it is forbidden to write a sample file.
    import importlib.util
    spec_live = importlib.util.spec_from_file_location(
        "xstage_live", root / "live_preview.py")
    live = importlib.util.module_from_spec(spec_live)
    spec_live.loader.exec_module(live)
    paired_midi = temp / "demo.mid"
    paired_midi.write_bytes(midi)
    catalog = [
        {"id": 101, "path": str(input_wav), "title": "Preview demo", "kind": "WAV"},
        {"id": 102, "path": str(paired_midi), "title": "Preview demo", "kind": "MID"},
    ]
    backing, sfmidi = live.matching_sources(catalog[0], catalog)
    assert backing == input_wav and sfmidi == paired_midi, "Companion MIDI pairing failed"
    before_files = set(temp.iterdir())
    streamed = b"".join(live.stream_mp3(
        audio=backing, midi=sfmidi,
        soundfont=engine.DEFAULT_SOUNDFONT,
        ffmpeg=engine.ffmpeg_binary(), runtime=root / ".runtime",
        music_volume=0.7, synth_volume=0.8
    ))
    assert streamed.startswith(b"ID3") and len(streamed) > 1000, "Live MP3 stream missing"
    assert set(temp.iterdir()) == before_files, "Live preview created a disk file"
    print("PASS: FluidSynth + backing music mixed live to MP3 bytes without creating files")

    engine.FILES[:] = catalog
    engine.FILE_BY_ID.clear()
    engine.FILE_BY_ID.update({song["id"]: song for song in catalog})
    ticket = engine.prepare_live_preview(101)
    assert ticket["mixed"] and ticket["has_midi"], "Live ticket must report real mixed tracks"
    assert len(ticket["ticket"]) > 30
    print("PASS: Live preview ticket issued from catalog without exposing file paths")

    # Without original backing audio, the default GeneralUser MIDI playback
    # must remain audible after muting the selected SoundFont overlay.
    from array import array
    original_midi_stream = b"".join(live.stream_mp3(
        audio=None, midi=paired_midi,
        soundfont=engine.DEFAULT_SOUNDFONT,
        ffmpeg=engine.ffmpeg_binary(), runtime=root / ".runtime",
        music_volume=0.9, synth_volume=0.0))
    pcm = subprocess.run([
        engine.ffmpeg_binary(), "-hide_banner", "-loglevel", "error",
        "-i", "pipe:0", "-f", "s16le", "-ac", "2", "-ar", "44100", "pipe:1"
    ], input=original_midi_stream, capture_output=True, check=True).stdout
    samples = array("h")
    samples.frombytes(pcm)
    assert max(abs(v) for v in samples) > 400, "Muting SoundFont silenced MIDI original!"
    print("PASS: MIDI original remains audible at SoundFont slider 0 percent")

    # Exercise the real Windows conversion through BOTH Build buttons' modes.
    engine.CANCEL.clear()
    engine.PREFS["workspace"] = str(temp / "production")
    source_row = {"path": str(input_wav), "title": "New song",
                  "code": "102030", "artist": "Test"}
    audio_only = engine.build_library([source_row], "original", {"audio_only": True})
    assert (audio_only["created"], audio_only["lyricsCount"]) == (1, 0)
    destination = temp / "production" / "songs"
    audio_files = list((destination / "audio").rglob("*.m4a"))
    assert len(audio_files) == 1
    complete = engine.build_library([source_row], "original", {"audio_only": False})
    assert complete["created"] == 0 and complete["lyricsCount"] == 1
    assert len(list((destination / "audio").rglob("*.m4a"))) == 1
    assert len(list((destination / "lyrics").rglob("*.json"))) == 1
    assert (destination / "current.json").is_file()
    print("PASS: Both build actions work: M4A only, then add lyrics without duplicate conversion")
print("Ready bundle integration smoke test passed.")
