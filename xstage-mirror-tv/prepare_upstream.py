#!/usr/bin/env python3
"""Reproducibly adapt pinned GPLv3 AirShow/UxPlay for X-Stage Mirror TV.

Builds an independent Android TV app. The entire upstream source and NOTICE
remain in the generated source package. No iOS companion application is used.
"""
from __future__ import annotations

import sys
import subprocess
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
VERSION = os.environ.get("XSTAGE_MIRROR_VERSION", "0.2.17")
BUILD = os.environ.get("XSTAGE_MIRROR_BUILD", "119")
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
           'val SERVER_NAME = str("server_name", "X-Stage Mirror TV", restart = true) { ReceiverNamePolicy.isValid(it) }')
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
                            Spacer(Modifier.height(10.dp))
                            ReceiverNameEditor(viewModel, canEdit = connections == 0)
                            Spacer(Modifier.height(4.dp))
                            Text(
                                "v${app.airshow.tv.BuildConfig.VERSION_NAME} · Build ${app.airshow.tv.BuildConfig.VERSION_CODE}",
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            Spacer(Modifier.height(8.dp))
                            val homeShortcutContext = LocalContext.current
                            OutlinedButton(
                                enabled = connections == 0,
                                onClick = { app.airshow.tv.TvHomeShortcut.request(homeShortcutContext) }
                            ) { Text("☆ เพิ่มแอปที่หน้าหลักทีวี") }
                            Spacer(Modifier.height(12.dp))
                            ReceiverSetupQr(serverName)'''
substitute(overview, needle, replacement)
# The full, user-selected name is the visible main-page headline, not a
# secondary Settings-only value. Keep brand in the app label and launcher.
substitute(overview,
           'text = stringResource(R.string.app_name),',
           'text = serverName,')
substitute(overview,
           'style = MaterialTheme.typography.displaySmall,',
           'style = MaterialTheme.typography.headlineMedium,')
# The original overview centers a fixed-height stack. On 720p Android TV,
# adding the receiver-name editor and QR made the lower controls overlap or
# disappear. Keep the same layout but give its content a bounded scroll viewport
# which responds to keyboard insets and TV remote focus.
substitute(overview,
           'import androidx.compose.foundation.focusable',
           'import androidx.compose.foundation.focusable\nimport androidx.compose.foundation.focusGroup\nimport androidx.compose.foundation.verticalScroll')
substitute(overview,
           '    Column(modifier = Modifier.fillMaxSize()) {\n        // content area',
           '    Column(modifier = Modifier.fillMaxSize().imePadding()) {\n        // content area')
substitute(overview,
           'horizontalAlignment = Alignment.CenterHorizontally,\n                        modifier = Modifier.padding(horizontal = 24.dp)',
           'horizontalAlignment = Alignment.CenterHorizontally,\n'
           '                        modifier = Modifier.fillMaxWidth().focusGroup()\n'
           '                            .verticalScroll(androidx.compose.foundation.rememberScrollState())\n'
           '                            .padding(horizontal = 24.dp)')
# Group bottom tabs, and make the selected tab/readable text obvious.
substitute(overview,
           '    var tab by remember { mutableStateOf(Tab.OVERVIEW) }',
           '    var tab by remember { mutableStateOf(Tab.OVERVIEW) }\n'
           '    val tabFocus = remember { Tab.entries.map { FocusRequester() } }')
substitute(overview,
           '                    NavigationBar {\n                        Tab.entries.forEach { t ->',
           '                    NavigationBar(modifier = Modifier.focusGroup()) {\n'
           '                        Tab.entries.forEachIndexed { index, t ->')
substitute(overview,
           'label = { Text(stringResource(t.labelRes)) },\n'
           '                                modifier = Modifier.dpadFocus()',
           'label = { Text(stringResource(t.labelRes),\n'
           '                                    fontWeight = if (tab == t) FontWeight.Bold else FontWeight.Medium) },\n'
           '                                colors = NavigationBarItemDefaults.colors(\n'
           '                                    selectedIconColor = androidx.compose.ui.graphics.Color(0xFF082A3C),\n'
           '                                    selectedTextColor = androidx.compose.ui.graphics.Color(0xFFE8FAFF),\n'
           '                                    indicatorColor = androidx.compose.ui.graphics.Color(0xFF7AE7FF),\n'
           '                                    unselectedIconColor = androidx.compose.ui.graphics.Color(0xFFC8D5E8),\n'
           '                                    unselectedTextColor = androidx.compose.ui.graphics.Color(0xFFC8D5E8)\n'
           '                                ),\n'
           '                                modifier = Modifier.focusRequester(tabFocus[index])\n'
           '                                    .focusProperties {\n'
           '                                        if (index > 0) left = tabFocus[index - 1]\n'
           '                                        if (index < tabFocus.lastIndex) right = tabFocus[index + 1]\n'
           '                                    }.dpadFocus()')
# Replace the busy upstream home/transport surface with a calm receiver view.
# Perform this after upstream UI substitutions so they remain pinned and audited.
minimal_home = Path(__file__).resolve().parent / "XStageReceiverHome.kt"
(ui / "XStageReceiverHome.kt").write_text(
    minimal_home.read_text(encoding="utf-8"), encoding="utf-8")
screen = overview.read_text(encoding="utf-8")
video_back = '        BackHandler { viewModel.stopVideoPlayback() }\n'
if screen.count(video_back) != 1:
    raise RuntimeError("Expected one upstream video-back handler")
# Keep Video Back local to video playback rather than closing the TV receiver.
screen = screen.replace(
    'if (justStarted && !audioOnly && !videoPlaybackActive && autoFullscreen && pin == null)',
    'if (justStarted && !audioOnly && !videoPlaybackActive && pin == null)')
start = screen.index('    if (fullscreen) {\n        BackHandler { fullscreen = false }')
end = screen.index('\n    // pin dialog', start)
screen = screen[:start] + '''    if (fullscreen) {
        FullscreenVideo(
            viewModel = viewModel,
            video = video,
            onExitFullscreen = { fullscreen = false },
            onPip = onPip
        )
    } else if (tab == Tab.OVERVIEW) {
        XStageReceiverHome(
            viewModel = viewModel,
            video = video,
            onSettings = { tab = Tab.SETTINGS },
            onLocalNetwork = onLocalNetwork
        )
    } else {
        Column(modifier = Modifier.fillMaxSize()) {
            TextButton(
                onClick = { tab = Tab.OVERVIEW },
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp)
                    .dpadFocus()
            ) {
                Icon(Icons.Default.ArrowBack, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text("กลับหน้าหลัก")
            }
            Box(modifier = Modifier.weight(1f)) {
                SettingsScreen(viewModel)
            }
        }
    }
''' + screen[end:]
# Remove the unreachable upstream overview and its start/stop button.
start = screen.index('\n@Composable\nprivate fun TabContent(')
end = screen.index('\n@Composable\nprivate fun FullscreenVideo(', start)
screen = screen[:start] + screen[end:]
# During screen mirroring, picture only: no PiP/close overlays over the video.
start = screen.index('@Composable\nprivate fun FullscreenVideo(')
end = screen.index('\n// dacp scanning', start)
screen = screen[:start] + '''@Composable
private fun FullscreenVideo(
    viewModel: MainViewModel,
    video: @Composable () -> Unit,
    onExitFullscreen: () -> Unit,
    onPip: () -> Unit
) {
    Box(
        modifier = Modifier.fillMaxSize().background(Color.Black),
        contentAlignment = Alignment.Center
    ) {
        video()
    }
}
''' + screen[end:]
# Subpages consume the remote Back key before the Activity exit handler.
subpage_marker = '    val videoScreen = videoPlaybackActive || videoSessionPending\n'
if screen.count(subpage_marker) != 1:
    raise RuntimeError("Expected one MainScreen video state marker")
screen = screen.replace(subpage_marker, subpage_marker +
    '    BackHandler(enabled = tab != Tab.OVERVIEW && !videoScreen) { tab = Tab.OVERVIEW }\n')
if 'viewModel::startServer' in screen or 'viewModel::stopServer' in screen:
    raise RuntimeError("Unexpected manual receiver control remains in primary UI")
overview.write_text(screen, encoding="utf-8")

# Material3's dimmed labels and weak outline are difficult to read across TVs.
theme_file = ui / "theme" / "Theme.kt"
substitute(theme_file, 'primary = Color(0xFFFF5A6E)', 'primary = Color(0xFF7AE7FF)')
substitute(theme_file, 'onPrimary = Color(0xFF2A0A10)', 'onPrimary = Color(0xFF082A3C)')
substitute(theme_file, 'onSurfaceVariant = Color(0xFFA9B8CF)',
           'onSurfaceVariant = Color(0xFFE1EAF8)')
substitute(theme_file, 'outline = Color(0xFF2A3B58)', 'outline = Color(0xFF91A7C7)')
substitute(theme_file, 'surfaceTint = Color(0xFFFF5A6E)', 'surfaceTint = Color(0xFF7AE7FF)')

# All preset chips should clearly distinguish selected/unselected states.
# Treat each horizontal choice row as a focus group for TV remote traversal.
settings_p = ui / "SettingsScreen.kt"
settings_text = settings_p.read_text(encoding="utf-8")
settings_text = settings_text.replace(
    'import androidx.compose.foundation.layout.*',
    'import androidx.compose.foundation.layout.*\nimport androidx.compose.foundation.focusGroup')
old_flow = 'FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {'
if settings_text.count(old_flow) != 2:
    raise RuntimeError("Expected two settings choice groups")
settings_text = settings_text.replace(
    old_flow,
    'FlowRow(modifier = Modifier.focusGroup(),\n'
    '            horizontalArrangement = Arrangement.spacedBy(8.dp)) {')
chip_colors = ('colors = FilterChipDefaults.filterChipColors(\n'
               '                            selectedContainerColor = MaterialTheme.colorScheme.secondary,\n'
               '                            selectedLabelColor = MaterialTheme.colorScheme.onSecondary,\n'
               '                            containerColor = MaterialTheme.colorScheme.surfaceContainerHigh,\n'
               '                            labelColor = MaterialTheme.colorScheme.onSurface),')
for pad, count in [('                        ', 3), ('                ', 1)]:
    target = pad + 'modifier = Modifier.dpadFocus()\n' + pad[:-4] + ')'
    if settings_text.count(target) != count:
        raise RuntimeError(f"Unexpected chip count for {pad!r}: {settings_text.count(target)}")
    settings_text = settings_text.replace(target,
        pad + 'modifier = Modifier.dpadFocus(),\n' + pad + chip_colors +
        '\n' + pad[:-4] + ')')
# In each setting's one-line choice row, DPAD LEFT/RIGHT must visit the
# immediate adjacent option, instead of choosing an unrelated control.
settings_text = settings_text.replace(
    'import androidx.compose.ui.focus.onFocusChanged',
    'import androidx.compose.ui.focus.FocusRequester\n'
    'import androidx.compose.ui.focus.focusProperties\n'
    'import androidx.compose.ui.focus.focusRequester\n'
    'import androidx.compose.ui.focus.onFocusChanged')
settings_text = settings_text.replace(
    '    FlowRow(modifier = Modifier.focusGroup(),\n'
    '            horizontalArrangement = Arrangement.spacedBy(8.dp)) {\n'
    '        options.forEach { (key, label) ->',
    '    val choiceFocus = remember(options) { List(options.size) { FocusRequester() } }\n'
    '    FlowRow(modifier = Modifier.focusGroup(),\n'
    '            horizontalArrangement = Arrangement.spacedBy(8.dp)) {\n'
    '        options.forEachIndexed { index, (key, label) ->')
settings_text = settings_text.replace(
    '                modifier = Modifier.dpadFocus(),\n'
    '                colors = FilterChipDefaults.filterChipColors(',
    '                modifier = Modifier.focusRequester(choiceFocus[index])\n'
    '                    .focusProperties {\n'
    '                        if (index > 0) left = choiceFocus[index - 1]\n'
    '                        if (index < choiceFocus.lastIndex) right = choiceFocus[index + 1]\n'
    '                    }.dpadFocus(),\n'
    '                colors = FilterChipDefaults.filterChipColors(')
if 'choiceFocus[index]' not in settings_text or 'forEachIndexed { index, (key, label)' not in settings_text:
    raise RuntimeError("TV choice focus chain was not installed")

settings_p.write_text(settings_text, encoding="utf-8")

overlay = Path(__file__).resolve().parent / "ReceiverSetupQr.kt"
(ui / "ReceiverSetupQr.kt").write_text(overlay.read_text(encoding="utf-8"), encoding="utf-8")

# Add a built-in HTTPS + SHA256 updater. Only a newer, verified APK is handed
# to Android's standard installer; Android decides whether user confirmation
# and unknown-source permission are required.
updater = Path(__file__).resolve().parent / "MirrorUpdateManager.kt"
pkg_dir = APP / "src/main/kotlin/app/airshow/tv"
for filename in ("ReceiverNamePolicy.kt", "TvHomeShortcut.kt"):
    (pkg_dir / filename).write_text(
        (Path(__file__).resolve().parent / filename).read_text(encoding="utf-8"),
        encoding="utf-8")
(ui / "ReceiverNameEditor.kt").write_text(
    (Path(__file__).resolve().parent / "ReceiverNameEditor.kt").read_text(encoding="utf-8"),
    encoding="utf-8")
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
           '        window.setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE)\n'
           '        // Preserve older custom receiver names as a suffix.\n'
           '        ReceiverNamePolicy.migratePreviousName(this)\n'
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

# One Back press always asks for confirmation, including during mirroring.
# Choosing "ปิด" stops the foreground receiver before finishing the Activity.
substitute(activity,
           'import androidx.activity.enableEdgeToEdge',
           'import androidx.activity.enableEdgeToEdge\n'
           'import androidx.activity.compose.BackHandler\n'
           'import androidx.compose.runtime.remember\n'
           'import androidx.compose.material3.AlertDialog\n'
           'import androidx.compose.material3.Text\n'
           'import androidx.compose.material3.TextButton')
substitute(activity,
           '        setContent {\n            AirShowTheme {',
           '        setContent {\n'
           '            val confirmExit = remember { mutableStateOf(false) }\n'
           '            BackHandler(enabled = !confirmExit.value) { confirmExit.value = true }\n'
           '            AirShowTheme {')
substitute(activity,
           '                    onLocalNetwork = ::_requestLocalNetwork\n'
           '                )\n            }\n        }',
           '                    onLocalNetwork = ::_requestLocalNetwork\n'
           '                )\n'
           '                if (confirmExit.value) {\n'
           '                    AlertDialog(\n'
           '                        onDismissRequest = { confirmExit.value = false },\n'
           '                        title = { Text("ปิด X-Stage Mirror TV?") },\n'
           '                        text = { Text("การรับภาพและการเชื่อมต่อจะหยุดลง") },\n'
           '                        confirmButton = {\n'
           '                            TextButton(onClick = {\n'
           '                                confirmExit.value = false\n'
           '                                viewModel.stopServer()\n'
           '                                finish()\n'
           '                            }) { Text("ปิด") }\n'
           '                        },\n'
           '                        dismissButton = {\n'
           '                            TextButton(onClick = { confirmExit.value = false }) {\n'
           '                                Text("ไม่ปิด")\n'
           '                            }\n'
           '                        }\n'
           '                    )\n'
           '                }\n'
           '            }\n        }')
# Do not allow a hidden old user preference to disable reception on launch.
substitute(activity,
           'if (viewModel.pref(Prefs.AUTO_START).value && svc.serverState.value == AirPlayService.ServerState.STOPPED && hasLocalNetwork())',
           'if (svc.serverState.value == AirPlayService.ServerState.STOPPED && hasLocalNetwork())')

settings = ui / "SettingsScreen.kt"
substitute(settings,
           '    val serverName by viewModel.pref(Prefs.SERVER_NAME).collectAsState()',
           '    val activeConnections by viewModel.connectionCount.collectAsState()')
substitute(settings,
           '        SettingTextField(\n'
           '            label = stringResource(R.string.setting_server_name),\n'
           '            value = serverName,\n'
           '            onCommit = { viewModel.set(Prefs.SERVER_NAME, it) }\n'
           '        )',
           '        ReceiverNameEditor(viewModel, canEdit = activeConnections == 0)')
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

# Automatic startup and fullscreen reception are fixed product behavior,
# not user-facing toggles that could contradict what the receiver actually does.
substitute(settings,
           '        SettingSwitch(\n'
           '            title = stringResource(R.string.setting_auto_fullscreen),\n'
           '            description = stringResource(R.string.setting_auto_fullscreen_desc),\n'
           '            checked = autoFullscreen,\n'
           '            onCheckedChange = { viewModel.set(Prefs.AUTO_FULLSCREEN, it) }\n'
           '        )',
           '')
substitute(settings,
           '            SettingSwitch(\n'
           '                title = stringResource(R.string.setting_auto_start),\n'
           '                description = stringResource(R.string.setting_auto_start_desc),\n'
           '                checked = autoStart,\n'
           '                onCheckedChange = { viewModel.set(Prefs.AUTO_START, it) }\n'
           '            )',
           '')

# Apply bounded decoder/discovery performance patches to the pinned source.
subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "performance_tuning.py"),
                str(ROOT)], check=True)

# Automatically select a hardware-supported quality level and safely learn from
# sustained decode overload. Do not restart while iPhone is connected.
subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "auto_quality_tuning.py"),
                str(ROOT)], check=True)

# Correct stalled AirPlay VOD/HLS independently of real-time screen mirroring.
subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "video_playback_recovery.py"),
                str(ROOT)], check=True)
# Preserve original attribution and build a distinctive launcher/TV banner.
font_paths = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
]
font_path = next((p for p in font_paths if Path(p).exists()), None)

def font(size):
    return ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()

def mark(size):
    """Distinct X-Stage Mirror TV cast icon, not the Karaoke X/microphone mark."""
    scale = size / 512.0
    im = Image.new("RGBA", (size, size), (10, 27, 63, 255))
    d = ImageDraw.Draw(im)
    def box(x1, y1, x2, y2):
        return tuple(round(v * scale) for v in (x1, y1, x2, y2))
    def w(px):
        return max(2, round(px * scale))
    def line(points, fill, width):
        d.line([(round(x * scale), round(y * scale)) for x,y in points],
               fill=fill, width=w(width), joint="curve")
    d.rounded_rectangle(box(7,7,505,505),radius=round(108*scale),
                        fill=(11,37,76,255),outline=(72,214,244,255),width=w(8))
    d.ellipse(box(166,98,495,427),fill=(20,97,157,255))
    d.rounded_rectangle(box(113,177,415,363),radius=round(22*scale),
                        fill=(21,71,132,255),outline=(166,240,255,255),width=w(10))
    d.rounded_rectangle(box(126,192,401,343),radius=round(13*scale),
                        fill=(26,136,166,255))
    line([(224,380),(306,380)],(219,250,255,255),10)
    line([(265,364),(265,382)],(219,250,255,255),10)
    d.rounded_rectangle(box(71,242,171,417),radius=round(21*scale),
                        fill=(10,34,87,255),outline=(224,245,255,255),width=w(9))
    line([(107,397),(138,397)],(131,214,253,255),5)
    # Fan-out from the sending iPhone to the TV is the identifying shape.
    for b in (box(235,270,339,369),box(248,284,327,359),box(263,303,311,348)):
        d.arc(b,205,330,fill=(166,255,250,255),width=w(9))
    d.ellipse(box(282,319,296,333),fill=(229,255,255,255))
    for b in (box(89,273,152,337),box(105,287,151,336),box(118,299,152,335)):
        d.arc(b,270,360,fill=(126,242,255,255),width=w(7))
    # Mini X-Stage family mark and product stripe.
    line([(63,57),(121,118)],(74,230,255,255),14)
    line([(121,57),(63,118)],(199,116,252,255),14)
    d.text((round(256*scale),round(461*scale)),"MIRROR TV",
           font=font(max(9,round(30*scale))),fill=(241,252,255),
           anchor="mm")
    return im


def banner(size):
    w,h = size
    # TV Launcher banner: solid white 16:9 background; preserve a distinctive
    # dark casting emblem and readable navy/cyan text on both low/high density.
    im = Image.new("RGB", size, (255,255,255))
    d = ImageDraw.Draw(im)
    icon = mark(int(h*0.56)).convert("RGB")
    im.paste(icon, (int(w*0.045), int(h*0.22)))
    tx = int(w*0.36)
    # Product name is dominant, with X-STAGE as a smaller parent brand.
    d.text((tx,int(h*0.32)), "X-STAGE", fill=(75,98,128), font=font(int(h*0.095)))
    d.text((tx,int(h*0.55)), "MIRROR TV", fill=(5,99,143), font=font(int(h*0.17)))
    d.text((tx,int(h*0.72)), "AirPlay receiver", fill=(78,96,123), font=font(int(h*0.068)))
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
