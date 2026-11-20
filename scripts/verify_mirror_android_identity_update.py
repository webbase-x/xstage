#!/usr/bin/env python3
"""Guard the Android PC hostname display and automatic updater."""
from pathlib import Path
main=Path("mirror-android-pc/MainForm.cs").read_text(encoding="utf-8")
updater=Path("mirror-android-pc/MirrorAutoUpdateManager.cs").read_text(encoding="utf-8")
store=Path("storefront.js").read_text(encoding="utf-8")
assert "MakeLabel(Environment.MachineName, 82" in main
assert 'Text = "X-Stage Mirror Android PC | " + Environment.MachineName' in main
assert "ReceiverIdentity" not in main
assert "No.XXXX" not in main
assert 'if (!_installingWindowsFeature) _ = _autoUpdates.CheckAsync();' in main
assert "Action<int?, long> onProgress" in updater
assert "_canUpgrade()" in updater
assert "ตรวจสอบ SHA-256 ผ่านแล้ว" in updater
android=store.split('"mirror-android-pc":{',1)[1].split('"mirror-pc":{',1)[0]
assert "No.XXXX" not in android
assert "ชื่อคอมพิวเตอร์ Windows" in android
print("Android PC actual hostname and auto-update checks passed")
