import json,struct,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from karaoke import dependency_check as d
from karaoke.bass import BassSynth

class DependencyTests(unittest.TestCase):
    def test_missing_libraries_are_all_reported(self):
        with tempfile.TemporaryDirectory() as root:
            r=d.inspect(root,importer=lambda name:object())
        self.assertFalse(r['ok'])
        failures={c['name'] for c in r['checks'] if not c['ok']}
        self.assertTrue({n+' PE' for n in d.NATIVE}<=failures)
    def test_import_failure_does_not_hide_other_checks(self):
        def load(name):
            if name=='soundcard':raise ImportError('missing SoundCard')
            return object()
        with tempfile.TemporaryDirectory() as root:r=d.inspect(root,importer=load)
        self.assertTrue(any(c['name']=='soundcard' and not c['ok'] for c in r['checks']))
        self.assertTrue(any(c['name']=='_cffi_backend' and c['ok'] for c in r['checks']))
    def test_report_is_machine_readable_on_failure(self):
        with tempfile.TemporaryDirectory() as root:
            report={'ok':False,'checks':[{'name':'bass.dll','ok':False}]}
            with patch.object(d,'inspect',return_value=report):self.assertEqual(d.run(root),1)
            self.assertEqual(json.loads((Path(root)/'dependency-report.json').read_text(encoding='utf-8')),report)
    def test_reject_wrong_architecture_and_truncated_pe(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'bass.dll'
            for content in [b'',b'MZ',b'MZ'+b'\0'*58+struct.pack('<I',64)+b'PE\0\0'+struct.pack('<H',0x14c)]:
                p.write_bytes(content)
                with self.assertRaises(OSError):BassSynth.validate_dll(p)
    def test_native_files_copied_to_source_and_app_manifests(self):
        from test_installed_wifi_helper import names
        root=Path(__file__).resolve().parents[1]
        installer=(root/'install_to_D.ps1').read_text(encoding='utf-8-sig')
        for group in ('sourceNames','appNames'):
            self.assertIn('native',names(installer,group));self.assertIn('Setup-Dependencies.ps1',names(installer,group))
        self.assertLess(installer.index('& (Join-Path $source \'Setup-Dependencies.ps1\')'),installer.index('$updatePlan ='))
        self.assertLess(installer.index('& (Join-Path $app \'Setup-Dependencies.ps1\')'),installer.index("Write-Host ('Installed:"))
