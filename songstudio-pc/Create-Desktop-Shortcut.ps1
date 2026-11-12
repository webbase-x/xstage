#requires -Version 5.1
# Optional shortcut: gives the Windows desktop launcher the Song Studio PC icon.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Launcher = Join-Path $Root 'Start-Song-Studio.cmd'
$Icon = Join-Path $Root 'studio\app-icon.ico'
if (!(Test-Path -LiteralPath $Launcher) -or !(Test-Path -LiteralPath $Icon)) {
    throw 'Please extract the entire X-Stage Song Studio PC Ready ZIP before creating a shortcut.'
}
$Desktop = [Environment]::GetFolderPath('DesktopDirectory')
if (![IO.Directory]::Exists($Desktop)) { throw 'Windows Desktop folder is unavailable.' }
$Link = Join-Path $Desktop 'X-Stage Song Studio PC.lnk'
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($Link)
$Shortcut.TargetPath = $Launcher
$Shortcut.WorkingDirectory = $Root
$Shortcut.IconLocation = $Icon + ',0'
$Shortcut.Description = 'X-Stage Song Studio PC — professional music production'
$Shortcut.Save()
Write-Host ('Desktop shortcut with X-Stage Song Studio PC icon: ' + $Link)
