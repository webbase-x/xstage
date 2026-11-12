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

# Prevent a ZIP bearing one version while its integrity manifest or UI
# advertises a different build (older distributions accidentally did this).
import json
manifest = json.loads((root / ".engine-ready-manifest.json").read_text(encoding="utf-8-sig"))
assert manifest["version"] == engine.STATUS_VERSION, (
    "Ready manifest version does not match the bundled PC Engine")
assert str(manifest["build"]) == str(engine.STATUS_BUILD), (
    "Ready manifest build does not match the bundled PC Engine")
print("PASS: Ready ZIP manifest matches PC Engine version and build")

assert engine.ffmpeg_binary() is not None, "FFmpeg is missing"
assert engine.fluidsynth_binary() is not None, "FluidSynth is missing"
assert engine.sf_available(), "Default SoundFont is not selected"
assert engine.DEFAULT_SOUNDFONT.is_file(), "SoundFont is not present"

assert engine.AI_LYRICS.available(engine.RUNTIME), (
    "Bundled multilingual Whisper CLI/model unavailable; AI Lyrics menu cannot run")
whisper_exe, whisper_model = engine.AI_LYRICS.resources(engine.RUNTIME)
assert whisper_model.stat().st_size > 100_000_000, "Whisper model is incomplete"
help_test = subprocess.run(
    [str(whisper_exe), "-h"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    timeout=30, creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
output = help_test.stdout.decode("utf-8", errors="replace").casefold()
assert help_test.returncode in (0, 1) and (
    "whisper" in output or "usage" in output or "model" in output), (
        "Whisper bundled executable failed to start with its dependent DLLs")
print("PASS: Whisper CLI and multilingual model respond from bundled offline runtime")


# The real Windows DPAPI native calls must be 64-bit pointer-safe.
# This unit check needs no actual Google account, OAuth file or network.
spec_google = importlib.util.spec_from_file_location("xstage_google_dpapi",
                                                    root / "google_drive.py")
google = importlib.util.module_from_spec(spec_google)
spec_google.loader.exec_module(google)
plain = b"xstage-google-dpapi-roundtrip-2026"
encrypted = google._crypt(plain, False)
assert encrypted != plain and len(encrypted) > len(plain)
assert google._crypt(encrypted, True) == plain
print("PASS: Windows DPAPI encrypts/decrypts Google refresh-token data safely")

# App developer can embed one public Desktop OAuth client for ALL PC users.
# The downloadable archive must NEVER contain anybody's refresh token.
public_client = root / "config" / "google-oauth-client.json"
if public_client.exists():
    import json
    config = json.loads(public_client.read_text(encoding="utf-8-sig"))
    installed = config.get("installed", {})
    assert installed.get("client_id", "").endswith(".apps.googleusercontent.com")
    assert isinstance(installed.get("client_secret"), str) and installed["client_secret"], (
        "Incomplete bundled Google Desktop OAuth client causes HTTP 400"
    )
    assert "refresh_token" not in public_client.read_text(encoding="utf-8-sig")
    assert "access_token" not in public_client.read_text(encoding="utf-8-sig")
    service = google.GoogleDrive(root / ".test-user-google", lambda: str(public_client))
    assert service.status()["configured"] and not service.status()["connected"]
    print("PASS: Bundled app-wide OAuth Desktop ID+Secret complete; no user tokens shipped")
else:
    print("INFO: Owner has not configured BOTH Desktop ID+Secret; import original Desktop JSON once per Windows user")

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
    # A source WAV has no built-in words. Supply REAL timed LRC before
    # expecting the second build to add lyrics; never require invented lyrics.
    input_wav.with_suffix(".lrc").write_text(
        "[00:00.10]ทดสอบคำร้องจริง\\n[00:00.60]ท่อนต่อไป\\n", encoding="utf-8")
    complete = engine.build_library([source_row], "original", {"audio_only": False})
    assert complete["created"] == 0 and complete["lyricsCount"] == 1, complete
    assert len(list((destination / "audio").rglob("*.m4a"))) == 1
    assert len(list((destination / "lyrics").rglob("*.json"))) == 1
    assert (destination / "current.json").is_file()

    print("PASS: Both build actions work: M4A only, then add lyrics without duplicate conversion")

    # End-to-end Windows PC HTTP API test. This exercises exactly the
    # interface behind the two UI confirmation buttons, NOT just build_library.
    import json
    import http.client
    import threading
    import time
    from http.server import ThreadingHTTPServer

    engine.PREFS["workspace"] = str(temp / "browser_pc_real_jobs")
    engine.PREFS["mode"] = "original"
    engine.CANCEL.clear()
    source_row["id"] = 803
    engine.FILE_BY_ID.clear()
    engine.FILE_BY_ID[803] = dict(source_row)
    api_server = ThreadingHTTPServer(("127.0.0.1", 0), engine.Handler)
    engine.PORT = api_server.server_port
    api_thread = threading.Thread(target=api_server.serve_forever, daemon=True)
    api_thread.start()

    def http_json(method, endpoint, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", engine.PORT, timeout=15)
        try:
            request_body = json.dumps(body).encode("utf-8") if body is not None else None
            headers = {"X-XStage-Token": engine.TOKEN}
            if request_body is not None:
                headers["Content-Type"] = "application/json"
            conn.request(method, endpoint, body=request_body, headers=headers)
            reply = conn.getresponse()
            payload = json.loads(reply.read().decode("utf-8"))
            return reply.status, payload
        finally:
            conn.close()

    def do_real_pc_build(only_audio):
        state, answer = http_json("POST", "/api/jobs", {
            "action": "build", "ids": [803], "audio_only": only_audio})
        assert state == 200 and answer.get("id"), (
            "PC confirmation did NOT start real engine job: " + str(answer))
        assert answer.get("total") == 1, (
            "PC Engine did not acknowledge selected source: " + str(answer))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status, snapshot = http_json("GET", "/api/status")
            assert status == 200, snapshot
            job = snapshot["job"]
            if job["id"] == answer["id"] and job["state"] != "running":
                assert job["state"] == "success", (
                    "PC build failed after UI confirmed: " + str(job))
                return job
            time.sleep(0.1)
        raise AssertionError("PC build stays running with no completion within test deadline")

    try:
        unknown_status, unknown_response = http_json("POST", "/api/jobs", {
            "action": "build", "ids": [999999], "audio_only": True})
        assert unknown_status == 400 and "error" in unknown_response, (
            "Missing original must show an immediate, specific error")
        first_http = do_real_pc_build(True)
        assert first_http["result"]["created"] == 1 and first_http["result"]["m4aCount"] == 1
        second_http = do_real_pc_build(False)
        assert second_http["result"]["created"] == 0 and second_http["result"]["lyricsCount"] == 1
        output_dir = temp / "browser_pc_real_jobs" / "songs"
        assert len(list((output_dir / "audio").rglob("*.m4a"))) == 1
        assert len(list((output_dir / "lyrics").rglob("*.json"))) == 1
        assert (output_dir / "current.json").is_file()
        print("PASS: PC browser POST /api/jobs starts & finishes both build modes; "+
              "invalid songs return immediate HTTP 400, outputs and current.json verified")
    finally:
        api_server.shutdown()
        api_server.server_close()
        api_thread.join(timeout=3)

print("Ready bundle integration smoke test passed.")
