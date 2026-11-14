[CmdletBinding()]
param([switch]$RestoreLatest, [switch]$NoPause, [string]$UserSid)
$ErrorActionPreference = 'Stop'
$exitCode = 0
if (-not $UserSid) { $UserSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value }
if ($UserSid -notmatch '^S-1-5-21-\d+-\d+-\d+-\d+$') { throw 'Unsupported user SID. Run this tool from your normal Windows user account.' }
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    try {
        $arguments = @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"' + $PSCommandPath + '"'),'-UserSid',$UserSid)
        if ($RestoreLatest) { $arguments += '-RestoreLatest' }
        if ($NoPause) { $arguments += '-NoPause' }
        $process = Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Verb RunAs -ArgumentList $arguments -Wait -PassThru
        exit $process.ExitCode
    } catch { Write-Host ('Administrator permission was not granted: ' + $_.Exception.Message); exit 1 }
}
$machine = 'Registry::HKEY_LOCAL_MACHINE'
$user = 'Registry::HKEY_USERS\' + $UserSid
if (-not (Test-Path -LiteralPath $user)) { throw 'The original user registry is not loaded. Sign in to that account and run again.' }
$policy = 'Software\Policies\Microsoft\Windows\LocationAndSensors'
$consent = 'Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\location'
# Only these exact registry values may be modified or restored.
$targets = @(
    @{ Path="$machine\$policy"; Name='DisableLocation'; Operation='Remove'; Kind='DWord'; Value=0 },
    @{ Path="$machine\$policy"; Name='DisableWindowsLocationProvider'; Operation='Remove'; Kind='DWord'; Value=0 },
    @{ Path="$user\$policy"; Name='DisableLocation'; Operation='Remove'; Kind='DWord'; Value=0 },
    @{ Path="$user\$policy"; Name='DisableWindowsLocationProvider'; Operation='Remove'; Kind='DWord'; Value=0 },
    @{ Path="$machine\Software\Policies\Microsoft\Windows\AppPrivacy"; Name='LetAppsAccessLocation'; Operation='Remove'; Kind='DWord'; Value=0 },
    @{ Path="$machine\$consent"; Name='Value'; Operation='Set'; Kind='String'; Value='Allow' },
    @{ Path="$user\$consent"; Name='Value'; Operation='Set'; Kind='String'; Value='Allow' },
    @{ Path="$user\$consent\NonPackaged"; Name='Value'; Operation='Set'; Kind='String'; Value='Allow' },
    @{ Path="$machine\SYSTEM\CurrentControlSet\Services\lfsvc\Service\Configuration"; Name='Status'; Operation='Set'; Kind='DWord'; Value=1 }
)
$backupRoot = Join-Path $env:ProgramData ('XStage-WiFi-Repair\' + $UserSid)
New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
$logPath = Join-Path $backupRoot ('run-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8) + '.log')
Start-Transcript -Path $logPath -Force | Out-Null
function Read-Value($path,$name) {
    $exists = $false; $data = $null; $kind = $null
    if (Test-Path -LiteralPath $path) {
        $key = Get-Item -LiteralPath $path
        try {
            $exists = $key.GetValueNames() -contains $name
            if ($exists) {
                $kind = $key.GetValueKind($name).ToString()
                $data = $key.GetValue($name,$null,[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
            }
        } finally { $key.Close() }
    }
    [pscustomobject]@{ Path=$path; Name=$name; Exists=$exists; Kind=$kind; Data=$data }
}
function Write-Value($path,$name,$kind,$value) {
    if (-not (Test-Path -LiteralPath $path)) { New-Item -Path $path -Force | Out-Null }
    New-ItemProperty -LiteralPath $path -Name $name -PropertyType $kind -Value $value -Force | Out-Null
}
function Restore-State($state) {
    if ($state.Schema -ne 1 -or $state.UserSid -ne $UserSid -or @($state.Values).Count -ne $targets.Count) { throw 'Backup does not match this user or repair version.' }
    $seen = @{}
    foreach ($entry in $state.Values) {
        $match = @($targets | Where-Object { $_.Path -eq $entry.Path -and $_.Name -eq $entry.Name })
        $identity = $entry.Path + '|' + $entry.Name
        if ($match.Count -ne 1 -or $seen.ContainsKey($identity)) { throw 'Unexpected or duplicate registry value in backup.' }
        $seen[$identity] = $true
        if ($entry.Exists -and $entry.Kind -notin @('DWord','QWord','String','ExpandString','MultiString','Binary')) { throw 'Unsupported registry type in backup.' }
    }
    if ([int]$state.ServiceStart -notin @(2,3,4)) { throw 'Invalid service startup setting in backup.' }
    $errors = @()
    foreach ($entry in $state.Values) {
        try {
            if ($entry.Exists) {
                $value = $entry.Data
                if ($entry.Kind -eq 'Binary') { $value = [byte[]]$value }
                if ($entry.Kind -eq 'MultiString') { $value = [string[]]$value }
                Write-Value $entry.Path $entry.Name $entry.Kind $value
            } elseif ((Read-Value $entry.Path $entry.Name).Exists) {
                Remove-ItemProperty -LiteralPath $entry.Path -Name $entry.Name -ErrorAction Stop
            }
        } catch { $errors += $_.Exception.Message }
    }
    try {
        $mode = @{2='Automatic';3='Manual';4='Disabled'}[[int]$state.ServiceStart]
        if (-not $state.ServiceRunning) { Stop-Service -Name lfsvc -ErrorAction Stop }
        Set-Service -Name lfsvc -StartupType $mode
        if ($state.ServiceRunning) { Start-Service -Name lfsvc }
    } catch { $errors += $_.Exception.Message }
    if ($errors.Count) { throw ('Restore could not finish: ' + ($errors -join '; ')) }
}
try {
    Write-Host 'X-STAGE Wi-Fi / Location repair for your personal computer' -ForegroundColor Cyan
    Write-Host 'This enables Windows location access, including desktop apps. It does not change Wi-Fi passwords, firewall, antivirus, or other privacy categories.'
    Write-Host ('Original user SID: ' + $UserSid)
    Write-Host ('Backup and log folder: ' + $backupRoot)
    if ($RestoreLatest) {
        $latest = Get-ChildItem -LiteralPath $backupRoot -Filter 'backup-*.json' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if (-not $latest) { throw 'No backup is available for this user.' }
        $state = Get-Content -LiteralPath $latest.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        Restore-State $state
        Write-Host 'Previous registry values and service state restored. Restart Windows if needed.' -ForegroundColor Green
    } else {
        $service = Get-Service -Name lfsvc
        $serviceStart = (Get-ItemProperty -LiteralPath "$machine\SYSTEM\CurrentControlSet\Services\lfsvc" -Name Start).Start
        if ([int]$serviceStart -notin @(2,3,4)) { throw 'Unexpected Geolocation Service configuration; no changes made.' }
        $values = @($targets | ForEach-Object { Read-Value $_.Path $_.Name })
        $state = [pscustomobject]@{ Schema=1; UserSid=$UserSid; Created=(Get-Date).ToString('o'); Values=$values; ServiceStart=[int]$serviceStart; ServiceRunning=($service.Status -eq 'Running') }
        $backupPath = Join-Path $backupRoot ('backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8) + '.json')
        $state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $backupPath -Encoding UTF8
        # A complete readable backup is required before the first mutation.
        $verified = Get-Content -LiteralPath $backupPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if (@($verified.Values).Count -ne $targets.Count) { throw 'Backup verification failed; no changes made.' }
        try {
            foreach ($target in $targets) {
                if ($target.Operation -eq 'Remove') {
                    $before = Read-Value $target.Path $target.Name
                    if ($before.Exists) { Remove-ItemProperty -LiteralPath $target.Path -Name $target.Name }
                } else { Write-Value $target.Path $target.Name $target.Kind $target.Value }
                Write-Host ('Applied: ' + $target.Name + ' [' + $target.Path + ']')
            }
            if ($serviceStart -eq 4) { Set-Service -Name lfsvc -StartupType Manual }
            Start-Service -Name lfsvc
            foreach ($target in $targets) {
                $after = Read-Value $target.Path $target.Name
                if ($target.Operation -eq 'Remove' -and $after.Exists) { throw ('Policy is still present: ' + $target.Name) }
                if ($target.Operation -eq 'Set' -and (-not $after.Exists -or $after.Data -ne $target.Value)) { throw ('Value verification failed: ' + $target.Name) }
            }
            Write-Host 'Repair values verified. This does not yet prove that X-Stage can read the Wi-Fi name.' -ForegroundColor Green
            Write-Host 'Close and reopen X-Stage, then choose Check again in Mobile Remote.'
            Write-Host 'If it is still blocked, restart Windows once. A local Group Policy or privacy utility may reapply its settings.'
        } catch {
            $failure = $_.Exception.Message
            Write-Host ('Repair failed: ' + $failure) -ForegroundColor Red
            try { Restore-State $state; Write-Host 'Changes rolled back to the saved values.' }
            catch { Write-Host ('Automatic rollback was incomplete: ' + $_.Exception.Message) -ForegroundColor Red }
            throw $failure
        }
    }
    Start-Process 'ms-settings:privacy-location'
} catch {
    $exitCode = 1
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ('Keep this log for diagnosis: ' + $logPath)
} finally {
    Stop-Transcript | Out-Null
}
Write-Host ('Log: ' + $logPath)
if (-not $NoPause) { Read-Host 'Press Enter to close' }
exit $exitCode
