package app.airshow.tv

import android.content.Context
import android.content.Intent
import android.content.pm.ShortcutInfo
import android.content.pm.ShortcutManager
import android.graphics.drawable.Icon
import android.os.Build
import android.widget.Toast

/**
 * User-requested TV Home shortcut. Android TV/TrueID launchers vary.
 * Use the official pin-shortcut confirmation when available; otherwise show
 * how to select the app in the TV Launcher's Favorite Apps row.
 */
object TvHomeShortcut {
    fun request(context: Context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = context.getSystemService(ShortcutManager::class.java)
            if (manager?.isRequestPinShortcutSupported == true) {
                val shortcutIntent = Intent(context, MainActivity::class.java)
                    .setAction(Intent.ACTION_MAIN)
                    .addCategory(Intent.CATEGORY_LAUNCHER)
                val shortcut = ShortcutInfo.Builder(context, "xstage-mirror-tv-home")
                    .setShortLabel("X-Stage Mirror TV")
                    .setLongLabel("X-Stage Mirror TV · AirPlay Receiver")
                    .setIcon(Icon.createWithResource(context, R.mipmap.ic_launcher))
                    .setIntent(shortcutIntent)
                    .build()
                if (manager.requestPinShortcut(shortcut, null)) {
                    Toast.makeText(context, "ยืนยันเพิ่ม X-Stage Mirror TV ที่หน้าหลักทีวี", Toast.LENGTH_LONG).show()
                    return
                }
            }
        }
        Toast.makeText(
            context,
            "หน้า Home > แอปโปรด > เพิ่มแอป (+) > X-Stage Mirror TV",
            Toast.LENGTH_LONG
        ).show()
        runCatching {
            context.startActivity(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME))
        }
    }
}
