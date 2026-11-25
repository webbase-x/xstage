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
assert 'ReceiverNamePolicy.isValid(it)' in prefs
policy = (app / "src/main/kotlin/app/airshow/tv/ReceiverNamePolicy.kt").read_text()
editor = (app / "src/main/kotlin/app/airshow/tv/ui/ReceiverNameEditor.kt").read_text()
assert 'const val PREFIX = "X-Stage Mirror TV"' in policy
assert 'const val MAX_NAME_LENGTH = 64' in policy
assert 'fun migratePreviousName(context: Context)' in policy
assert 'prefs.edit().putString(Prefs.SERVER_NAME.key, migrated).apply()' in policy
assert 'fromSuffix(suffixDraft)' in editor
assert 'Text("บันทึกชื่อ"' in editor
assert 'viewModel.set(Prefs.SERVER_NAME, namePreview)' in editor
assert 'enabled = canEdit' in editor
receiver_home = (app / "src/main/kotlin/app/airshow/tv/ui/XStageReceiverHome.kt").read_text()
assert 'XStageReceiverHome(' in ui
assert 'ReceiverNameEditor(viewModel, canEdit = true, onFinished = { editingName = false })' in receiver_home
assert 'text = serverName,' in receiver_home
assert 'text = "พร้อมรับภาพ"' not in receiver_home  # status comes from actual running state
assert 'state == ServerState.RUNNING -> "พร้อมรับภาพ"' in receiver_home
assert 'viewModel::stopServer' not in ui and 'viewModel::startServer' not in ui
assert 'NavigationBar(' not in ui
assert 'ReceiverSetupQr(serverName)' not in ui
assert 'Text("ตั้งค่า"' in receiver_home
assert 'BuildConfig.VERSION_NAME' in receiver_home
assert 'BuildConfig.VERSION_CODE' in receiver_home

assert 'val editOpen = true' in editor
assert '.imePadding(),' not in editor
assert 'ReceiverNamePolicy.migratePreviousName(this)' in (app / "src/main/kotlin/app/airshow/tv/MainActivity.kt").read_text()


home = (app / "src/main/kotlin/app/airshow/tv/TvHomeShortcut.kt").read_text()
assert "isRequestPinShortcutSupported" in home and "requestPinShortcut(shortcut, null)" in home
assert "Intent.CATEGORY_HOME" in home and "Intent.CATEGORY_LAUNCHER" in home
assert 'fun request(' in (app / "src/main/kotlin/app/airshow/tv/TvHomeShortcut.kt").read_text()
assert (app / "src/main/res/drawable/banner.png").exists()
assert (app / "src/main/res/drawable-xhdpi/banner.png").exists()
from PIL import Image
for path, size in [
    (app / "src/main/res/drawable/banner.png", (320,180)),
    (app / "src/main/res/drawable-xhdpi/banner.png", (640,360)),
]:
    with Image.open(path) as banner:
        assert banner.size == size, (path, banner.size)
        assert banner.convert("RGB").getpixel((0,0)) == (255,255,255), "TV banner corner must be white"
        assert banner.convert("RGB").getpixel((banner.width-1,banner.height-1)) == (255,255,255)


assert 'bool("require_pin", false' in prefs
assert 'bool("allow_new_conn", false' in prefs
assert 'bool("boot_auto_start", true' in prefs
assert 'bool("auto_start", true' in prefs
assert 'bool("run_in_background", true' in prefs
assert 'bool("advertise_mirroring", true' in prefs
assert 'int("max_fps", 30,' in prefs
assert 'str("h265", OFF,' in prefs
service = (app / "src/main/kotlin/app/airshow/tv/service/AirPlayService.kt").read_text()
renderer = (app / "src/main/kotlin/app/airshow/tv/renderer/VideoRenderer.kt").read_text()
discovery = (app / "src/main/kotlin/app/airshow/tv/discovery/NsdServiceManager.kt").read_text()
assert "if (auto) minOf(maxW, 1920)" in service
assert "if (auto) minOf(maxH, 1080)" in service
assert "prewarmPipeline()" in service and "fun prewarmPipeline()" in renderer
assert "First video packet after " in service
assert "Negotiated video size after " in service
assert "Receiver startup: " in service
assert "FEED_WAIT_US = 5_000L" in renderer
assert "FEED_RETRIES = 5" in renderer
assert "FIRST_FEED_RETRIES = 20" in renderer
assert "700L, 1_800L, 4_000L, 8_000L" in discovery
assert "removeCallbacksAndMessages(null)" in discovery
assert "registerAttempt(service, next)" in discovery
assert "30_000L" in discovery and "if (released) return" in discovery
assert "wasPending" in discovery
assert "250_000_000L" in renderer
assert "maxOf(now, target)" in renderer
assert "_ptsBaseUs = Long.MIN_VALUE" in renderer
assert 'ReceiverSetupQr(serverName)' not in ui
assert (app / "src/main/kotlin/app/airshow/tv/ui/ReceiverSetupQr.kt").exists()
updater = (app / "src/main/kotlin/app/airshow/tv/MirrorUpdateManager.kt").read_text()
activity = (app / "src/main/kotlin/app/airshow/tv/MainActivity.kt").read_text()

