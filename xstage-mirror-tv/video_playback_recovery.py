#!/usr/bin/env python3
"""Patch pinned AirShow ExoPlayer for bounded live-edge recovery.

AirPlay video playback (HLS/VOD) uses ExoPlayer, while iOS screen mirroring
uses a separate native renderer. Never restart the AirPlay receiver to
recover a video stream, and never run this watchdog on screen mirroring.
"""
from pathlib import Path
import sys

player = Path(sys.argv[1]).resolve() / "app/src/main/kotlin/app/airshow/tv/renderer/AirPlayVideoPlayer.kt"

def replace_once(before: str, after: str):
    source = player.read_text(encoding="utf-8")
    count = source.count(before)
    if count != 1:
        raise RuntimeError(f"{player}: expected one anchor, got {count}: {before[:80]!r}")
    player.write_text(source.replace(before, after), encoding="utf-8")

replace_once("import android.os.Looper\n",
             "import android.os.Looper\nimport android.os.SystemClock\nimport android.widget.Toast\n")
replace_once("    private var clientGain = 1f\n", """    private var clientGain = 1f
    // Values are touched only on ExoPlayer's application (main) looper.
    private var bufferingSinceMs = 0L
    private var readySinceMs = 0L
    private var consecutiveRecoveries = 0
    private var lastKnownLive = false
""")
replace_once("""    private val _listener = object : Player.Listener {
        override fun onPlayerError(error: androidx.media3.common.PlaybackException) {
            Log.w(TAG, "playback error", error)
            onEnded?.invoke()
        }
        override fun onPlaybackStateChanged(state: Int) {
            if (state == Player.STATE_ENDED) onEnded?.invoke()
        }
""", """    // Distinguish transient live HLS stalls from VOD failures. If buffering
    // continues after a bounded interval, restart only the player, preserving
    // the current AirPlay receiver and its screen-mirroring connection.
    private val _stallWatchdog = object : Runnable {
        override fun run() {
            val current = player ?: return
            val now = SystemClock.elapsedRealtime()
            if (current.isCurrentMediaItemLive) lastKnownLive = true
            if (!current.playWhenReady || current.playbackState == Player.STATE_READY) {
                bufferingSinceMs = 0L
                if (current.playbackState == Player.STATE_READY && current.playWhenReady) {
                    if (readySinceMs == 0L) readySinceMs = now
                    if (now - readySinceMs >= STABLE_PLAYBACK_MS) {
                        consecutiveRecoveries = 0
                    }
                } else {
                    readySinceMs = 0L
                }
            } else if (current.playbackState == Player.STATE_BUFFERING ||
                       current.playbackState == Player.STATE_IDLE) {
                readySinceMs = 0L
                if (bufferingSinceMs == 0L) bufferingSinceMs = now
                val timeoutMs = if (lastKnownLive) LIVE_BUFFERING_TIMEOUT_MS
                    else VOD_BUFFERING_TIMEOUT_MS
                if (now - bufferingSinceMs >= timeoutMs) {
                    if (!_recoverOrFinish("buffering timeout")) return
                }
            }
            mainHandler.postDelayed(this, WATCHDOG_INTERVAL_MS)
        }
    }

    // On an HLS live stream the old absolute position can fall outside the
    // sliding playlist window; always restart at the current live edge.
    private fun _recoverOrFinish(reason: String): Boolean {
        val current = player ?: return false
        val live = current.isCurrentMediaItemLive || lastKnownLive
        val maxRecoveries = if (live) LIVE_MAX_RECOVERIES else VOD_MAX_RECOVERIES
        if (consecutiveRecoveries >= maxRecoveries) {
            _reportFailure("AirPlay video $reason after $consecutiveRecoveries retries, live=$live")
            return false
        }
        consecutiveRecoveries++
        bufferingSinceMs = SystemClock.elapsedRealtime()
        readySinceMs = 0L
        val previousPosition = current.currentPosition.coerceAtLeast(0L)
        Log.w(TAG, "Recovering AirPlay video ($reason): attempt " +
            "$consecutiveRecoveries/$maxRecoveries, live=$live")
        // Media3 stop + prepare reopens the HTTP/HLS source. A plain prepare()
        // while BUFFERING does not reliably restart a stalled load.
        current.stop()
        if (live) {
            current.seekToDefaultPosition()
        } else {
            current.seekTo(previousPosition)
        }
        current.prepare()
        current.playWhenReady = true
        return true
    }

    private fun _reportFailure(reason: String) {
        Log.w(TAG, reason)
        mainHandler.removeCallbacks(_stallWatchdog)
        Toast.makeText(context,
            "วิดีโอขัดข้องหรือสัญญาณถ่ายทอดสดไม่พร้อม โปรดลองเล่นใหม่",
            Toast.LENGTH_LONG).show()
        onEnded?.invoke()
    }

    private val _listener = object : Player.Listener {
        override fun onPlayerError(error: androidx.media3.common.PlaybackException) {
            Log.w(TAG, "AirPlay video error: " + error.errorCodeName, error)
            _recoverOrFinish("player error: " + error.errorCodeName)
        }
        override fun onPlaybackStateChanged(state: Int) {
            if (state == Player.STATE_READY) {
                bufferingSinceMs = 0L
                readySinceMs = SystemClock.elapsedRealtime()
                if (player?.isCurrentMediaItemLive == true) lastKnownLive = true
            }
            if (state == Player.STATE_BUFFERING && bufferingSinceMs == 0L)
                bufferingSinceMs = SystemClock.elapsedRealtime()
            if (state == Player.STATE_ENDED) onEnded?.invoke()
        }
""")
replace_once("""        player = p
        p.setMediaItem""", """        player = p
        bufferingSinceMs = SystemClock.elapsedRealtime()
        readySinceMs = 0L
        consecutiveRecoveries = 0
        lastKnownLive = false
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
        readySinceMs = 0L
        consecutiveRecoveries = 0
        lastKnownLive = false
        player?.let {""")
replace_once("""        private const val REPORT_INTERVAL_MS = 250L
""", """        private const val REPORT_INTERVAL_MS = 250L
        private const val WATCHDOG_INTERVAL_MS = 1_000L
        private const val VOD_BUFFERING_TIMEOUT_MS = 18_000L
        private const val LIVE_BUFFERING_TIMEOUT_MS = 12_000L
        private const val STABLE_PLAYBACK_MS = 20_000L
        private const val VOD_MAX_RECOVERIES = 1
        private const val LIVE_MAX_RECOVERIES = 3
""")
print("PASS: AirPlay live HLS edge recovery, bounded retries and VOD protection")
