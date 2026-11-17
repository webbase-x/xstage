package com.webbasex.xstage;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.ShortcutInfo;
import android.content.pm.ShortcutManager;
import android.graphics.drawable.Icon;
import android.os.Build;
import android.widget.Toast;

/**
 * User-initiated TV home icon action. Launchers control Favorites: request a
 * pinned app shortcut where supported, otherwise open the TV home so the
 * owner can select "Add app to favorites" with the remote.
 */
public final class TvHomeShortcut {
    private TvHomeShortcut() {}

    public static void request(Activity activity) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            try {
                ShortcutManager shortcuts = activity.getSystemService(ShortcutManager.class);
                if (shortcuts != null && shortcuts.isRequestPinShortcutSupported()) {
                    Intent launch = new Intent(activity, MainActivity.class)
                            .setAction(Intent.ACTION_MAIN)
                            .addCategory(Intent.CATEGORY_LAUNCHER)
                            .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP);
                    ShortcutInfo shortcut = new ShortcutInfo.Builder(activity, "xstage-karaoke-tv-home")
                            .setShortLabel("X-Stage Karaoke")
                            .setLongLabel("X-Stage Karaoke Android TV")
                            .setIcon(Icon.createWithResource(activity, R.drawable.xstage_app_icon))
                            .setIntent(launch)
                            .build();
                    if (shortcuts.requestPinShortcut(shortcut, null)) {
                        Toast.makeText(activity, "ยืนยันเพิ่ม X-Stage Karaoke ที่หน้าหลักทีวี",
                                Toast.LENGTH_LONG).show();
                        return;
                    }
                }
            } catch (RuntimeException ignored) {
                // TV/TrueID launchers may not implement shortcut pinning.
            }
        }
        Toast.makeText(activity,
                "บนหน้า Home: แอปโปรด > เพิ่มแอป (+) > X-Stage Karaoke",
                Toast.LENGTH_LONG).show();
        try {
            Intent home = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME);
            activity.startActivity(home);
        } catch (RuntimeException ignored) {
            // User can always press the physical HOME key instead.
        }
    }
}
