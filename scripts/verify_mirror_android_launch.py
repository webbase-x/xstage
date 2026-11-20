#!/usr/bin/env python3
"""Guard against the File Explorer launch regression on Windows receivers."""
from pathlib import Path
f = Path("mirror-android-pc/MainForm.cs").read_text(encoding="utf-8")
launcher = Path("mirror-android-pc/MiracastAppLauncher.cs").read_text(encoding="utf-8")
assert 'ProcessStartInfo("explorer.exe"' not in f
assert 'shell:AppsFolder' not in f
assert 'MiracastAppLauncher.TryStart(out var error)' in f
assert 'IApplicationActivationManager' in launcher
assert 'ActivateApplication(appId' in launcher
assert 'Microsoft.WirelessDisplay.Connect_cw5n1h2txyewy!App' in launcher
assert 'Microsoft.PPIProjection_cw5n1h2txyewy!Microsoft.PPIProjection' in launcher
assert 'Process.Start(new ProcessStartInfo("explorer.exe"' not in launcher
print("Miracast launch regression: pass (no Explorer fallback)")
