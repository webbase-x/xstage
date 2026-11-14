param([string]$PythonExe = 'python')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& $PythonExe -c "import os,struct; assert os.name == 'nt' and struct.calcsize('P') == 8, 'Windows x64 Python required'"
if ($LASTEXITCODE -ne 0) { throw 'Use Windows with Python x64.' }
& $PythonExe (Join-Path $PSScriptRoot 'tools\verify_release.py') --home $PSScriptRoot
if ($LASTEXITCODE -ne 0) { throw 'Release metadata/environment gate failed.' }
& (Join-Path $PSScriptRoot 'Setup-Dependencies.ps1')
& $PythonExe (Join-Path $PSScriptRoot 'tools\check_dependencies.py') --home $PSScriptRoot
if ($LASTEXITCODE -ne 0) { throw 'Runtime check failed: dependency-report.json' }
& $PythonExe (Join-Path $PSScriptRoot 'tools\run_build_tests.py')
if ($LASTEXITCODE -ne 0) {
    $summaryFile=Join-Path $PSScriptRoot 'build-tests-summary.json'
    if (Test-Path -LiteralPath $summaryFile) {
        try {
            $summary=Get-Content -LiteralPath $summaryFile -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($failure in @($summary.failures)+@($summary.errors)) {
                if ($failure -and $failure.test) { Write-Host ('FAILED TEST: '+$failure.test) -ForegroundColor Red }
            }
        } catch { Write-Warning 'Could not parse test summary; inspect build-tests.log.' }
    }
    throw ('Tests failed; no executable was built. Full report: ' + (Join-Path $PSScriptRoot 'build-tests.log') + '; summary: ' + $summaryFile)
}
& $PythonExe -m PyInstaller --noconfirm --clean --windowed --onedir --collect-all soundcard --collect-all qrcode --collect-all imageio_ffmpeg --hidden-import _cffi_backend --name XStageKaraoke --version-file version_info.txt --icon assets/xstage.ico --add-data "assets;assets" main.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed. Install it using: python -m pip install pyinstaller' }
$ready = Join-Path $PSScriptRoot 'dist\XStageKaraoke'
$names = @('RELEASE_0913_TH.md','RELEASE_0912_TH.md','RELEASE_0911_TH.md','RELEASE_0910_TH.md','RELEASE_099_TH.md','RELEASE_098_TH.md','RELEASE_097_TH.md','RELEASE_096_TH.md','RELEASE_095_TH.md','RELEASE_094_TH.md','RELEASE_093_TH.md','RELEASE_092_TH.md','RELEASE_091_TH.md','RELEASE_090_TH.md','QUALITY_AND_CLEANUP_TH.md','RELEASE_082_TH.md','RELEASE_081_TH.md','RELEASE_080_TH.md','RELEASE_073_TH.md','RELEASE_072_TH.md','RELEASE_071_TH.md','RELEASE_070_TH.md','RELEASE_061_TH.md','requirements-build.lock.txt','release-environment.json','RELEASE_060_TH.md','Setup-Dependencies.ps1','DEPENDENCIES_TH.md','offline','SETUP_0570_TH.md','EQ_0570_TH.md','EQ_0571_TH.md','EQ_0572_TH.md','EQ_0573_TH.md','EQ_0574_TH.md','EQ_0575_TH.md','VERIFY_0576_TH.md','EQ_0578_TH.md','SONG_WORKSPACE_0579_TH.md','SOUNDFONT_0580_TH.md','SOUNDFONT_0581_TH.md','RUNTIME_LOGS_0583_TH.md','karaoke','tools','tests','samples','assets','third_party_licenses','native','main.py','build.ps1','Build-Windows.cmd','Build-Source.ps1','version_info.txt','README_TH.md','SOUNDFONT_GUIDE_TH.md','UI_GUIDE_TH.md','IMPORT_GUIDE_TH.md','DUPLICATE_GUIDE_TH.md','PROGRESS_GUIDE_TH.md','INDEXER_GUIDE_TH.md','AUDIO_FIX_TH.md','AUTO_AUDIO_TH.md','AUDIO_BENCHMARK_TH.md','AUDIO_TOOLS_TH.md','PERFORMANCE_GUIDE_TH.md','WINDOWS_CHECK_TH.md','BUILD_FIX_TH.md','CHANGELOG.md','FEATURE_STATUS.md','THIRD_PARTY.md','LICENSE.txt','SYSTEM_EQ_TH.md','Setup-Audio.ps1','Install-to-D.cmd','install_to_D.ps1','start.bat','Start-XStage-Silent.vbs','requirements.txt')
$names = @('RELEASE_0939_TH.md','QA_RESULTS_0939_TH.md','WINDOWS_BUILD_0939_TH.md','BENCHMARK_0939.json','Verify-Windows-0939.cmd') + $names
$names = @('RELEASE_0937_TH.md','QA_RESULTS_0937_TH.md','AUDIT_ALL_FUNCTIONS_0937_TH.md','WINDOWS_BUILD_0937_TH.md','RELEASE_0933_TH.md','RELEASE_0932_TH.md','RELEASE_0931_TH.md','RELEASE_0926_TH.md','RELEASE_0925_TH.md','google-oauth-client.json.example','RELEASE_0917_TH.md','RELEASE_0916_TH.md','RELEASE_0915_TH.md','RELEASE_0914_TH.md','web') + $names
$names = @('ONLINE_RECOVERY_R2_TH.md','ตรวจรุ่นซิงค์ออนไลน์.cmd') + $names
$names = @('Verify-Windows-0943.cmd') + $names
$names = @('RELEASE_0942_TH.md','QA_RESULTS_0942_TH.md','WINDOWS_BUILD_0942_TH.md','Verify-Windows-0942.cmd') + $names
$names = @('Convert-Web-Assets.cmd','Verify-Windows-0945.cmd','Verify-Windows-0946.cmd','Verify-Windows-0947.cmd') + $names
foreach ($name in $names) {
    $item = Join-Path $PSScriptRoot $name
    if (Test-Path -LiteralPath $item) { Copy-Item -LiteralPath $item -Destination $ready -Recurse -Force }
}
$release092 = Join-Path $PSScriptRoot 'RELEASE_092_TH.md'
if (Test-Path -LiteralPath $release092) { Copy-Item -LiteralPath $release092 -Destination $ready -Force }
if (-not (Test-Path -LiteralPath (Join-Path $ready 'tools\Repair-XStage-WiFi.ps1') -PathType Leaf)) {
    throw 'Build incomplete: missing tools\Repair-XStage-WiFi.ps1.'
}
& (Join-Path $ready 'Setup-Dependencies.ps1') -TargetDirectory $ready
& $PythonExe (Join-Path $PSScriptRoot 'tools\verify_release.py') --home $PSScriptRoot --package $ready
if ($LASTEXITCODE -ne 0) { throw 'Release manifest failed.' }
Write-Host ('Built: ' + (Join-Path $ready 'XStageKaraoke.exe'))
Write-Host 'Test playback and SoundFont on this computer, then run dist\XStageKaraoke\Install-to-D.cmd.'