# TV keyboard and remote usability: name editor is part of the scrolling
# overview, not an obscured modal dialog. Enter and IME Done both save.
assert 'AlertDialog(' not in editor
assert 'keyboardActions = KeyboardActions(onDone = { saveName() })' in editor
assert 'Key.Enter' in editor and 'Key.NumPadEnter' in editor
assert 'fieldBringIntoView.bringIntoView()' in editor
assert 'up = openFocus; down = saveFocus' in editor
assert 'right = cancelFocus' in editor and 'left = saveFocus' in editor
assert '.imePadding()' in receiver_home
assert '.verticalScroll(rememberScrollState())' in receiver_home
assert '.focusGroup()' in receiver_home
assert 'Text(if (editingName)' in receiver_home
assert 'if (mirroringActive && connections > 0)' in receiver_home
assert 'window.setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE)' in activity
settings = (app / "src/main/kotlin/app/airshow/tv/ui/SettingsScreen.kt").read_text()
assert 'FlowRow(modifier = Modifier.focusGroup()' in settings
assert 'selectedContainerColor = MaterialTheme.colorScheme.secondary' in settings
assert 'choiceFocus[index]' in settings
assert 'forEachIndexed { index, (key, label)' in settings
assert 'right = choiceFocus[index + 1]' in settings
assert 'else if (tab == Tab.OVERVIEW)' in ui
assert 'SettingsScreen(viewModel)' in ui
theme_text = (app / "src/main/kotlin/app/airshow/tv/ui/theme/Theme.kt").read_text()
assert 'onSurfaceVariant = Color(0xFFE1EAF8)' in theme_text


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
assert 'BackHandler(enabled = !confirmExit.value)' in activity
assert 'title = { Text("ปิด X-Stage Mirror TV?") }' in activity
assert 'Text("ปิด")' in activity and 'Text("ไม่ปิด")' in activity
assert 'viewModel.stopServer()' in activity and 'finish()' in activity
assert 'if (svc.serverState.value == AirPlayService.ServerState.STOPPED && hasLocalNetwork())' in activity
assert 'viewModel.pref(Prefs.AUTO_START).value &&' not in activity
assert 'BackHandler { fullscreen = false }' not in ui
assert 'BackHandler { viewModel.stopVideoPlayback() }' in ui
assert 'BackHandler(enabled = tab != Tab.OVERVIEW && !videoScreen)' in ui
assert 'BackHandler(enabled = editingName)' in receiver_home
assert 'onFinished = { editingName = false }' in receiver_home
assert 'onFinished()' in editor
video_player = (app / "src/main/kotlin/app/airshow/tv/renderer/AirPlayVideoPlayer.kt").read_text()
assert 'VOD_BUFFERING_TIMEOUT_MS = 18_000L' in video_player
assert 'LIVE_BUFFERING_TIMEOUT_MS = 12_000L' in video_player
assert 'LIVE_MAX_RECOVERIES = 3' in video_player
assert '_recoverOrFinish("live playlist ended")' in video_player
assert 'if (failingPlayer != null && player === failingPlayer)' in video_player
assert 'current.seekToDefaultPosition()' in video_player
assert 'current.isCurrentMediaItemLive || lastKnownLive' in video_player
assert 'current.stop()' in video_player and 'current.prepare()' in video_player
assert 'consecutiveRecoveries = 0' in video_player
assert 'mainHandler.removeCallbacks(_stallWatchdog)' in video_player
assert "checkMirrorUpdateNow" in settings
assert "ReceiverNameEditor(viewModel, canEdit = activeConnections == 0)" in settings
assert 'label = stringResource(R.string.setting_server_name)' not in settings

