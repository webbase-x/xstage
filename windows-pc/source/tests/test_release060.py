import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools.verify_release import check_source, make_manifest, verify_manifest
import json

class ReleaseTests(unittest.TestCase):
    def test_source_exe_version_match_and_mismatch(self):
        root=Path(__file__).resolve().parents[1]
        from karaoke import __version__
        self.assertEqual(check_source(root),__version__)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'karaoke').mkdir()
            (p/'karaoke/__init__.py').write_text('__version__="0.6.0"')
            (p/'version_info.txt').write_text((root/'version_info.txt').read_text().replace('prodvers=(0,6,0,0)','prodvers=(0,5,87,0)'))
            with self.assertRaises(ValueError):check_source(p)
    def test_manifest_detects_missing_and_modified_files(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);file=p/'XStageKaraoke.exe';file.write_bytes(b'test-fixture')
            manifest=make_manifest(p,'0.6.0')
            (p/'release-manifest.json').write_text(json.dumps(manifest))
            self.assertEqual(verify_manifest(p)['version'],'0.6.0')
            file.write_bytes(b'changed')
            with self.assertRaises(ValueError):verify_manifest(p)
            file.unlink()
            with self.assertRaises(ValueError):verify_manifest(p)
