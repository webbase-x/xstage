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
assert values["app_name"] == "X-Stage Mirror TV"
assert any(x.attrib.get("{http://schemas.android.com/apk/res/android}name") == "android.intent.category.LEANBACK_LAUNCHER" for x in manifest.iter("category"))
assert (root / "LICENSE").exists()
assert (root / "NOTICE").exists()
print("PASS: unique package, TV launcher, discoverability, PIN-free defaults, rename and QR guide")
