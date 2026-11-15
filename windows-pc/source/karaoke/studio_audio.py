"""Play Song Studio's M4A and other audio even without a Windows MCI codec.

Prefer native MCI (instant start, no conversion). If the system cannot open
the original, decode with imageio-ffmpeg bundled by the Windows build to
verified PCM WAV and play using the existing waveOut backend. Only a private
bounded cache is written; the original Song Studio library stays read-only.
"""
from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import subprocess
import tempfile
import time

FALLBACK_EXT = frozenset((".m4a", ".aac", ".flac", ".ogg", ".oga"))
CACHE_LIMIT = 4
MAX_WAV_BYTES = 512 * 1024 * 1024
TIMEOUT_SECONDS = 240


def _cache_folder():
    home = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(home) / "X-Stage" / "KaraokePC" / "decoded-audio"


def _ffmpeg_binary():
    # The Windows release collects this executable from imageio-ffmpeg.
    import imageio_ffmpeg
    path = Path(imageio_ffmpeg.get_ffmpeg_exe())
    if not path.is_file():
        raise FileNotFoundError("ไม่พบ FFmpeg ที่บรรจุมากับ X-Stage")
    return str(path)


def _cache_key(source):
    path = Path(source).resolve()
    stat = path.stat()
    # No full-media hash during stage start; path, size and modification
    # timestamp invalidate previously converted PCM after an edit.
    identity = f"{os.path.normcase(str(path))}|{stat.st_size}|{stat.st_mtime_ns}"
    return sha256(identity.encode("utf-8", errors="surrogatepass")).hexdigest()


def _prune(folder, current):
    try:
        previous = sorted((f for f in folder.glob("*.wav")
                           if f.is_file() and not f.is_symlink()),
                          key=lambda f: f.stat().st_mtime_ns, reverse=True)
        for file in previous:
            if file != current and previous.index(file) >= CACHE_LIMIT:
                file.unlink(missing_ok=True)
    except OSError:
        pass  # Cache cleanup must never interrupt live karaoke playback.


def _decode_pcm(source, *, ffmpeg=None):
    source = Path(source).resolve()
    if source.suffix.casefold() not in FALLBACK_EXT or not source.is_file():
        raise ValueError("รูปแบบเพลงไม่รองรับการถอดรหัสทางเลือก")
    folder = _cache_folder()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (_cache_key(source) + ".wav")
    if target.is_file() and 44 < target.stat().st_size <= MAX_WAV_BYTES:
        os.utime(target, None)
        _prune(folder, target)
        return target

    tool = ffmpeg or _ffmpeg_binary()
    handle, tmp_name = tempfile.mkstemp(prefix=".decode-", suffix=".wav", dir=folder)
    os.close(handle)
    tmp = Path(tmp_name)
    try:
        completed = subprocess.run(
            [tool, "-hide_banner", "-nostdin", "-loglevel", "error",
             "-y", "-i", str(source), "-map", "0:a:0", "-vn",
             "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le",
             "-f", "wav", str(tmp)],
            capture_output=True, timeout=TIMEOUT_SECONDS, check=False)
        if completed.returncode:
            error = completed.stderr.decode("utf-8", "replace").strip()
            raise OSError("FFmpeg ถอดรหัสเพลงไม่สำเร็จ: " + error[-450:])
        size = tmp.stat().st_size
        if size <= 44 or size > MAX_WAV_BYTES:
            raise ValueError("เพลง PCM มีขนาดไม่สมบูรณ์หรือเกิน 512 MB")
        import wave
        with wave.open(str(tmp), "rb") as reader:
            if (reader.getcomptype() != "NONE" or reader.getnchannels() != 2
                    or reader.getsampwidth() != 2 or reader.getnframes() < 1):
                raise ValueError("PCM WAV ที่ถอดรหัสไม่ถูกต้อง")
        os.replace(tmp, target)
        _prune(folder, target)
        return target
    finally:
        tmp.unlink(missing_ok=True)


class SongStudioAudioPlayer:
    """Adapter implementing the MediaPlayer transport contract for UI."""
    kind = "AUDIO"
    supports_pitch = False

    def __init__(self):
        self._player = None
        self.fallback_used = False

    def load(self, path, video_handle=0, video=False):
        from .playback import MediaPlayer, WavePlayer
        path = Path(path)
        if video or path.suffix.casefold() not in FALLBACK_EXT:
            raise ValueError("ต้องเลือกไฟล์เสียง M4A/AAC/FLAC/OGG ที่รองรับ")
        try:
            native = MediaPlayer()
            self._player = native
            native.load(path, video_handle, False)
            self.fallback_used = False
            return
        except OSError:
            if self._player:
                self._player.close()
                self._player = None
        converted = _decode_pcm(path)
        wave_player = WavePlayer()
        self._player = wave_player
        try:
            wave_player.load(converted)
        except BaseException:
            self.close()
            raise
        self.fallback_used = True

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if self._player is None:
            raise AttributeError(name)
        return getattr(self._player, name)

    def close(self):
        if self._player is not None:
            player, self._player = self._player, None
            player.close()
