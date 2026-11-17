#!/usr/bin/env python3
"""Fail fast when the branded receiver's essential contract regresses."""
from pathlib import Path
import sys
from xml.etree import ElementTree

root = Path(sys.argv[1]).resolve()
app = root / "app"
gradle = (app / "build.gradle.kts").read_text()
prefs = (app / "src/main/kotlin/app/airshow/tv/Prefs.kt").read_text()
ui = (app / "src/main/kotlin/app/airshow/tv/ui/MainScreen.kt").read_text()
manifest = ElementTree.parse(app / "src/main/AndroidManifest.xml")
res = ElementTree.parse(app / "src/main/res/values/strings.xml")
values = {entry.attrib.get("name"): entry.text for entry in res.getroot() if entry.tag == "string"}
assert 'applicationId = "com.webbasex.xstagemirror.tv"' in gradle
assert 'buildConfig = true' in gradle
assert "zxing:core:3.5.3" in gradle
assert 'str("server_name", "X-Stage Mirror TV"' in prefs
assert 'bool("require_pin", false' in prefs
assert 'bool("allow_new_conn", false' in prefs
assert 'bool("boot_auto_start", true' in prefs
assert 'bool("auto_start", true' in prefs
assert 'bool("run_in_background", true' in prefs
assert 'bool("advertise_mirroring", true' in prefs
assert 'ReceiverSetupQr(serverName)' in ui
assert (app / "src/main/kotlin/app/airshow/tv/ui/ReceiverSetupQr.kt").exists()
updater = (app / "src/main/kotlin/app/airshow/tv/MirrorUpdateManager.kt").read_text()
activity = (app / "src/main/kotlin/app/airshow/tv/MainActivity.kt").read_text()
settings = (app / "src/main/kotlin/app/airshow/tv/ui/SettingsScreen.kt").read_text()
assert "MirrorUpdateCleanup.purgeInstalled(this)" in activity
cleanup = (app / "src/main/kotlin/app/airshow/tv/MirrorUpdateCleanup.kt").read_text()
assert "MY_PACKAGE_REPLACED" in cleanup
assert "BuildConfig.VERSION_CODE" in cleanup
assert "File(context.cacheDir" not in cleanup
assert "xstage-mirror-update-" in cleanup
assert "installedVersion" in cleanup
assert "mirrorUpdates.checkOnLaunch()" in activity
assert "mirrorUpdates.onResume()" in activity
assert "mirrorUpdates.close()" in activity
assert "checkMirrorUpdateNow" in settings
assert "SHA-256" in updater and "getPackageArchiveInfo" in updater
assert "FileProvider.getUriForFile" in updater
assert "canRequestPackageInstalls()" in updater
assert "github.com/webbase-x/xstage/releases/download/" in updater
assert "https://webbase-x.github.io/xstage/mirror-tv/latest.json" in updater
assert "android.permission.REQUEST_INSTALL_PACKAGES" in open(app / "src/main/AndroidManifest.xml").read()
assert any(x.attrib.get("{http://schemas.android.com/apk/res/android}name") == "android.intent.action.MY_PACKAGE_REPLACED" for x in manifest.iter("action"))
assert any(x.attrib.get("{http://schemas.android.com/apk/res/android}name") == ".MirrorUpdateCleanupReceiver" and x.attrib.get("{http://schemas.android.com/apk/res/android}exported") == "false" for x in manifest.iter("receiver"))
assert 'versionCode = 102' in gradle or __import__('os').environ.get('XSTAGE_MIRROR_BUILD') is not None
assert values["app_name"] == "X-Stage Mirror TV"
assert any(x.attrib.get("{http://schemas.android.com/apk/res/android}name") == "android.intent.category.LEANBACK_LAUNCHER" for x in manifest.iter("category"))
assert (root / "LICENSE").exists()
assert (root / "NOTICE").exists()
print("PASS: one-APK receiver, verified installer, safe post-install cleanup, Android TV launcher and QR")
