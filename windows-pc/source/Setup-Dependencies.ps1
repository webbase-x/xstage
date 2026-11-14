param([string]$TargetDirectory = $PSScriptRoot)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'tools\Dependency-Common.ps1')
Assert-XStagePlatform
# Install only missing system runtime. Its signed installer owns the UAC prompt.
$runtime=Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64' -ErrorAction SilentlyContinue
$runtimeVersion=[version]'0.0'
if ($runtime -and $runtime.Version) { try { $runtimeVersion=[version]($runtime.Version -replace '^v','') } catch { } }
if (-not $runtime -or $runtimeVersion -lt [version]'14.34' -or $runtime.Installed -ne 1 -or -not (Test-Path -LiteralPath (Join-Path $env:WINDIR 'System32\vcruntime140.dll'))) {
    $installer=Get-XStageDownload 'https://aka.ms/vc14/vc_redist.x64.exe' 'vc_redist.x64.exe' (Join-Path $PSScriptRoot 'offline') { param($file) Assert-XStagePublisher $file 'Microsoft Corporation' }
    Assert-XStagePublisher $installer 'Microsoft Corporation'
    $process=Start-Process -FilePath $installer -ArgumentList '/install /passive /norestart' -Verb RunAs -Wait -PassThru
    if ($process.ExitCode -notin @(0,1638,3010)) { throw ('Visual C++ runtime install failed/cancelled: '+$process.ExitCode) }
    if ($process.ExitCode -eq 3010) { Write-Warning 'Windows requires a restart to finish runtime setup. Do not restart during playback.' }
}
& (Join-Path $PSScriptRoot 'Setup-Audio.ps1') -TargetDirectory (Join-Path $TargetDirectory 'native\x64')
if (Test-Path -LiteralPath (Join-Path $TargetDirectory 'XStageKaraoke.exe')) {
    $report=Join-Path $TargetDirectory 'dependency-report.json'
    $process=Start-Process -FilePath (Join-Path $TargetDirectory 'XStageKaraoke.exe') -ArgumentList @('--check-dependencies','--dependency-report',('"'+$report+'"')) -Wait -PassThru
    if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $report)) { throw ('Packaged runtime check failed. See '+$report) }
    Write-Host ('Dependency check passed: '+$report)
}
