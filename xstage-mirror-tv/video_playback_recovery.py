#!/usr/bin/env python3
"""Recover stuck AirPlay video buffering independently of the screen-mirroring decoder."""
from pathlib import Path
import sys

player = Path(sys.argv[1]).resolve() / "app/src/main/kotlin/app/airshow/tv/renderer/AirPlayVideoPlayer.kt"
def replace_once(before: str, after: str):
    source = player.read_text(encoding="utf-8")
    n = source.count(before)
    if n != 1:
        raise RuntimeError(f"{player}: expected one anchor, got {n}: {before[:80]!r}")
    player.write_text(source.replace(before, after), encoding="utf-8")

replace_once("import android.os.Looper\n",
             "import android.os.Looper\nimport android.os.SystemClock\nimport android.widget.Toast\n")
replace_once("    private var clientGain = 1f\n",
    """    private var clientGain = 1f
    private var bufferingSinceMs = 0L
    private var recoveredOnce = false
""")
replace_once("""    private val _listener = object : Player.Listener {
        override fun onPlayerError(error: androidx.media3.common.PlaybackException) {
            Log.w(TAG, "playback error", error)
            onEnded?.invoke()
        }
        override fun onPlaybackStateChanged(state: Int) {
            if (state == Player.STATE_ENDED) onEnded?.invoke()
        }
""", """    private val _stallWatchdog = object : Runnable {
        override fun run() {
            val current = player ?: return
            val now = SystemClock.elapsedRealtime()
            val stalled = current.playWhenReady &&
                (current.playbackState == Player.STATE_BUFFERING ||
                 current.playbackState == Player.STATE_IDLE)
            if (!stalled) {
                bufferingSinceMs = 0L
            } else {
                if (bufferingSinceMs == 0L) bufferingSinceMs = now
                if (now - bufferingSinceMs >= BUFFERING_TIMEOUT_MS) {
                    if (recoveredOnce) {
                        _reportFailure("AirPlay video failed after one retry")
                        return
                    }
                    recoveredOnce = true
                    bufferingSinceMs = now
                    val positionMs = current.currentPosition.coerceAtLeast(0L)
                    Log.w(TAG, "AirPlay video buffering timeout; retry media source once")
                    current.stop()
                    current.prepare()
                    current.seekTo(positionMs)
                    current.playWhenReady = true
                }
            }
            mainHandler.postDelayed(this, WATCHDOG_INTERVAL_MS)
        }
    }

    private fun _reportFailure(reason: String) {
        Log.w(TAG, reason)
        mainHandler.removeCallbacks(_stallWatchdog)
        Toast.makeText(context,
            "ไม่สามารถโหลดวิดีโอได้ โปรดลองเล่นใหม่หรือตรวจสอบเครือข่าย",
            Toast.LENGTH_LONG).show()
        onEnded?.invoke()
    }

    private val _listener = object : Player.Listener {
        override fun onPlayerError(error: androidx.media3.common.PlaybackException) {
            Log.w(TAG, "playback error", error)
            _reportFailure("AirPlay video player error: " + error.errorCodeName)
        }
        override fun onPlaybackStateChanged(state: Int) {
            if (state == Player.STATE_READY) bufferingSinceMs = 0L
            if (state == Player.STATE_BUFFERING && bufferingSinceMs == 0L)
                bufferingSinceMs = SystemClock.elapsedRealtime()
            if (state == Player.STATE_ENDED) onEnded?.invoke()
        }
""")
replace_once("""        player = p
        p.setMediaItem""", """        player = p
        recoveredOnce = false
        bufferingSinceMs = SystemClock.elapsedRealtime()
        p.setMediaItem""")
replace_once("""        mainHandler.postDelayed(_reportTick, REPORT_INTERVAL_MS)
    }

    fun scrub""", """        mainHandler.postDelayed(_reportTick, REPORT_INTERVAL_MS)
        mainHandler.postDelayed(_stallWatchdog, WATCHDOG_INTERVAL_MS)
    }

    fun scrub""")
replace_once("""        mainHandler.removeCallbacks(_reportTick)
        player?.let {""", """        mainHandler.removeCallbacks(_reportTick)
        mainHandler.removeCallbacks(_stallWatchdog)
        bufferingSinceMs = 0L
        recoveredOnce = false
        player?.let {""")
replace_once("""        private const val REPORT_INTERVAL_MS = 250L
""", """        private const val REPORT_INTERVAL_MS = 250L
        private const val WATCHDOG_INTERVAL_MS = 1_000L
        private const val BUFFERING_TIMEOUT_MS = 18_000L
""")
print("PASS: bounded VOD buffering timeout, single retry and return-home failure")
