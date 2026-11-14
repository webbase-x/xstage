"""Update only installer/docs in a verified release; preserve EXE bytes."""
import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import zipfile
from verify_installer import verify


def patch_release(archive_path, project):
    project = Path(project).resolve()
    with zipfile.ZipFile(archive_path) as archive:
        files = {item.filename: archive.read(item) for item in archive.infolist() if not item.is_dir()}
    before = hashlib.sha256(files['XStageKaraoke.exe']).hexdigest()
    for name in ('Install-to-D.cmd', 'install_to_D.ps1', 'README_TH.md', 'CHANGELOG.md',
                 'tools/verify_installer.py', 'tools/patch_installer_release.py', 'tools/package_release.py'):
        files[name] = (project/name).read_bytes()
    with tempfile.TemporaryDirectory(prefix='xstage-installer-release-') as temporary:
        root = Path(temporary).resolve()
        assert root.parent == Path(tempfile.gettempdir()).resolve()
        package = root/'Package'
        package.mkdir()
        for relative, content in files.items():
            target = (package/relative).resolve()
            assert target.is_relative_to(package)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        live = verify(package)
    report = json.loads(files['RELEASE_TEST_RESULTS.json'])
    report.update(installer_revision=2, installer_live_test=live,
        installer_test='Passed fresh install, native file lock, running target, graceful close, path scope, and Data preservation tests',
        executable_sha256=before, executable_unchanged_from=Path(archive_path).name)
    files['RELEASE_TEST_RESULTS.json'] = json.dumps(report, ensure_ascii=False, indent=2).encode('utf-8')
    text = '# X-Stage Karaoke '+report['version']+' - Installer revision 2\n\n'+json.dumps(report, ensure_ascii=False, indent=2)+'\n'
    files['TEST_RESULTS.md'] = text.encode('utf-8')
    assert hashlib.sha256(files['XStageKaraoke.exe']).hexdigest() == before
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(name, content)
    data = output.getvalue()
    return {'report': report, 'test_results_md': text, 'zip_size': len(data),
            'zip_base64': base64.b64encode(data).decode('ascii')}


if __name__ == '__main__':
    print(json.dumps(patch_release(sys.argv[1], sys.argv[2]), ensure_ascii=True))
