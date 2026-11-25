package app.airshow.tv.service

import android.content.Context
import android.media.MediaCodecInfo
import android.media.MediaCodecList
import android.media.MediaFormat
import android.os.Build
import android.os.SystemClock
import android.util.Log
import app.airshow.tv.realDisplaySize

/**
 * Device-adaptive AirPlay mirroring with hysteresis and safe session boundaries.
 *
 * Receiver-advertised resolution/FPS are negotiated before mirroring starts.
 * The iOS system mirroring sender is not guaranteed to accept live renegotiation.
 * Never terminate a session to downshift. Instead, clear already-DECODED video
 * output backlog immediately and use the lower advertised level next session.
 *
 * Frame counts from a mostly-static phone screen are not evidence of lag:
 * downgrade only with sustained decoder drops or high output pacing jitter
 * while frames are actually flowing.
 */
class MirrorAutoQuality(private val context: Context) {
    data class Profile(val width: Int, val height: Int, val fps: Int, val label: String)
    enum class Signal { NONE, CATCH_UP, RECOVER }

    private val preferences = context.getSharedPreferences("xstage_mirror_stable_quality_v119", Context.MODE_PRIVATE)
    private val candidates = listOf(
        Profile(1920, 1080, 30, "1080p30"),
        Profile(1280, 720, 30, "720p30"),
        Profile(960, 540, 30, "540p30")
    )

    // Resolve only once per service lifetime, rather than probing MediaCodecList
    // or video capabilities every two seconds on the rendering thread.
    private val available: List<Profile> by lazy { detectProfiles() }
    private var active: Profile? = null
    private var pendingReannounce = false
    private var sessionSinceMs = 0L
    private var lastSampleMs = 0L
    private var lastFrameCount = 0L
    private var lastInputDrops = 0L
    private var lastDecodedCount = 0L
    private var badSamples = 0
    private var stableSamples = 0
    private var degradedInSession = false
    private var catchUp = false

    @Synchronized
    fun choose(): Profile {
        val possible = available
        val initialLevel = possible.indexOfFirst { it.width <= 1280 }.let { if (it < 0) 0 else it }
        val requested = preferences.getInt("level", initialLevel).coerceIn(0, possible.lastIndex)
        preferences.edit().putInt("level", requested).apply()
        val profile = possible[requested]
        active = profile
        pendingReannounce = false
        Log.i(TAG, "Hardware support=" + possible.joinToString { it.label } +
            " selected=" + profile.label)
        return profile
    }

    @Synchronized
    fun isRenegotiationPending() = pendingReannounce

    @Synchronized
    fun startSession() {
        sessionSinceMs = SystemClock.elapsedRealtime()
        lastSampleMs = sessionSinceMs
        lastFrameCount = 0L
        lastInputDrops = 0L
        lastDecodedCount = 0L
        badSamples = 0
        stableSamples = 0
        degradedInSession = false
        catchUp = false
    }

    /**
     * All counters are cumulative within the current mirroring session.
     * Returns only transition edges, not an action for each incoming frame.
     */
    @Synchronized
    fun sample(totalFrames: Long, totalInputDrops: Long, jitterUs: Long, totalDecodedFrames: Long): Signal {
        val now = SystemClock.elapsedRealtime()
        if (sessionSinceMs == 0L || now - lastSampleMs < SAMPLE_MS) return Signal.NONE

        val frames = (totalFrames - lastFrameCount).coerceAtLeast(0L)
        val drops = (totalInputDrops - lastInputDrops).coerceAtLeast(0L)
        val decoded = (totalDecodedFrames - lastDecodedCount).coerceAtLeast(0L)
        val duration = (now - lastSampleMs).coerceAtLeast(1L)
        lastFrameCount = totalFrames
        lastInputDrops = totalInputDrops
        lastDecodedCount = totalDecodedFrames
        lastSampleMs = now

        // Changes on screen may be idle/static; low FPS alone is not proof
        // of slow hardware or Wi-Fi. Use observed drops / jitter only on motion.
        val activeStream = frames * 1000L / duration >= 12L
        val decoderBacklog = frames >= 24L && decoded * 100L < frames * 70L
        val overloaded = activeStream && (drops >= 2L || jitterUs > 25_000L || decoderBacklog)
        if (overloaded) {
            badSamples++
            stableSamples = 0
        } else {
            badSamples = 0
            if (activeStream && drops == 0L && jitterUs < 14_000L) stableSamples++
        }

        if (badSamples >= 3) {
            if (!degradedInSession) {
                degradedInSession = true
                val possible = available
                val oldLevel = preferences.getInt("level", 0).coerceIn(0, possible.lastIndex)
                if (oldLevel < possible.lastIndex) {
                    preferences.edit().putInt("level", oldLevel + 1)
                        .putInt("stable_sessions", 0).apply()
                    pendingReannounce = true
                    Log.w(TAG, "Sustained decoder lag; switching next session from " +
                        possible[oldLevel].label + " to " + possible[oldLevel + 1].label)
                } else {
                    Log.w(TAG, "Decoder lag even at lowest hardware profile")
                }
            }
            // Later bursts can enter catch-up again without repeatedly
            // lowering the next-session profile during one connection.
            if (!catchUp) {
                catchUp = true
                return Signal.CATCH_UP
            }
        }

        // Once recovered, stop dropping decoded output frames. Never change
        // sender negotiation or restart while iPhone is connected.
        if (catchUp && stableSamples >= 6) {
            catchUp = false
            return Signal.RECOVER
        }
        return Signal.NONE
    }

