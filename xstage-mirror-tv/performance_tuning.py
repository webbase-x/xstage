#!/usr/bin/env python3
"""Targeted performance patches for pinned AirShow on compact Android TV boxes.

No floating dependency upgrades or remote runtime downloads. This script runs
only on the pinned source copied into CI's build workspace.
"""
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
package = root / "app/src/main/kotlin/app/airshow/tv"
this_dir = Path(__file__).resolve().parent

def replace_once(path: Path, original: str, replacement: str):
    source = path.read_text(encoding="utf-8")
    occurrences = source.count(original)
    if occurrences != 1:
        raise RuntimeError(f"{path}: expected one location, got {occurrences}: {original[:70]!r}")
    path.write_text(source.replace(original, replacement), encoding="utf-8")

prefs = package / "Prefs.kt"
replace_once(prefs,
             'val MAX_FPS = int("max_fps", 60, 1..Int.MAX_VALUE, restart = true)',
             'val MAX_FPS = int("max_fps", 30, 1..Int.MAX_VALUE, restart = true)')
# H.264 is less likely to trigger slow software decode on unknown TrueID models.
# HEVC can still be turned on manually for supported boxes.
replace_once(prefs,
             'val H265 = tri("h265", restart = true)',
             'val H265 = str("h265", OFF, restart = true) { it in setOf(AUTO, ON, OFF) }')

renderer = package / "renderer/VideoRenderer.kt"
# The old path could wait up to 200ms for each packet / 1s for first packet.
# Keep short bounded retries to avoid blocking incoming AirPlay network callbacks.
# An overloaded decoder may still drop frames; users can choose 720p30.
replace_once(renderer, 'private const val FEED_WAIT_US = 20_000L',
             'private const val FEED_WAIT_US = 5_000L')
replace_once(renderer, 'private const val FEED_RETRIES = 10',
             'private const val FEED_RETRIES = 5')
replace_once(renderer, 'private const val FIRST_FEED_RETRIES = 50',
             'private const val FIRST_FEED_RETRIES = 20')
replace_once(renderer,
             '    // codec per mirror session; pipeline persists across sessions',
             '    fun prewarmPipeline() = pipeline.start()\n\n'
             '    // codec per mirror session; pipeline persists across sessions')

# Android NsdManager may report transient registration failures. Retry in a
# bounded fashion while keeping the Wi-Fi multicast lock; cancel on teardown.
discovery = package / "discovery/NsdServiceManager.kt"
discovery.write_text(
    (this_dir / "NsdServiceManager.kt").read_text(encoding="utf-8"),
    encoding="utf-8",
)

service = package / "service/AirPlayService.kt"
replace_once(service,
             '        val (maxW, maxH) = videoRenderer.maxResolution()\n'
             '        return w.coerceAtMost(maxW) to h.coerceAtMost(maxH)',
             '        val (maxW, maxH) = videoRenderer.maxResolution()\n'
             '        // AUTO is capped at 1080p, even if the TV panel is 4K.\n'
             '        // Keep aspect ratio and even dimensions for H.264 hardware decoders.\n'
             '        val auto = res == Prefs.AUTO\n'
             '        val limitW = if (auto) minOf(maxW, 1920) else maxW\n'
             '        val limitH = if (auto) minOf(maxH, 1080) else maxH\n'
             '        val scale = minOf(1.0, limitW.toDouble() / w, limitH.toDouble() / h)\n'
             '        val safeW = ((w * scale).toInt().coerceAtLeast(2) / 2) * 2\n'
             '        val safeH = ((h * scale).toInt().coerceAtLeast(2) / 2) * 2\n'
             '        return safeW to safeH')
replace_once(service,
             '    private var foregroundStarted = false',
             '    private var foregroundStarted = false\n'
             '    @Volatile private var connectionStartedAtMs = 0L\n'
             '    @Volatile private var firstFrameSeen = false\n'
             '    @Volatile private var firstVideoSizeSeen = false')
replace_once(service,
             '        val effectiveName = prefs[Prefs.SERVER_NAME].ifBlank { Prefs.SERVER_NAME.def }',
             '        val startupMs = SystemClock.elapsedRealtime()\n'
             '        val effectiveName = prefs[Prefs.SERVER_NAME].ifBlank { Prefs.SERVER_NAME.def }')
