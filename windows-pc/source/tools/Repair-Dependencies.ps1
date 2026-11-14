param([int]$WaitPid,[string]$AppDirectory,[string]$DataDirectory,[string]$PythonExe='')
$ErrorActionPreference='Stop'
$logRoot=Join-Path $env:LOCALAPPDATA 'XStageKaraoke\Logs'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$log=Join-Path $logRoot ('repair-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'.log')
Start-Transcript -Path $log | Out-Null
$script:stage='Preparing';$script:step=1
function Set-RepairStage([int]$Number,[string]$Name,[string]$Status='running',[string]$Failure='') {
    $script:stage=$Name;$script:step=$Number
    Write-Host ("[{0}/5] {1}" -f $Number,$Name) -ForegroundColor Cyan
    Write-Progress -Activity 'X-Stage component repair' -Status $Name -PercentComplete (($Number-1)*20)
    $record=@{step=$Number;stage=$Name;status=$Status;error=$Failure;log=$log;time=(Get-Date).ToString('o')}
    New-Item -ItemType Directory -Path $DataDirectory -Force | Out-Null
    $destination=Join-Path $DataDirectory 'repair-status.json'
    [IO.File]::WriteAllText(($destination+'.tmp'),($record | ConvertTo-Json),(New-Object Text.UTF8Encoding($false)))
    Move-Item -LiteralPath ($destination+'.tmp') -Destination $destination -Force
}
try {
    Set-RepairStage 1 'Waiting for player to close'
    if ($WaitPid -le 0) { throw 'A running application PID is required.' }
    $running=Get-Process -Id $WaitPid -ErrorAction SilentlyContinue
    if ($running -and -not $running.WaitForExit(120000)) { throw 'Application is still running. No files were changed.' }
    Set-RepairStage 2 'Checking/downloading native libraries and Visual C++ runtime'
    & (Join-Path $AppDirectory 'Setup-Dependencies.ps1') -TargetDirectory $AppDirectory
    Set-RepairStage 3 'Checking application components'
    if ($PythonExe) {
        & $PythonExe -m pip install --only-binary=:all: --find-links (Join-Path $AppDirectory 'offline\wheels') -r (Join-Path $AppDirectory 'requirements.txt')
        if ($LASTEXITCODE -ne 0) { throw 'Python component repair failed.' }
        Set-RepairStage 4 'Validating runtime'
        & $PythonExe (Join-Path $AppDirectory 'tools\check_dependencies.py') --home $AppDirectory --report (Join-Path $DataDirectory 'dependency-report.json')
        if ($LASTEXITCODE -ne 0) { throw 'Runtime check failed. See dependency-report.json.' }
        Set-RepairStage 5 'Components ready; launching player' 'completed'
        Start-Process -FilePath $PythonExe -WorkingDirectory $AppDirectory -ArgumentList @(('"'+(Join-Path $AppDirectory 'main.py')+'"'),'--data-dir',('"'+$DataDirectory+'"'))
    } else {
        Set-RepairStage 4 'Packaged runtime validated by setup'
        Set-RepairStage 5 'Components ready; launching player' 'completed'
        Start-Process -FilePath (Join-Path $AppDirectory 'XStageKaraoke.exe') -WorkingDirectory $AppDirectory -ArgumentList @('--data-dir',('"'+$DataDirectory+'"'))
    }
} catch {
    $failure=$_.Exception.Message
    try { Set-RepairStage $script:step $script:stage 'failed' $failure } catch { Write-Warning 'Could not save repair status.' }
    Write-Host $failure -ForegroundColor Red
    Write-Host ('Repair was not completed. Log: '+$log)
    Read-Host 'Press Enter to close';exit 1
} finally { Write-Progress -Activity 'X-Stage component repair' -Completed; Stop-Transcript | Out-Null }
