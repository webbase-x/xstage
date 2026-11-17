#!/usr/bin/env python3
"""Reproducibly adapt pinned GPLv3 AirShow/UxPlay for X-Stage Mirror TV.

Builds an independent Android TV app. The entire upstream source and NOTICE
remain in the generated source package. No iOS companion application is used.
"""
from __future__ import annotations

import sys
import os
import re
from pathlib import Path
from xml.etree import ElementTree as ET
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else None
if ROOT is None or not (ROOT / "LICENSE").is_file():
    raise SystemExit("Usage: prepare_upstream.py <checked-out-upstream-root>")

APP = ROOT / "app"
PKG = "com.webbasex.xstagemirror.tv"
NAME = "X-Stage Mirror TV"
VERSION = os.environ.get("XSTAGE_MIRROR_VERSION", "0.2.0")
BUILD = os.environ.get("XSTAGE_MIRROR_BUILD", "102")
if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", VERSION) or not BUILD.isdecimal() or int(BUILD) <= 0:
    raise SystemExit("Invalid Mirror TV release version/build")

def substitute(path: Path, before: str, after: str) -> None:
    old = path.read_text(encoding="utf-8")
    count = old.count(before)
    if count != 1:
        raise RuntimeError(f"{path}: expected one target, got {count}: {before[:70]!r}")
    path.write_text(old.replace(before, after), encoding="utf-8")

gradle = APP / "build.gradle.kts"
substitute(gradle, 'applicationId = "app.airshow.tv"', f'applicationId = "{PKG}"')
substitute(gradle, 'versionName = "1.0.0"', f'versionName = "{VERSION}"')
substitute(gradle, 'versionCode = 1', f'versionCode = {int(BUILD)}')
# AGP 9 defaults BuildConfig generation off; the updater needs VERSION_CODE.
substitute(gradle, '        prefab = true', '        prefab = true\n        buildConfig = true')
with gradle.open("a", encoding="utf-8") as out:
    out.write('\n// X-Stage QR setup requires no iOS helper app.\ndependencies { implementation("com.google.zxing:core:3.5.3") }\n')

prefs = APP / "src/main/kotlin/app/airshow/tv/Prefs.kt"
substitute(prefs,
           'val SERVER_NAME = str("server_name", "AirShow", restart = true)',
           'val SERVER_NAME = str("server_name", "X-Stage Mirror TV", restart = true) { it.isNotBlank() && it.length <= 64 }')
substitute(prefs, 'val ALLOW_NEW_CONN = bool("allow_new_conn", true, restart = true)',
           'val ALLOW_NEW_CONN = bool("allow_new_conn", false, restart = true)')
assert 'val REQUIRE_PIN = bool("require_pin", false' in prefs.read_text()
assert 'val AUTO_START = bool("auto_start", true)' in prefs.read_text()
assert 'val BOOT_AUTO_START = bool("boot_auto_start", true)' in prefs.read_text()

# Android TV update handoff requires the OS-controlled package installer.
# It is not a silent installer, and no runtime AirPlay modules are fetched.
manifest = APP / "src/main/AndroidManifest.xml"
substitute(manifest,
           '    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />',
           '    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />\n'
           '    <uses-permission android:name="android.permission.REQUEST_INSTALL_PACKAGES" />')
# Only our app's successful package replacement triggers cleanup. The protected
# system action is not exposed as a general exported receiver.
substitute(manifest,
           '        <receiver\n            android:name=".BootReceiver"',
           '        <receiver\n'
           '            android:name=".MirrorUpdateCleanupReceiver"\n'
           '            android:enabled="true"\n'
           '            android:exported="false">\n'
           '            <intent-filter>\n'
           '                <action android:name="android.intent.action.MY_PACKAGE_REPLACED" />\n'
           '            </intent-filter>\n'
           '        </receiver>\n\n'
           '        <receiver\n            android:name=".BootReceiver"')

strings = APP / "src/main/res/values/strings.xml"
text = strings.read_text(encoding="utf-8").replace("AirShow", NAME)
text = text.replace("Mirror your Mac or iPhone", "Mirror your iPhone, iPad or Mac")
text = text.replace("Drop current sender when a new one connects", "Allow another device to replace a connected sender")
text = text.replace("Open Control Center", "Open iPhone Control Center")
# XML validation catches a broken rebrand before Gradle is started.
ET.fromstring(text)
strings.write_text(text, encoding="utf-8")

ui = APP / "src/main/kotlin/app/airshow/tv/ui"
overview = ui / "MainScreen.kt"
needle = '''stringResource(R.string.idle_hint, serverName)
                                },
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.8f),
                                textAlign = TextAlign.Center
                            )'''
replacement = needle + '''
                            Spacer(Modifier.height(12.dp))
                            ReceiverSetupQr(serverName)'''
substitute(overview, needle, replacement)
overlay = Path(__file__).resolve().parent / "ReceiverSetupQr.kt"
(ui / "ReceiverSetupQr.kt").write_text(overlay.read_text(encoding="utf-8"), encoding="utf-8")