    @Synchronized
    fun endSession() {
        if (sessionSinceMs == 0L) return
        val length = SystemClock.elapsedRealtime() - sessionSinceMs
        sessionSinceMs = 0L
        if (degradedInSession || length < 60_000L || stableSamples < 15) {
            preferences.edit().putInt("stable_sessions", 0).apply()
            return
        }
        // Slow re-upgrade: only after three long, stable mirroring sessions.
        val count = preferences.getInt("stable_sessions", 0) + 1
        if (count < 3) {
            preferences.edit().putInt("stable_sessions", count).apply()
            return
        }
        val level = preferences.getInt("level", 0).coerceIn(0, available.lastIndex)
        if (level > 0) {
            preferences.edit().putInt("level", level - 1).putInt("stable_sessions", 0).apply()
            pendingReannounce = true
            Log.i(TAG, "Three stable sessions: cautiously upgrading next session to " +
                available[level - 1].label)
        } else {
            preferences.edit().putInt("stable_sessions", 0).apply()
        }
    }

    private fun detectProfiles(): List<Profile> {
        val (rawW, rawH) = context.realDisplaySize()
        val displayW = maxOf(rawW, rawH)
        val displayH = minOf(rawW, rawH)

        // Virtual Android devices often report optimistic AVC decoder capabilities.
        // Physical Android TV keeps its normal hardware-based AUTO profile.
        val virtualHint = virtualReceiverHint()
        if (virtualHint != null) {
            val profile = if (displayW >= 1280 && displayH >= 720)
                Profile(1280, 720, 30, "720p30 (virtual)")
            else Profile(
                (minOf(displayW, 960).coerceAtLeast(2) / 2) * 2,
                (minOf(displayH, 540).coerceAtLeast(2) / 2) * 2,
                30,
                "display-fit30 (virtual)"
            )
            Log.i(TAG, "Virtual Android receiver ($virtualHint); conservative " +
                profile.label + " instead of advertised 60 FPS throughput")
            return listOf(profile)
        }
        val decoder = runCatching {
            MediaCodecList(MediaCodecList.REGULAR_CODECS).codecInfos.firstOrNull { info ->
                !info.isEncoder &&
                    info.supportedTypes.any { it.equals(MediaFormat.MIMETYPE_VIDEO_AVC, true) } &&
                    isHardwareDecoder(info)
            }
        }.getOrNull()
        val caps = runCatching {
            decoder?.getCapabilitiesForType(MediaFormat.MIMETYPE_VIDEO_AVC)?.videoCapabilities
        }.getOrNull()
        val supported = candidates.filter { profile ->
            profile.width <= displayW && profile.height <= displayH &&
                caps?.let {
                    runCatching {
                        it.areSizeAndRateSupported(
                            profile.width, profile.height, profile.fps.toDouble()
                        )
                    }.getOrDefault(false)
                } == true
        }
        // AUTO favors stability: start at 720p30, then learn within 30 FPS profiles.
        if (supported.isNotEmpty()) return supported

        // Incomplete manufacturer codec metadata is common. Avoid black-screen
        // by starting at a conservative size and allowing future diagnostics.
        Log.w(TAG, "No reliable hardware H.264 throughput data; use safe 720p30")
        return listOf(Profile(1280, 720, 30, "720p30 (fallback)"))
    }

    private fun virtualReceiverHint(): String? {
        // Build properties are only heuristics; some emulators spoof real phones.
        val identity = listOf(
            Build.MANUFACTURER, Build.BRAND, Build.MODEL, Build.DEVICE,
            Build.PRODUCT, Build.HARDWARE, Build.FINGERPRINT
        ).joinToString(" ") { it.orEmpty() }.lowercase()
        return listOf(
            "bluestacks", "vbox", "virtualbox", "ranchu", "goldfish",
            "sdk_gphone", "emulator", "generic"
        ).firstOrNull { identity.contains(it) }
    }

    private fun isHardwareDecoder(info: MediaCodecInfo): Boolean =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) info.isHardwareAccelerated
        else {
            val name = info.name.lowercase()
            !name.contains("google") && !name.contains("ffmpeg") &&
                !name.startsWith("c2.android") && !name.contains("software")
        }

    private companion object {
        const val TAG = "XStageMirrorAutoQuality"
        const val SAMPLE_MS = 2_000L
    }
}
