#!/usr/bin/env python3
"""Safe automatic AirPlay quality profiles on the pinned Android TV receiver."""
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
package = root / "app/src/main/kotlin/app/airshow/tv"

def change(path: Path, a: str, b: str):
    old = path.read_text(encoding="utf-8")
    n = old.count(a)
    if n != 1:
        raise RuntimeError(f"{path}: expected 1 match but saw {n} for {a[:85]!r}")
    path.write_text(old.replace(a, b), encoding="utf-8")

src = Path(__file__).resolve().parent / "MirrorAutoQuality.kt"
(package / "service/MirrorAutoQuality.kt").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

service = package / "service/AirPlayService.kt"
change(service,
       '    private var foregroundStarted = false',
       '    private var foregroundStarted = false\n'
       '    private val mirrorAutoQuality by lazy { MirrorAutoQuality(this) }\n'
       '    private var activeMirrorProfile: MirrorAutoQuality.Profile? = null')
change(service,
       '        val maxFps = prefs[Prefs.MAX_FPS]\n'
       '        val overscanned = prefs[Prefs.OVERSCANNED]',
       '        // Evaluate hardware capabilities and learn from sustained real lag.\n'
       '        val selectedProfile = mirrorAutoQuality.choose()\n'
       '        activeMirrorProfile = selectedProfile\n'
       '        val maxFps = if (prefs[Prefs.RESOLUTION] == Prefs.AUTO)\n'
       '            selectedProfile.fps else prefs[Prefs.MAX_FPS]\n'
       '        Log.i(TAG, "Auto quality negotiated: " + selectedProfile.label)\n'
       '        val overscanned = prefs[Prefs.OVERSCANNED]')
change(service,
       '        val (reqW, reqH) = _displaySize(clamp = false)',
       '        val (reqW, reqH) = if (prefs[Prefs.RESOLUTION] == Prefs.AUTO)\n'
       '            (selectedProfile.width to selectedProfile.height)\n'
       '        else _displaySize(clamp = false)')
change(service,
       '        val (w, h) = _displaySize()\n'
       '        videoRenderer.setResolution(w, h)',
       '        val (w, h) = _adaptiveDisplaySize()\n'
       '        videoRenderer.setResolution(w, h)')
change(service,
       '        val (w, h) = _displaySize()\n'
       '        NativeBridge.nativeSetDisplaySize(nativeHandle, w, h, prefs[Prefs.MAX_FPS])',
       '        val (w, h) = _adaptiveDisplaySize()\n'
       '        val fps = if (prefs[Prefs.RESOLUTION] == Prefs.AUTO)\n'
       '            (activeMirrorProfile?.fps ?: 30) else prefs[Prefs.MAX_FPS]\n'
       '        NativeBridge.nativeSetDisplaySize(nativeHandle, w, h, fps)')
change(service,
       '    private fun _orientationFollowsDevice(): Boolean =',
       '''    private fun _adaptiveDisplaySize(): Pair<Int, Int> {
        val (w, h) = _displaySize()
        if (prefs[Prefs.RESOLUTION] != Prefs.AUTO) return w to h
        val profile = activeMirrorProfile ?: return w to h
        val wide = w >= h
        val targetW = if (wide) profile.width else profile.height
        val targetH = if (wide) profile.height else profile.width
        val scale = minOf(1.0, targetW.toDouble() / w, targetH.toDouble() / h)
        return ((w * scale).toInt().coerceAtLeast(2) / 2) * 2 to
            ((h * scale).toInt().coerceAtLeast(2) / 2) * 2
    }

    private fun _orientationFollowsDevice(): Boolean =''')
change(service,
       '        videoRenderer.feedFrame(data, ntpTimeNs, isH265)',
       '''        videoRenderer.feedFrame(data, ntpTimeNs, isH265)
        when (mirrorAutoQuality.sample(
            videoRenderer.frameCount,
            videoRenderer.droppedFrames,
            videoRenderer.framePacingJitterUs,
            videoRenderer.decodedFrameCount
        )) {
            MirrorAutoQuality.Signal.CATCH_UP -> {
                // Only drop already-decoded display frames, never H.264
                // reference packets; no forced iOS reconnection.
                videoRenderer.catchUpMode = true
            }
            MirrorAutoQuality.Signal.RECOVER -> videoRenderer.catchUpMode = false
            MirrorAutoQuality.Signal.NONE -> Unit
        }''')
change(service,
       '''        if (running) videoRenderer.startSession() else {
            videoRenderer.stopSession()
            _mirroringActive.value = false
        }''',
       '''        if (running) {
            videoRenderer.startSession()
            videoRenderer.catchUpMode = false
            mirrorAutoQuality.startSession()
        } else {
            mirrorAutoQuality.endSession()
            videoRenderer.catchUpMode = false
            videoRenderer.stopSession()
            _mirroringActive.value = false
        }''')