# Add a built-in HTTPS + SHA256 updater. Only a newer, verified APK is handed
# to Android's standard installer; Android decides whether user confirmation
# and unknown-source permission are required.
updater = Path(__file__).resolve().parent / "MirrorUpdateManager.kt"
pkg_dir = APP / "src/main/kotlin/app/airshow/tv"
(pkg_dir / "MirrorUpdateManager.kt").write_text(updater.read_text(encoding="utf-8"), encoding="utf-8")
cleanup = Path(__file__).resolve().parent / "MirrorUpdateCleanup.kt"
(pkg_dir / "MirrorUpdateCleanup.kt").write_text(cleanup.read_text(encoding="utf-8"), encoding="utf-8")

activity = pkg_dir / "MainActivity.kt"
substitute(activity,
           '    private val viewModel: MainViewModel by viewModels()',
           '    private val viewModel: MainViewModel by viewModels()\n'
           '    private lateinit var mirrorUpdates: MirrorUpdateManager')
substitute(activity,
           '        enableEdgeToEdge()',
           '        enableEdgeToEdge()\n'
           '        // Remove only downloaded APKs whose build is already installed.\n'
           '        MirrorUpdateCleanup.purgeInstalled(this)\n'
           '        mirrorUpdates = MirrorUpdateManager(this)\n'
           '        mirrorUpdates.checkOnLaunch()')
substitute(activity,
           '    override fun onStart() {',
           '    fun checkMirrorUpdateNow() = mirrorUpdates.checkNow()\n\n'
           '    override fun onResume() {\n'
           '        super.onResume()\n'
           '        mirrorUpdates.onResume()\n'
           '    }\n\n'
           '    override fun onStart() {')
substitute(activity,
           '    override fun onDestroy() {',
           '    override fun onDestroy() {\n'
           '        mirrorUpdates.close()')

settings = ui / "SettingsScreen.kt"
substitute(settings,
           'fun SettingsScreen(viewModel: MainViewModel) {',
           'fun SettingsScreen(viewModel: MainViewModel) {\n'
           '    val mirrorActivity = LocalContext.current as? app.airshow.tv.MainActivity')
substitute(settings,
           '        SectionHeader(stringResource(R.string.section_server))',
           '        SectionHeader(stringResource(R.string.section_server))\n'
           '        Button(\n'
           '            onClick = { mirrorActivity?.checkMirrorUpdateNow() },\n'
           '            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)\n'
           '        ) { Text("ตรวจสอบอัปเดต X-Stage Mirror TV") }')

# Preserve original attribution and build a distinctive launcher/TV banner.
font_paths = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
]
font_path = next((p for p in font_paths if Path(p).exists()), None)

def font(size):
    return ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()

def mark(size):
    img = Image.new("RGBA", (size, size), (12, 20, 42, 255))
    dr = ImageDraw.Draw(img)
    w = max(2, size // 9)
    m = size // 4
    dr.line([(m,m),(size-m,size-m)], fill=(55, 207, 235, 255), width=w)
    dr.line([(size-m,m),(m,size-m)], fill=(246, 169, 69, 255), width=w)
    return img

def banner(size):
    w,h = size
    im = Image.new("RGB",size,(9,18,38))
    d = ImageDraw.Draw(im)
    icon = mark(int(h*0.63)).convert("RGB")
    im.paste(icon, (int(w*0.05),int(h*0.18)))
    tx = int(w*0.39)
    d.text((tx,int(h*0.29)), "X-STAGE", fill=(244,249,255), font=font(int(h*0.17)))
    d.text((tx,int(h*0.52)), "MIRROR TV", fill=(67,214,239), font=font(int(h*0.13)))
    d.text((tx,int(h*0.72)), "AirPlay receiver", fill=(179,193,217), font=font(int(h*0.065)))
    return im

for folder,size in [("mipmap-mdpi",48),("mipmap-hdpi",72),("mipmap-xhdpi",96),
                    ("mipmap-xxhdpi",144),("mipmap-xxxhdpi",192)]:
    for file_name in ("ic_launcher.png","ic_launcher_round.png"):
        mark(size).save(APP / "src/main/res" / folder / file_name)

mark(384).save(APP / "src/main/res/drawable-xxxhdpi/airshow_mark.png")
mark(432).save(APP / "src/main/res/drawable-xxxhdpi/ic_launcher_foreground.png")
banner((320,180)).save(APP / "src/main/res/drawable/banner.png")
banner((640,360)).save(APP / "src/main/res/drawable-xhdpi/banner.png")

# Keep GPLv3 license and upstream notices inside the APK source distribution.
(ROOT / "XSTAGE_MIRROR_NOTICE.txt").write_text(
    "X-Stage Mirror TV is an independently branded build of AirShow (GPL-3.0), "
    "based on jqssun/android-airplay-server and UxPlay. Original LICENSE and NOTICE "
    "are preserved. This is not affiliated with or endorsed by Apple or TrueID. "
    "Source recipe: https://github.com/webbase-x/xstage/tree/main/xstage-mirror-tv\n",
    encoding="utf-8",
)
print("Prepared X-Stage Mirror TV:", PKG)
