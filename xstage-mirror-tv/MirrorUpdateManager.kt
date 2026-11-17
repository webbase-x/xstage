package app.airshow.tv

import android.app.Activity
import android.app.AlertDialog
import android.content.ClipData
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.util.Log
import android.widget.Toast
import androidx.core.content.FileProvider
import androidx.lifecycle.Lifecycle
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * A built-in, opt-in Android package installer handoff, not a silent installer.
 * Only pinned HTTPS metadata and same-repository GitHub release assets are trusted.
 * Android's PackageInstaller validates the UPDATE's signing certificate.
 *
 * No binary components are downloaded to make AirPlay work: all receiver libraries
 * are already bundled in the installed APK. Network access here is updates only.
 */
class MirrorUpdateManager(private val activity: MainActivity) {
    private val worker = Executors.newSingleThreadExecutor()
    private val ui = Handler(Looper.getMainLooper())
    private val checking = AtomicBoolean(false)
    @Volatile private var closed = false
    private var pendingInstall: File? = null
    private var permissionPageOpened = false
    private var pendingPreview: Preview? = null
    private var alertedPreviewBuild = 0
    private var pendingIncompatibleOfficial: Update? = null
    private var alertedIncompatibleOfficialBuild = 0

    private data class Update(
        val version: String, val code: Int, val sha256: String, val file: String,
        val url: String, val signerSha256: String? = null
    )

    // Preview builds can be installed in-place ONLY when the publisher pins a
    // persistent private signing identity matching the currently installed APK.
    // Older CI debug-signed installs receive a download notice, never a forced update.
    private data class Preview(
        val version: String, val code: Int, val url: String,
        val sha256: String, val file: String, val signerSha256: String?
    )

    fun checkOnLaunch() = check(manual = false)

    fun checkNow() = check(manual = true)