# Place the reconnect logic inside onConnectionDestroy, before its final log.
change(service,
       '        log("Sender disconnected (',
       '''        if (_connectionCount.value == 0 && mirrorAutoQuality.isRenegotiationPending()) {
            // Re-advertise only after the user has disconnected, never live.
            _mainHandler.postDelayed({
                if (_connectionCount.value == 0 &&
                    _serverState.value == ServerState.RUNNING &&
                    mirrorAutoQuality.isRenegotiationPending()) {
                    Log.i(TAG, "Applying learned AirPlay profile after disconnect")
                    _restartServer()
                }
            }, 1_500L)
        }
        log("Sender disconnected (''')

renderer = package / "renderer/VideoRenderer.kt"
change(renderer,
       '    @Volatile var frameCount = 0L; private set',
       '    @Volatile var frameCount = 0L; private set\n'
       '    @Volatile var decodedFrameCount = 0L; private set')
change(renderer,
       '        fps = 0; bitrateBps = 0; frameCount = 0; codecName = ""',
       '        fps = 0; bitrateBps = 0; frameCount = 0; codecName = ""\n'
       '        decodedFrameCount = 0L')
change(renderer,
       '    private fun _recordOutputFrameTime() {\n        val now = System.nanoTime()',
       '    private fun _recordOutputFrameTime() {\n'
       '        decodedFrameCount++\n'
       '        val now = System.nanoTime()')
change(renderer,
       '    var scheduledOutputBufferRelease = true',
       '    @Volatile var catchUpMode = false\n'
       '    var scheduledOutputBufferRelease = true')
change(renderer,
       '''    private fun drainOutput() {
        val c = codec ?: return
        val info = MediaCodec.BufferInfo()
        while (true) {
            val idx = c.dequeueOutputBuffer(info, 0)
            if (idx < 0) break
            _recordOutputFrameTime()
            if (scheduledOutputBufferRelease) {
                // schedule frame at VSYNC matching its NTP presentation time
                val ptsUs = info.presentationTimeUs
                if (_ptsBaseUs == Long.MIN_VALUE) {
                    _ptsBaseUs = ptsUs
                    _wallBaseNs = System.nanoTime()
                }
                c.releaseOutputBuffer(idx, _wallBaseNs + (ptsUs - _ptsBaseUs) * 1000L)
            } else {
                c.releaseOutputBuffer(idx, true)
            }
        }
    }''',
       '''    private fun drainOutput() {
        val c = codec ?: return
        val info = MediaCodec.BufferInfo()
        var latestDecodedBuffer = -1
        while (true) {
            val idx = c.dequeueOutputBuffer(info, 0)
            if (idx == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) continue
            if (idx < 0) break
            _recordOutputFrameTime()
            if (catchUpMode) {
                // All compressed references were decoded; discard only
                // already-decoded display buffers when backlog accumulates.
                if (latestDecodedBuffer >= 0) {
                    c.releaseOutputBuffer(latestDecodedBuffer, false)
                }
                latestDecodedBuffer = idx
                continue
            }
            if (scheduledOutputBufferRelease) {
                val ptsUs = info.presentationTimeUs
                val now = System.nanoTime()
                val target = if (_ptsBaseUs == Long.MIN_VALUE) now else
                    _wallBaseNs + (ptsUs - _ptsBaseUs) * 1000L
                // Discontinuous sender timestamps must not park decoder output buffers.
                if (_ptsBaseUs == Long.MIN_VALUE || target - now > 250_000_000L || now - target > 250_000_000L) {
                    _ptsBaseUs = ptsUs
                    _wallBaseNs = now
                    c.releaseOutputBuffer(idx, true)
                } else {
                    c.releaseOutputBuffer(idx, maxOf(now, target))
                }
            } else {
                c.releaseOutputBuffer(idx, true)
            }
        }
        if (latestDecodedBuffer >= 0) {
            _ptsBaseUs = Long.MIN_VALUE
            c.releaseOutputBuffer(latestDecodedBuffer, true)
        }
    }''')

settings = package / "ui/SettingsScreen.kt"
raw = settings.read_text(encoding="utf-8")
begin = raw.find('        Text("โหมดภาพตามความสามารถของกล่องทีวี",')
end_marker = ' { Text("คมชัด 1080p / 30 FPS") }\n'
end = raw.find(end_marker, begin)
if begin < 0 or end < 0:
    raise RuntimeError("Previous manual quality preset block not found")
end += len(end_marker)
raw = (raw[:begin] +
       '        Text("AUTO Performance: ประเมินตัวถอดรหัสและปรับภาพให้อัตโนมัติ",\n'
       '            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp))\n' +
       raw[end:])
settings.write_text(raw, encoding="utf-8")
print("PASS: hardware auto quality, decoded-only catch-up and session-safe downshifts")
