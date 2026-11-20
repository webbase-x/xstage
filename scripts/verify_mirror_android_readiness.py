#!/usr/bin/env python3
"""Static regression checks: readiness must require hardware and real receiver."""
from pathlib import Path
main=Path("mirror-android-pc/MainForm.cs").read_text("utf-8")
prep=Path("mirror-android-pc/WindowsPreparation.cs").read_text("utf-8")
launcher=Path("mirror-android-pc/MiracastAppLauncher.cs").read_text("utf-8")
assert "NativeMiracastWindow.TryFind" in main
assert "_connectProcessRunning && _wifiAvailable" in main
assert "PrepareWindowsFeatureAsync()" in main
assert "PollPreparation()" in main
assert "HasWirelessAdapter()" in prep
assert "if (!HasWirelessAdapter())" in prep
assert 'line.Trim().Equals("Installed"' in prep
assert 'ProcessStartInfo("explorer.exe"' not in main + launcher
assert 'ActivateApplication(appId' in launcher
print("Miracast receiver provisioning readiness: source checks passed")