assert "setting_auto_fullscreen" not in settings
assert "setting_auto_start" not in settings
assert "AUTO Performance" in settings
assert "ลื่นไหล 720p" not in settings
quality = (app / "src/main/kotlin/app/airshow/tv/service/MirrorAutoQuality.kt").read_text()
assert "MediaCodecList.REGULAR_CODECS" in quality
assert "virtualReceiverHint()" in quality
assert 'Profile(1280, 720, 30, "720p30 (virtual)")' in quality
assert "areSizeAndRateSupported" in quality
assert "getSharedPreferences" in quality and "stable_sessions" in quality
assert "badSamples >= 3" in quality and "Signal.CATCH_UP" in quality
assert 'Profile(1920, 1080, 30, "1080p30")' in quality
assert 'Profile(1280, 720, 30, "720p30")' in quality
assert 'Profile(1920, 1080, 60' not in quality
assert 'Profile(1280, 720, 60' not in quality
assert 'possible.indexOfFirst { it.width <= 1280 }' in quality
assert "SAMPLE_MS = 2_000L" in quality
assert "Never terminate" in quality
assert "mirrorAutoQuality.choose()" in service
assert "mirrorAutoQuality.sample(" in service
assert "videoRenderer.decodedFrameCount" in service
assert "decodedFrameCount" in renderer
assert "decoderBacklog" in quality
assert "mirrorAutoQuality.startSession()" in service
assert "mirrorAutoQuality.endSession()" in service
assert "isRenegotiationPending()" in service
assert "_adaptiveDisplaySize()" in service
assert "catchUpMode" in renderer
assert "c.releaseOutputBuffer(latestDecodedBuffer, false)" in renderer
assert "SHA-256" in updater and "getPackageArchiveInfo" in updater
assert "FileProvider.getUriForFile" in updater
assert "canRequestPackageInstalls()" in updater
assert "github.com/webbase-x/xstage/releases/download/" in updater
assert "https://webbase-x.github.io/xstage/mirror-tv/latest.json" in updater
assert "https://webbase-x.github.io/xstage/mirror-tv/test-latest.json" in updater
assert "https://webbase-x.github.io/xstage/downloads/" in updater
assert "fun checkOnLaunch() = check(manual = false)" in updater
assert "fetchPreview()" in updater and "offerPreview()" in updater
assert 'json.optString("channel") != "test-preview"' in updater
assert "direct_download_sha256" in updater and "PREVIEW_APK_BASE + file" in updater
assert "pendingPreview != null" in updater
assert "Android" in updater and "ลายเซ็น" in updater
assert 'setPositiveButton("เปิดหน้าดาวน์โหลด")' in updater
assert "downloadAndVerify(official)" in updater
assert 'official.signerSha256 == null' in updater
assert 'official.signerSha256 != installedSigner' in updater
assert 'offerIncompatibleOfficial()' in updater
assert 'val persistent = json.optString("signing_mode") == "persistent"' in updater

assert "downloadAndVerify(preview)" not in updater
assert "PackageManager.GET_SIGNING_CERTIFICATES" in updater
assert "signer_sha256" in updater and 'json.optString("signing_mode") == "persistent"' in updater
assert "installedSignerSha256()" in updater
assert "downloadAndVerify(signedPreview)" in updater
assert "preview.signerSha256 == installedSigner" in updater
assert 'json.optString("channel") != "test-preview"' in updater

assert "android.permission.REQUEST_INSTALL_PACKAGES" in open(app / "src/main/AndroidManifest.xml").read()
assert any(x.attrib.get("{http://schemas.android.com/apk/res/android}name") == "android.intent.action.MY_PACKAGE_REPLACED" for x in manifest.iter("action"))
assert any(x.attrib.get("{http://schemas.android.com/apk/res/android}name") == ".MirrorUpdateCleanupReceiver" and x.attrib.get("{http://schemas.android.com/apk/res/android}exported") == "false" for x in manifest.iter("receiver"))
assert 'versionCode = 119' in gradle or __import__('os').environ.get('XSTAGE_MIRROR_BUILD') is not None
assert values["app_name"] == "X-Stage Mirror TV"
assert any(x.attrib.get("{http://schemas.android.com/apk/res/android}name") == "android.intent.category.LEANBACK_LAUNCHER" for x in manifest.iter("category"))
assert (root / "LICENSE").exists()
assert (root / "NOTICE").exists()
print("PASS: Mirror TV minimal auto-ready UI, Back confirmation, quality, mDNS, updater")
