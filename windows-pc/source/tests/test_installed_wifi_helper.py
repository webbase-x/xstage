"""Check the installer manifests against the frozen application's lookup."""
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from karaoke.wifi_permission import repair_script

ROOT = Path(__file__).resolve().parent.parent


def names(text, variable):
    body = re.search(r'\$' + variable + r'\s*=\s*@\(([^)]*)\)', text)
    if body is None:
        raise AssertionError('Missing manifest: ' + variable)
    return re.findall(r"'([^']+)'", body.group(1))


class InstalledWifiHelperTests(unittest.TestCase):
    def test_build_and_install_manifests_deliver_helper_beside_exe(self):
        build = (ROOT / 'build.ps1').read_text(encoding='utf-8-sig')
        installer = (ROOT / 'install_to_D.ps1').read_text(encoding='utf-8-sig')
        # Model both copy stages, not just presence in the source ZIP.
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve() / "ไพรัช  อินควรชุม" / "teacher's folder"
            release, app = folder / 'release', folder / 'installed' / 'App'
            release.mkdir(parents=True)
            app.mkdir(parents=True)
            for manifest, source, destination in [
                (names(build, 'names'), ROOT, release),
                (names(installer, 'appNames'), release, app),
            ]:
                for name in manifest:
                    if name == 'tools':
                        shutil.copytree(source / name, destination / name)
            with patch('karaoke.wifi_permission.sys.frozen', True, create=True), patch(
                'karaoke.wifi_permission.sys.executable', str(app / 'XStageKaraoke.exe')
            ):
                resolved = repair_script()
                self.assertEqual(resolved, app / 'tools' / 'Repair-XStage-WiFi.ps1')
                self.assertEqual(resolved.read_bytes(), (ROOT / 'tools' / resolved.name).read_bytes())

    def test_missing_helper_is_required_before_installer_copies(self):
        text = (ROOT / 'install_to_D.ps1').read_text(encoding='utf-8-sig')
        required = re.search(r"foreach \(\$required in @\(([^)]*)\)\)", text)
        self.assertIsNotNone(required)
        self.assertIn('tools\\Repair-XStage-WiFi.ps1', required.group(1))
        self.assertLess(required.start(), text.index('foreach ($entry in $updatePlan)'))

    def test_build_verifies_helper_before_reporting_success(self):
        text = (ROOT / 'build.ps1').read_text(encoding='utf-8-sig')
        self.assertLess(text.index("Join-Path $ready 'tools\\Repair-XStage-WiFi.ps1'"),
                        text.index("Write-Host ('Built:"))


if __name__ == '__main__':
    unittest.main()
