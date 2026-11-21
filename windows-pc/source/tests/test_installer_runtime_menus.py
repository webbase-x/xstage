"""Packaging and menu-wiring regression checks for the installed Windows PC app.

These tests intentionally run without a display or live audio device. They
verify that the commands are implemented and that the installer ships resources
those commands need. They do not certify actual playback or peripherals.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import unittest

from karaoke.ui import KaraokeApp
from karaoke.classic import ClassicApp
from karaoke.performer import PlaybackApp

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
INSTALLER = REPO / "windows-pc" / "installer" / "XStageKaraoke.iss"

NATIVE = ("bass.dll", "bassmidi.dll", "bass_fx.dll")
ROOT_SCRIPTS = ("Setup-Dependencies.ps1", "Setup-Audio.ps1")
TOOL_SCRIPTS = (
    "Dependency-Common.ps1",
    "Probe-Native.ps1",
    "Repair-Dependencies.ps1",
    "Repair-XStage-WiFi.ps1",
    "Setup-System-EQ.ps1",
    "Open-APO-Device.ps1",
    "Install-EqualizerAPO.ps1",
    "Installer-Safety.ps1",
)


class RuntimeInstallerTests(unittest.TestCase):
    @unittest.skipUnless(INSTALLER.is_file(), "source ZIP has no Inno Setup project")
    def test_installer_includes_native_and_all_runtime_helpers(self):
        text = INSTALLER.read_text(encoding="utf-8-sig")
        # The path is resolved against the installed EXE, not PyInstaller _internal.
        self.assertIn(
            r'Source: "..\source\dist\XStageKaraoke\native\x64\*"; DestDir: "{app}\native\x64"',
            text)
        for name in ROOT_SCRIPTS:
            self.assertIn(
                'Source: "..\\source\\dist\\XStageKaraoke\\' + name +
                '"; DestDir: "{app}";', text, name)
        for name in TOOL_SCRIPTS:
            self.assertIn(
                'Source: "..\\source\\dist\\XStageKaraoke\\tools\\' + name +
                '"; DestDir: "{app}\\tools";', text, name)
        self.assertNotIn(r'DestDir: "{app}\Source"', text)
        self.assertNotIn(r'DestDir: "{app}\tests"', text)

    def test_build_copies_runtime_resources_before_packaging(self):
        build = (ROOT / "build.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("'native'", build)
        self.assertIn("'tools'", build)
        for name in ROOT_SCRIPTS:
            self.assertIn("'" + name + "'", build)
        for name in TOOL_SCRIPTS:
            self.assertTrue((ROOT / "tools" / name).is_file(), name)

    @unittest.skipUnless(INSTALLER.is_file(), "source ZIP has no Windows build workflow")
    def test_build_refuses_missing_audio_runtime(self):
        workflow = (REPO / ".github" / "workflows" / "build-windows-pc.yml").read_text(encoding="utf-8")
        self.assertIn("Verify bundled BASS runtime before packaging", workflow)
        for name in NATIVE:
            self.assertIn("'" + name + "'", workflow)
        self.assertIn("Not a valid Windows x64 DLL", workflow)

    def test_component_repair_requires_windows_consent_before_exit(self):
        source = (ROOT / "karaoke" / "dependency_ui.py").read_text(encoding="utf-8")
        self.assertIn("ShellExecuteW", source)
        self.assertIn("'runas'", source)
        # ShellExecuteW returns NULL or an error code <= 32 on failure.
        # Include the NULL check: on 64-bit Windows restype is c_void_p.
        self.assertRegex(source, r"if\\s+not\\s+result\\s+or\\s+result\\s*<=\\s*32\\s*:")
        self.assertIn("shell.restype=ctypes.c_void_p", source)
        self.assertLess(source.index("ShellExecuteW"), source.index("app.close_app()"))
        script = (ROOT / "tools" / "Repair-Dependencies.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("WindowsBuiltInRole]::Administrator", script)
        self.assertNotIn("Start-Process -FilePath (Join-Path $AppDirectory 'XStageKaraoke.exe')", script)
        self.assertIn("reopen the player normally", script)


class MenuWiringTests(unittest.TestCase):
    def test_direct_button_callbacks_are_real_app_methods(self):
        # A missing callback crashes UI construction even when only that menu
        # button is needed. Check the inherited class, not only local methods.
        for filename, app_class in (
            ("ui.py", KaraokeApp),
            ("classic.py", ClassicApp),
            ("performer.py", PlaybackApp),
        ):
            with self.subTest(file=filename):
                source = (ROOT / "karaoke" / filename).read_text(encoding="utf-8-sig")
                tree = ast.parse(source, filename=filename)
                found = 0
                for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
                    for kw in call.keywords:
                        item = kw.value
                        if kw.arg != "command":
                            continue
                        if (isinstance(item, ast.Attribute)
                                and isinstance(item.value, ast.Name)
                                and item.value.id == "self"):
                            found += 1
                            self.assertTrue(callable(getattr(app_class, item.attr, None)),
                                f"{filename}:{item.lineno} missing handler {item.attr}")
                self.assertGreater(found, 4, filename)

    def test_context_menu_callback_methods_exist(self):
        text = (ROOT / "karaoke" / "context_menu.py").read_text(encoding="utf-8")
        callbacks = set(re.findall(
            r"\bcommand\([^\n]*?\bapp\.([A-Za-z_]\w*)", text))
        callbacks.update(re.findall(
            r"\bcommand=app\.([A-Za-z_]\w*)", text))
        self.assertGreater(len(callbacks), 20)
        for method in sorted(callbacks):
            with self.subTest(method=method):
                self.assertTrue(callable(getattr(PlaybackApp, method, None)),
                                "Unimplemented menu handler: " + method)


if __name__ == "__main__":
    unittest.main()
