"""Windows/portable audio regression: Song Studio codec fallback uses bundled FFmpeg."""
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch, MagicMock

from karaoke import studio_audio


class SongStudioAudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.song = self.root / "เพลงทดสอบ.m4a"
        self.song.write_bytes(b"original-audio-content" * 300)
        self.old = self.song.read_bytes()

    def test_windows_native_codec_used_without_transcode(self):
        native = MagicMock()
        with patch("karaoke.playback.MediaPlayer", return_value=native):
            with patch("karaoke.studio_audio._decode_pcm",
                       side_effect=AssertionError("should not transcode")):
                player = studio_audio.SongStudioAudioPlayer()
                player.load(self.song)
                self.assertFalse(player.fallback_used)
                player.play()
                native.play.assert_called_once_with()
                player.close()
                native.close.assert_called_once_with()

    def test_missing_windows_codec_falls_back_to_pcm_player(self):
        native = MagicMock()
        native.load.side_effect = OSError("MCI codec unavailable")
        pcm = MagicMock()
        with patch("karaoke.playback.MediaPlayer", return_value=native), \
             patch("karaoke.playback.WavePlayer", return_value=pcm), \
             patch("karaoke.studio_audio._decode_pcm", return_value=self.root / "audio.wav"):
            player = studio_audio.SongStudioAudioPlayer()
            player.load(self.song)
            self.assertTrue(player.fallback_used)
            native.close.assert_called_once()
            pcm.load.assert_called_once_with(self.root / "audio.wav")
            player.play()
            pcm.play.assert_called_once()
            player.close()
            pcm.close.assert_called_once()
        self.assertEqual(self.song.read_bytes(), self.old)

    def test_ffmpeg_is_bundled_and_cached_per_source_revision(self):
        output = self.root / "cache"
        def render(command, **kwargs):
            self.assertIn("-map", command)
            self.assertEqual(command[-2], "-f")
            target = Path(command[-1])
            with wave.open(str(target), "wb") as wav:
                wav.setnchannels(2)
                wav.setsampwidth(2)
                wav.setframerate(44100)
                wav.writeframes(b"\\0\\0" * 1024)
            return subprocess.CompletedProcess(command, 0, b"", b"")
        with patch.object(studio_audio, "_cache_folder", return_value=output), \
             patch.object(studio_audio, "_ffmpeg_binary", return_value="bundled-ffmpeg.exe"), \
             patch.object(studio_audio.subprocess, "run", side_effect=render) as convert:
            first = studio_audio._decode_pcm(self.song)
            second = studio_audio._decode_pcm(self.song)
            self.assertEqual(first, second)
            self.assertEqual(convert.call_count, 1)
            self.song.write_bytes(self.old + b"changed")
            third = studio_audio._decode_pcm(self.song)
            self.assertNotEqual(first, third)
            self.assertEqual(convert.call_count, 2)
        self.assertEqual(first.suffix, ".wav")

    def test_ffmpeg_failure_leaves_original_and_no_playable_cache(self):
        output = self.root / "cache"
        with patch.object(studio_audio, "_cache_folder", return_value=output), \
             patch.object(studio_audio, "_ffmpeg_binary", return_value="bundled-ffmpeg.exe"), \
             patch.object(studio_audio.subprocess, "run",
                          return_value=subprocess.CompletedProcess([], 1, b"", b"invalid source")):
            with self.assertRaisesRegex(OSError, "invalid source"):
                studio_audio._decode_pcm(self.song)
        self.assertEqual(self.song.read_bytes(), self.old)
        self.assertEqual(list(output.glob("*.wav")), [])


if __name__ == "__main__":
    unittest.main()
