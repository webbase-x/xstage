"""Build in an owned temporary directory; return ZIP bytes to the orchestrator."""
import base64
import importlib.metadata
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import re
import zipfile


def run(command, directory, timeout=120):
    result=subprocess.run(command,cwd=directory,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
    if result.returncode:
        raise RuntimeError('Command failed: '+repr(command[:4])+'\n'+result.stdout[-3000:]+'\n'+result.stderr[-6000:])
    return result


def build(project):
    project=Path(project).resolve()
    version=re.search(r'__version__\s*=\s*"([^"]+)"',(project/'karaoke'/'__init__.py').read_text(encoding='utf-8')).group(1)
    with tempfile.TemporaryDirectory(prefix='newKaraoke-release-') as temporary:
        root=Path(temporary).resolve()
        assert root.parent==Path(tempfile.gettempdir()).resolve()
        source=root/'Source'
        shutil.copytree(project,source,ignore=shutil.ignore_patterns('__pycache__','*.pyc','dist','build','data','google-oauth-client.json','*.zip','XStageKaraoke.exe','_internal'))
        os.environ['PYINSTALLER_CONFIG_DIR']=str(root/'pyinstaller-cache')
        os.environ['PYTHONDONTWRITEBYTECODE']='1'
        os.environ['PYTHONIOENCODING']='utf-8'
        unit=run([sys.executable,'-B','-m','unittest','discover','-s','tests','-v'],source)
        gui=run([sys.executable,'-B','tests/smoke_studio.py'],source)
        gui_result=json.loads(gui.stdout)
        workspace=json.loads(run([sys.executable,'-B','tests/smoke_workspace.py'],source).stdout)
        pillow=importlib.metadata.distribution('Pillow')
        for relative in pillow.files or []:
            if '.dist-info/licenses/' in str(relative).replace('\\','/'):
                item=Path(pillow.locate_file(relative))
                subpath=str(relative).replace('\\','/').split('/licenses/',1)[1]
                target=source/'third_party_licenses'/'Pillow'/subpath
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(item,target)
        run([sys.executable,'-B','-m','PyInstaller','--noconfirm','--clean','--windowed','--onedir','--collect-all','soundcard','--collect-all','imageio_ffmpeg','--hidden-import','_cffi_backend','--name','XStageKaraoke','--version-file','version_info.txt','--icon','assets/xstage.ico','--add-data','assets;assets','main.py'],source,timeout=300)
        ready=source/'dist'/'XStageKaraoke'
        names=['karaoke','tools','tests','samples','assets','web','native','third_party_licenses','main.py','build.ps1','Build-Windows.cmd','RELEASE_0914_TH.md','RELEASE_0913_TH.md','RELEASE_0912_TH.md','SOUNDFONT_GUIDE_TH.md','UI_GUIDE_TH.md','IMPORT_GUIDE_TH.md','version_info.txt','README_TH.md','CHANGELOG.md','FEATURE_STATUS.md','LEGACY_TEST_RESULTS.json','SEARCH_BENCHMARK.json','THIRD_PARTY.md','LICENSE.txt','Setup-Audio.ps1','Install-to-D.cmd','install_to_D.ps1','start.bat','requirements.txt']
        names=['RELEASE_0925_TH.md','google-oauth-client.json.example','RELEASE_0917_TH.md','RELEASE_0916_TH.md','RELEASE_0915_TH.md']+names
        for name in names:
            item=source/name
            if item.is_dir():
                shutil.copytree(item,ready/name,dirs_exist_ok=True)
            elif item.is_file():
                shutil.copy2(item,ready/name)
        check=root/'PackagedTest'
        run([str(ready/'XStageKaraoke.exe'),'--self-test','--data-dir',str(check)],ready,timeout=45)
        packaged=json.loads((check/'self-test.json').read_text(encoding='utf-8'))
        assert packaged['ok'],packaged
        assert packaged['app_name']=='X-Stage Karaoke'
        assert packaged['version']==version
        exe_path=str(ready/'XStageKaraoke.exe').replace("'","''")
        properties=json.loads(run(['powershell','-NoProfile','-Command',
            "(Get-Item -LiteralPath '"+exe_path+"').VersionInfo | Select-Object ProductName,FileDescription,FileVersion | ConvertTo-Json -Compress"],ready).stdout)
        assert properties['ProductName']=='X-Stage Karaoke',properties
        assert properties['FileDescription']=='X-Stage Karaoke',properties
        installed=root/'Installed'
        (installed/'Data').mkdir(parents=True)
        sentinel=installed/'Data'/'keep-this.json'
        sentinel.write_text('{"preserve":true}')
        install=run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ready/'install_to_D.ps1'),'-Destination',str(installed)],ready)
        assert sentinel.read_text()=='{"preserve":true}'
        assert (installed/'App'/'XStageKaraoke.exe').is_file()
        assert (installed/'Source'/'main.py').is_file()
        assert (installed/'Start-Karaoke.cmd').is_file()
        assert (installed/'X-Stage Karaoke.cmd').is_file()
        installer_live=json.loads(run([sys.executable,'-B','tools/verify_installer.py',str(ready)],source,timeout=150).stdout)
        legacy=json.loads((source/'LEGACY_TEST_RESULTS.json').read_text(encoding='utf-8')) if (source/'LEGACY_TEST_RESULTS.json').is_file() else {}
        test_count=re.search(r'Ran (\d+) tests?',unit.stderr).group(1)
        report={'app_name':'X-Stage Karaoke','version':version,'executable_properties':properties,'unit_tests':test_count+' passed','source_gui':gui_result,'workspace_gui':workspace,'packaged_self_test':packaged,
            'installer_test':'passed in temporary destination; preserved existing Data sentinel',
            'installer_revision':2, 'installer_live_test':installer_live,
            'actual_D_install':'blocked by workspace access permissions',
            'remote_live_test':'blocked by socket access WinError 10013; HTTP protocol tests passed in memory',
            'bass_runtime':'not tested: official DLL download DNS unavailable',
            'microphone_capture':'not performed; input device enumeration and dialog tested',
            'pillow_version':pillow.version,'python':sys.version.split()[0],
            'search_benchmark':json.loads((source/'SEARCH_BENCHMARK.json').read_text(encoding='utf-8')) if (source/'SEARCH_BENCHMARK.json').is_file() else {},
            'catalog_rows':legacy.get('count'),'ncn_midi_read':legacy.get('ncn_midi_read'),
            'ncn_lyric_read':len(legacy.get('samples',[])),'emk_midi_read':legacy.get('emk_midi_read'),
            'emk_lyric_read':legacy.get('emk_lyrics_read'),'search_samples':legacy.get('search')}
        text='# ผลทดสอบ X-Stage Karaoke '+version+'\n\n'+json.dumps(report,ensure_ascii=False,indent=2)+'\n\nการอ่านตัวอย่างไม่ใช่การรับรองเพลงทุกไฟล์หรือความตรงเนื้อร้องจากการฟังเทียบ\n'
        (ready/'TEST_RESULTS.md').write_text(text,encoding='utf-8')
        (ready/'RELEASE_TEST_RESULTS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for file in sorted(ready.rglob('*')):
                if file.is_file() and '__pycache__' not in file.parts:
                    archive.write(file,file.relative_to(ready).as_posix())
        data=output.getvalue()
        return {'report':report,'test_results_md':text,'zip_size':len(data),'zip_base64':base64.b64encode(data).decode('ascii')}

if __name__=='__main__':
    print(json.dumps(build(sys.argv[1]),ensure_ascii=True))