replace_once(service,
             '        _serverState.value = ServerState.RUNNING',
             '        _serverState.value = ServerState.RUNNING\n'
             '        // mDNS registration is already queued. Prepare the GLES pipeline\n'
             '        // before the sender transmits its first keyframe.\n'
             '        runCatching { videoRenderer.prewarmPipeline() }\n'
             '            .onFailure { Log.w(TAG, "GL prewarm failed", it) }\n'
             '        Log.i(TAG, "Receiver startup: " +\n'
             '            (SystemClock.elapsedRealtime() - startupMs) + " ms")')
replace_once(service,
             '        val firstConnection = _connectionCount.value == 0',
             '        val firstConnection = _connectionCount.value == 0\n'
             '        if (firstConnection) {\n'
             '            connectionStartedAtMs = SystemClock.elapsedRealtime()\n'
             '            firstFrameSeen = false\n'
             '            firstVideoSizeSeen = false\n'
             '        }')
replace_once(service,
             '    override fun onVideoData(data: ByteArray, ntpTimeNs: Long, isH265: Boolean) {\n'
             '        videoRenderer.feedFrame(data, ntpTimeNs, isH265)',
             '    override fun onVideoData(data: ByteArray, ntpTimeNs: Long, isH265: Boolean) {\n'
             '        if (!firstFrameSeen && connectionStartedAtMs > 0L) {\n'
             '            firstFrameSeen = true\n'
             '            Log.i(TAG, "First video packet after " +\n'
             '                (SystemClock.elapsedRealtime() - connectionStartedAtMs) + " ms")\n'
             '        }\n'
             '        videoRenderer.feedFrame(data, ntpTimeNs, isH265)')
replace_once(service,
             '        log("Video size: ',
             '        if (w > 0f && h > 0f) firstVideoSizeSeen = true\n'
             '        if (connectionStartedAtMs > 0L) {\n'
             '            Log.i(TAG, "Negotiated video size after " +\n'
             '                (SystemClock.elapsedRealtime() - connectionStartedAtMs) + " ms")\n'
             '        }\n'
             '        log("Video size: ')
replace_once(service,
             '        if (_connectionCount.value == 0) {\n'
             '            // clients may drop without POST /stop;',
             '        if (_connectionCount.value == 0) {\n'
             '            val durationMs = if (connectionStartedAtMs > 0L)\n'
             '                SystemClock.elapsedRealtime() - connectionStartedAtMs else -1L\n'
             '            if (durationMs >= 0L) {\n'
             '                val phase = when {\n'
             '                    firstFrameSeen -> "video-packets-arrived"\n'
             '                    firstVideoSizeSeen -> "video-size-only"\n'
             '                    else -> "connected-without-video"\n'
             '                }\n'
             '                Log.i(TAG, "AirPlay session ended: durationMs=$durationMs phase=$phase")\n'
             '                if (durationMs < 15_000L && !firstFrameSeen) {\n'
             '                    Log.w(TAG, "Short AirPlay session without video data; inspect sender handshake and network before decoder")\n'
             '                }\n'
             '            }\n'
             '            connectionStartedAtMs = 0L\n'
             '            firstFrameSeen = false\n'
             '            firstVideoSizeSeen = false\n'
             '            // clients may drop without POST /stop;')

settings = package / "ui/SettingsScreen.kt"
replace_once(settings,
             '        SectionHeader(stringResource(R.string.section_display))',
             '        SectionHeader(stringResource(R.string.section_display))\n'
             '        Text("โหมดภาพตามความสามารถของกล่องทีวี",\n'
             '            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp))\n'
             '        Button(onClick = {\n'
             '            viewModel.set(Prefs.RESOLUTION, "1280x720")\n'
             '            viewModel.set(Prefs.MAX_FPS, 30)\n'
             '        }, modifier = Modifier.padding(horizontal = 16.dp)) { Text("ลื่นไหล 720p / 30 FPS") }\n'
             '        Button(onClick = {\n'
             '            viewModel.set(Prefs.RESOLUTION, "1280x720")\n'
             '            viewModel.set(Prefs.MAX_FPS, 60)\n'
             '        }, modifier = Modifier.padding(horizontal = 16.dp)) { Text("เคลื่อนไหว 720p / 60 FPS") }\n'
             '        Button(onClick = {\n'
             '            viewModel.set(Prefs.RESOLUTION, "1920x1080")\n'
             '            viewModel.set(Prefs.MAX_FPS, 30)\n'
             '        }, modifier = Modifier.padding(horizontal = 16.dp)) { Text("คมชัด 1080p / 30 FPS") }')

print("PASS: 1080p AUTO cap, H.264 compatibility, bounded decoder queue,"
      " prewarm, NSD retries, session-phase diagnostics and TV profiles")
