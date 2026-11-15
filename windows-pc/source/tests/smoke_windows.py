"""Integration checks with real WinMM/MCI/Tk. Plays short, quiet demo sounds."""
from pathlib import Path
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.make_demo import build_demo
from karaoke.playback import WinMidi, MidiPlayer, WavePlayer
from karaoke.ui import KaraokeApp
from karaoke.library import QueueItem


def check(value, message):
    if not value:
        raise AssertionError(message)
    print("PASS", message, flush=True)


def smoke():
    with tempfile.TemporaryDirectory(prefix="newKaraoke_test_") as tmp:
        home = Path(__file__).resolve().parents[1]
        data_dir = Path(tmp) / "data"
        build_demo(Path(tmp) / "fixtures")
        mid = next((Path(tmp) / "fixtures").glob("*.mid"))
        wav = next((Path(tmp) / "fixtures").glob("*.wav"))
        check(len(WinMidi.devices()) > 1, "Windows exposes an actual MIDI output")
        midi = MidiPlayer()
        try:
            midi.load(mid)
            midi.set_volume(0.1)
            midi.play()
            time.sleep(0.08)
            midi.pump()
            check(midi.position > 0, "MIDI clock advances with real output")
            midi.set_key(2)
            midi.set_channel(3, muted=True)
            midi.pause()
            position = midi.position
            time.sleep(0.04)
            check(midi.position == position, "MIDI pause freezes clock")
            midi.seek(15.95)
            midi.play()
            time.sleep(0.08)
            midi.pump()
            check(midi.ended, "MIDI reaches end and silences output")
        finally:
            midi.close()
        media = WavePlayer()
        try:
            media.load(wav)
            check(abs(media.duration - 16) < 0.1, "Windows decodes demo WAV")
            media.set_volume(0.1)
            media.play()
            time.sleep(0.15)
            media.pump()
            check(media.position > 0, "WAV playback advances")
            media.pause()
            media.seek(2)
            media.set_speed(1.1)
            media.play()
            media.stop()
            check(media.position < 0.1, "WAV pause, seek, speed, stop work")
        finally:
            media.close()
        app = KaraokeApp(home, data_dir)
        captured_errors = []
        app.show_error = lambda error: captured_errors.append(str(error))
        try:
            app.update()
            check(len(app.songs.get_children()) == 2, "UI imports both original demo tracks")
            rows = app.library.search()
            midi_song = next(song for song in rows if song["kind"] == "MIDI")
            audio_song = next(song for song in rows if song["kind"] == "AUDIO")
            app.volume_var.set(10)
            app.songs.selection_set(str(midi_song["id"]))
            app.add_selected()
            app.song_queue.add(QueueItem(audio_song["id"], "Test singer", 0, 100))
            app.refresh_queue()
            app.next_song()
            app.update()
            check(app.current_song["id"] == midi_song["id"], "UI starts first queued MIDI")
            check(len(app.song_queue.items) == 1, "Successfully started song is removed from waiting queue")
            app.toggle_stage()
            app.update()
            check(app.stage.winfo_exists(), "Separate singer window opens")
            app.toggle_stage()
            app.update()
            app.exit_stage_fullscreen()
            app.close_stage()
            app.play_pause()
            app.engine.seek(app.engine.duration - 0.01)
            app.play_pause()
            time.sleep(0.04)
            app.update()
            check(app.current_song["id"] == audio_song["id"], "Automatic next switches from MIDI to WAV")
            check(bool(app.lyrics.lines), "WAV loads matching enhanced LRC")
            app.key_var.set(4)
            app.apply_key()
            app.stop()
            app.open_mixer()
            app.update()
            check(not captured_errors, "UI playback and mixer produce no errors: " + str(captured_errors))
        finally:
            app.close_app()
        restored = KaraokeApp(home, data_dir)
        try:
            restored.update()
            check(restored.library.count() == 2, "Song index survives app restart")
        finally:
            restored.close_app()
    print("WINDOWS SMOKE TEST COMPLETE", flush=True)


if __name__ == "__main__":
    smoke()
