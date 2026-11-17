package app.airshow.tv

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import java.io.File

/**
 * Remove app-private update APKs only AFTER the new app has been installed.
 *
 * The installer must retain access to its FileProvider URI until Android has
 * completed installation. Never delete the staged file immediately after
 * ACTION_VIEW; the user may still be reviewing the system install dialog.
 *
 * Version comparison against installed BuildConfig avoids deleting a future
 * update that the user has not yet approved.
 */
internal object MirrorUpdateCleanup {
    private const val TAG = "XStageMirrorCleanup"
    private val STAGED_APK = Regex("""^xstage-mirror-update-([0-9]{1,10})\.apk$""")

    fun purgeInstalled(context: Context) {
        val installedVersion = BuildConfig.VERSION_CODE.toLong()
        val cacheFiles: Array<File> = context.cacheDir.listFiles() ?: return
        for (file in cacheFiles) {
            if (!file.isFile) continue
            val match = STAGED_APK.matchEntire(file.name) ?: continue
            val stagedVersion = match.groupValues[1].toLongOrNull() ?: continue
            // An APK is obsolete only when Android has installed its build.
            if (stagedVersion > installedVersion) continue
            if (!file.delete()) {
                Log.w(TAG, "Could not remove installed update APK: " + file.name)
            }
        }
    }
}

/** System-only, app-targeted broadcast after Android replaces this package. */
class MirrorUpdateCleanupReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_MY_PACKAGE_REPLACED) {
            MirrorUpdateCleanup.purgeInstalled(context)
        }
    }
}