    private fun check(manual: Boolean) {
        if (closed || !checking.compareAndSet(false, true)) return
        if (manual) toast("กำลังตรวจสอบอัปเดต X-Stage Mirror TV…")
        worker.execute {
            try {
                // Signed production releases retain the existing verified, system-approved
                // update flow. A missing production release must NOT suppress preview
                // announcements for installations made from the TEST channel.
                val official = try {
                    fetchLatest()
                } catch (e: Exception) {
                    Log.w(TAG, "Signed release channel check failed; checking preview separately", e)
                    null
                }
                if (official != null && official.code > BuildConfig.VERSION_CODE) {
                    // Android cannot update an existing package signed by a
                    // different key. Check BEFORE downloading a large APK.
                    // This is especially important for legacy debug Build 107.
                    val installedSigner = installedSignerSha256()
                    if (official.signerSha256 == null ||
                        official.signerSha256 != installedSigner) {
                        onMain {
                            pendingIncompatibleOfficial = official
                            offerIncompatibleOfficial()
                        }
                    } else {
                        if (manual) toast("พบรุ่นทางการ " + official.version + " กำลังดาวน์โหลด…")
                        val file = downloadAndVerify(official)
                        onMain {
                            pendingInstall = file
                            offerInstall()
                        }
                    }
                } else {
                    val preview = fetchPreview()
                    if (preview != null && preview.code > BuildConfig.VERSION_CODE) {
                        val installedSigner = installedSignerSha256()
                        if (preview.signerSha256 != null &&
                            preview.signerSha256 == installedSigner) {
                            if (manual) toast("พบ APK ลายเซ็นตรงกัน v" +
                                preview.version + " กำลังดาวน์โหลด…")
                            val signedPreview = Update(preview.version, preview.code,
                                preview.sha256, preview.file, preview.url)
                            val file = downloadAndVerify(signedPreview)
                            onMain {
                                pendingInstall = file
                                offerInstall()
                            }
                        } else {
                            onMain {
                                pendingPreview = preview
                                offerPreview()
                            }
                        }
                    } else if (manual) {
                        toast("ไม่พบรุ่นใหม่กว่า v" + BuildConfig.VERSION_NAME +
                            " (Build " + BuildConfig.VERSION_CODE + ")")
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "Update channels unavailable", e)
                if (manual) toast("ตรวจสอบอัปเดตไม่สำเร็จ: " + (e.message ?: "เครือข่ายไม่พร้อม"))
            } finally {
                checking.set(false)
            }
        }
    }

    private fun fetchJsonMetadata(endpoint: String): JSONObject {
        val conn = URL(endpoint).openConnection() as HttpURLConnection
        conn.connectTimeout = 12000
        conn.readTimeout = 15000
        conn.useCaches = false
        conn.setRequestProperty("Cache-Control", "no-cache")
        try {
            if (conn.responseCode != 200) {
                throw IllegalStateException("Update server HTTP " + conn.responseCode)
            }
            val out = ByteArrayOutputStream()
            conn.inputStream.use { input ->
                val buffer = ByteArray(4096)
                while (true) {
                    val n = input.read(buffer)
                    if (n < 0) break
                    if (out.size() + n > 8192) {
                        throw IllegalArgumentException("Update metadata too large")
                    }
                    out.write(buffer, 0, n)
                }
            }
            return JSONObject(out.toString(StandardCharsets.UTF_8.name()))
        } finally {
            conn.disconnect()
        }
    }

    private fun fetchLatest(): Update? {
        val json = fetchJsonMetadata(METADATA)
        if (!json.optBoolean("available", false)) return null
        if (json.optString("package") != activity.packageName) {
            throw IllegalArgumentException("Official update package mismatch")
        }
        val version = json.optString("version")
        val code = json.optInt("build", 0)
        val checksum = json.optString("sha256").lowercase(Locale.ROOT)
        val file = json.optString("file")
        val signer = json.optString("signer_sha256").lowercase(Locale.ROOT)
        val persistent = json.optString("signing_mode") == "persistent"
        if (!version.matches(Regex("""[0-9]+[.][0-9]+[.][0-9]+""")) ||
            code <= 0 || !checksum.matches(Regex("[0-9a-f]{64}")) ||
            file != "X-Stage-Mirror-TV-v" + version + "-build" + code + ".apk" ||
            !persistent || !signer.matches(Regex("[0-9a-f]{64}"))) {
            throw IllegalArgumentException("Invalid official update metadata")
        }
        val url = "https://github.com/webbase-x/xstage/releases/download/" +
            "xstage-mirror-tv-v" + version + "-build" + code + "/" + file
        return Update(version, code, checksum, file, url, signer)
    }

    private fun fetchPreview(): Preview? {
        val json = fetchJsonMetadata(PREVIEW_METADATA)
        if (!json.optBoolean("available", false)) return null
        if (json.optString("channel") != "test-preview" ||
            json.optString("package") != activity.packageName) {
            throw IllegalArgumentException("Invalid preview update channel/package")
        }
        val version = json.optString("version")
        val code = json.optInt("build", 0)
        val checksum = json.optString("sha256").lowercase(Locale.ROOT)
        val file = json.optString("file")
        val url = json.optString("direct_download_url")
        if (!version.matches(Regex("""[0-9]+[.][0-9]+[.][0-9]+""")) ||
            code <= 0 || !checksum.matches(Regex("[0-9a-f]{64}")) ||
            file != "X-Stage-Mirror-TV-test-v" + version + "-build" + code + ".apk" ||
            !json.optBoolean("direct_download_available", false) ||
            json.optString("direct_download_file") != file ||
            !json.optString("direct_download_sha256").equals(checksum, ignoreCase = true) ||
            url != PREVIEW_APK_BASE + file) {
            throw IllegalArgumentException("Invalid preview APK link or SHA-256 metadata")
        }
        val signer = json.optString("signer_sha256").lowercase(Locale.ROOT)
        val persistent = json.optString("signing_mode") == "persistent" &&
            signer.matches(Regex("[0-9a-f]{64}"))
        return Preview(version, code, url, checksum, file,
            if (persistent) signer else null)
    }

    /**
     * Checks the actual installed package's certificate, not a preference or
     * server-provided device ID. Android remains the final update signature gate.
     * A legacy debug certificate never qualifies for a persistent-key update.
     */
    private fun installedSignerSha256(): String? {
        return try {
            val manager = activity.packageManager
            val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                PackageManager.GET_SIGNING_CERTIFICATES
            } else {
                @Suppress("DEPRECATION")
                PackageManager.GET_SIGNATURES
            }
            val details = if (Build.VERSION.SDK_INT >= 33) {
                manager.getPackageInfo(activity.packageName,
                    PackageManager.PackageInfoFlags.of(flags.toLong()))
            } else {
                @Suppress("DEPRECATION")
                manager.getPackageInfo(activity.packageName, flags)
            }
            val signers = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                details.signingInfo?.apkContentsSigners
            } else {
                @Suppress("DEPRECATION")
                details.signatures
            }
            val signer = signers?.singleOrNull() ?: return null
            MessageDigest.getInstance("SHA-256").digest(signer.toByteArray())
                .joinToString("") { "%02x".format(it) }
        } catch (e: Exception) {
            Log.w(TAG, "Unable to verify installed signing certificate", e)
            null
        }
    }

    /** A different signer is NOT an installable update; do not delete user data. */
    private fun offerIncompatibleOfficial() {
        val update = pendingIncompatibleOfficial ?: return
        if (!activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) return
        if (alertedIncompatibleOfficialBuild == update.code) return
        alertedIncompatibleOfficialBuild = update.code
        pendingIncompatibleOfficial = null
        AlertDialog.Builder(activity)
            .setTitle("พบรุ่นใหม่ แต่ยังติดตั้งทับไม่ได้")
            .setMessage(
                "พบ X-Stage Mirror TV v" + update.version + " (Build " + update.code + ").\\n\\n" +
                "ลายเซ็นของ APK ใหม่ไม่ตรงกับแอปในเครื่อง หรืออ่านลายเซ็นเดิมไม่ได้ " +
                "Android ไม่อนุญาตให้ติดตั้งทับ เพื่อป้องกันการปลอมแปลงแอป\\n\\n" +
                "อย่าเพิ่งถอนแอปเดิม เพราะชื่อเครื่องรับและการตั้งค่าอาจหายไป " +
                "หากมีไฟล์กุญแจลงนามเดิม ผู้พัฒนาต้องสร้าง APK ด้วยกุญแจนั้นจึงจะอัปเดตทับได้"
            )
            .setPositiveButton("ตกลง", null)
            .show()
    }

    private fun offerPreview() {
        val preview = pendingPreview ?: return
        if (!activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) return
        if (alertedPreviewBuild == preview.code) return
        alertedPreviewBuild = preview.code
        pendingPreview = null
        AlertDialog.Builder(activity)
            .setTitle("มี Mirror TV รุ่นทดสอบใหม่ v" + preview.version)
            .setMessage(
                "ตรวจพบ Build " + preview.code + " (เครื่องนี้ Build " +
                BuildConfig.VERSION_CODE + ")\n\n" +
                "APK นี้ใช้กุญแจลงนามไม่ตรงกับแอปที่ติดตั้งอยู่ หรือเป็นรุ่นเก่าที่ใช้กุญแจ Debug ชั่วคราว " +
                "Android จะไม่อนุญาตให้ติดตั้งทับหากลายเซ็นต่างกัน " +
                "การถอนแอปเดิมอาจทำให้ชื่อเครื่องรับและค่าตั้งสูญหาย\n\n" +
                "ต้องการเปิดหน้าดาวน์โหลด APK ที่เว็บไซต์ X-Stage หรือไม่?"
            )
            .setPositiveButton("เปิดหน้าดาวน์โหลด") { _, _ ->
                try {
                    val intent = Intent(Intent.ACTION_VIEW, Uri.parse(preview.url))
                        .addCategory(Intent.CATEGORY_BROWSABLE)
                    activity.startActivity(intent)
                } catch (e: Exception) {
                    Log.w(TAG, "Cannot open preview download in TV browser", e)
                    AlertDialog.Builder(activity)
                        .setTitle("ไม่พบเบราว์เซอร์บนทีวี")
                        .setMessage("เปิดลิงก์นี้จากอุปกรณ์ที่ดาวน์โหลด APK ได้ แล้วส่งไฟล์มาที่กล่องทีวี:\n" +
                            preview.url)
                        .setPositiveButton("ตกลง", null)
                        .show()
                }
            }
            .setNegativeButton("ภายหลัง", null)
            .show()
    }

    private fun downloadAndVerify(update: Update): File {
        val dir = activity.cacheDir
        val dest = File(dir, "xstage-mirror-update-" + update.code + ".apk")
        val partial = File(dir, "xstage-mirror-update-" + update.code + ".apk.part")
        if (partial.exists()) partial.delete()
        val conn = URL(update.url).openConnection() as HttpURLConnection
        conn.connectTimeout = 15000
        conn.readTimeout = 30000
        conn.instanceFollowRedirects = true
        val digest = MessageDigest.getInstance("SHA-256")
        var count = 0L
        try {
            if (conn.responseCode != 200) throw IllegalStateException("APK download HTTP " + conn.responseCode)
            conn.inputStream.use { input ->
                FileOutputStream(partial).use { output ->
                    val buffer = ByteArray(65536)
                    while (true) {
                        val n = input.read(buffer)
                        if (n < 0) break
                        count += n
                        if (count > MAX_APK_BYTES) throw IllegalStateException("APK too large")
                        output.write(buffer, 0, n)
                        digest.update(buffer, 0, n)
                    }
                    output.fd.sync()
                }
            }
            if (count < 1024 * 1024L) throw IllegalStateException("APK truncated")
            val actual = digest.digest().joinToString("") { "%02x".format(it) }
            if (actual != update.sha256) throw SecurityException("APK SHA-256 mismatch")
            @Suppress("DEPRECATION")
            val info = activity.packageManager.getPackageArchiveInfo(partial.absolutePath, 0)
                ?: throw IllegalArgumentException("Downloaded file is not an APK")
            val apkCode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                info.longVersionCode
            } else {
                @Suppress("DEPRECATION")
                info.versionCode.toLong()
            }
            if (info.packageName != activity.packageName || apkCode != update.code.toLong()) {
                throw SecurityException("APK package/version mismatch")
            }
            if (dest.exists() && !dest.delete()) throw IllegalStateException("Unable to replace cached update")
            if (!partial.renameTo(dest)) throw IllegalStateException("Unable to finalize update")
            return dest
        } finally {
            conn.disconnect()
            if (partial.exists()) partial.delete()
        }
    }

    private fun onMain(action: () -> Unit) = ui.post {
        if (!closed && !activity.isFinishing && !activity.isDestroyed) action()
    }

    private fun offerInstall() {
        val file = pendingInstall ?: return
        if (!file.isFile) {
            pendingInstall = null
            return
        }
        if (!activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) return
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
            !activity.packageManager.canRequestPackageInstalls()) {
            if (permissionPageOpened) return
            AlertDialog.Builder(activity)
                .setTitle("อนุญาตติดตั้งการอัปเดต")
                .setMessage("อนุญาต X-Stage Mirror TV ติดตั้งแอปจากแหล่งนี้หนึ่งครั้ง แล้วกลับมาเพื่อเปิดหน้าติดตั้งอัปเดตผ่าน Android")
                .setPositiveButton("เปิดการตั้งค่า") { _, _ ->
                    try {
                        permissionPageOpened = true
                        activity.startActivity(Intent(
                            Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                            Uri.parse("package:" + activity.packageName)
                        ))
                    } catch (e: Exception) {
                        permissionPageOpened = false
                        Log.w(TAG, "Cannot open unknown sources settings", e)
                        toast("ไม่สามารถเปิดการตั้งค่าติดตั้ง APK ได้")
                    }
                }
                .setNegativeButton("ภายหลัง", null)
                .show()
            return
        }
        try {
            val uri = FileProvider.getUriForFile(
                activity, activity.packageName + ".fileprovider", file
            )
            val install = Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, APK_MIME)
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            install.clipData = ClipData.newUri(activity.contentResolver, "X-Stage Mirror TV update", uri)
            pendingInstall = null
            activity.startActivity(install)
            // The platform's installer (not this app) requires user approval.
        } catch (e: Exception) {
            Log.e(TAG, "Unable to start Android package installer", e)
            pendingInstall = file
            toast("ไม่สามารถเปิดหน้าติดตั้งอัปเดตได้")
        }
    }

    fun onResume() {
        if (permissionPageOpened) {
            permissionPageOpened = false
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
                !activity.packageManager.canRequestPackageInstalls()) {
                toast("ยังไม่ได้อนุญาตการติดตั้งอัปเดต")
                return
            }
        }
        if (pendingInstall != null) offerInstall()
        if (pendingPreview != null) offerPreview()
        if (pendingIncompatibleOfficial != null) offerIncompatibleOfficial()
    }

    fun close() {
        closed = true
        worker.shutdownNow()
        ui.removeCallbacksAndMessages(null)
    }

    private fun toast(message: String) {
        onMain { Toast.makeText(activity, message, Toast.LENGTH_LONG).show() }
    }

    private companion object {
        const val TAG = "XStageMirrorUpdate"
        const val METADATA = "https://webbase-x.github.io/xstage/mirror-tv/latest.json"
        const val PREVIEW_METADATA = "https://webbase-x.github.io/xstage/mirror-tv/test-latest.json"
        const val PREVIEW_APK_BASE = "https://webbase-x.github.io/xstage/downloads/"
        const val APK_MIME = "application/vnd.android.package-archive"
        const val MAX_APK_BYTES = 200L * 1024L * 1024L
    }
}
