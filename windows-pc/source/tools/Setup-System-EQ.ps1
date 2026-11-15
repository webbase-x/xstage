param([string]$UserSid='', [switch]$NoPause)
$ErrorActionPreference='Stop'
if (!$UserSid) { $UserSid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value }
if ($UserSid -notmatch '^S-1-5-[0-9-]+$') { throw 'Invalid Windows user SID.' }
$admin=([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (!$admin) {
    $arguments = @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+$PSCommandPath+'"'),'-UserSid',$UserSid)
    if ($NoPause) { $arguments += '-NoPause' }
    $process = Start-Process powershell.exe -Verb RunAs -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
    exit $process.ExitCode
}
try {
    $root=(Get-ItemProperty 'HKLM:\SOFTWARE\EqualizerAPO').ConfigPath
    $main=Join-Path $root 'config.txt'
    if (!(Test-Path -LiteralPath $main -PathType Leaf)) { throw 'Install Equalizer APO first and select your playback device.' }
    $folder=Join-Path $root 'XStage'
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
    $file=Join-Path $folder 'xstage-eq.txt'
    if (!(Test-Path -LiteralPath $file)) { [IO.File]::WriteAllText($file,"# X-Stage bypass - no filters`r`n",[Text.UTF8Encoding]::new($false)) }
    # Grant only the invoking user access to X-Stage's own config subdirectory.
    $acl=Get-Acl -LiteralPath $folder
    $sid=[Security.Principal.SecurityIdentifier]::new($UserSid)
    $rule=[Security.AccessControl.FileSystemAccessRule]::new($sid,'Modify','ContainerInherit,ObjectInherit','None','Allow')
    $acl.SetAccessRule($rule);Set-Acl -LiteralPath $folder -AclObject $acl
    $bytes=[IO.File]::ReadAllBytes($main)
    if ($bytes.Length -gt 1 -and (($bytes[0] -eq 255 -and $bytes[1] -eq 254) -or ($bytes[0] -eq 254 -and $bytes[1] -eq 255))) { throw 'config.txt uses UTF-16. Convert it to UTF-8 in Equalizer APO Editor first.' }
    $text=[Text.Encoding]::UTF8.GetString($bytes)
    if ($text.Contains('# X-STAGE SYSTEM EQ BEGIN')) {
        if (!$text.Contains('Include: XStage/xstage-eq.txt')) { throw 'Existing X-Stage include is damaged. Restore your config backup first.' }
    } else {
        $backup=$main+'.xstage-'+[DateTime]::Now.ToString('yyyyMMdd-HHmmss-fff')+'.bak'
        [IO.File]::WriteAllBytes($backup,$bytes)
        $prefix="# X-STAGE SYSTEM EQ BEGIN`r`nInclude: XStage/xstage-eq.txt`r`nDevice: all`r`nChannel: all`r`nStage: post-mix capture`r`n# X-STAGE SYSTEM EQ END`r`n"
        $bom=0
        if ($bytes.Length -ge 3 -and $bytes[0] -eq 239 -and $bytes[1] -eq 187 -and $bytes[2] -eq 191) { $bom=3 }
        $out=[IO.MemoryStream]::new();$head=[Text.Encoding]::UTF8.GetBytes($prefix)
        $out.Write($head,0,$head.Length);$out.Write($bytes,$bom,$bytes.Length-$bom)
        $tmp=$main+'.xstage.tmp';[IO.File]::WriteAllBytes($tmp,$out.ToArray());$out.Dispose()
        [IO.File]::Replace($tmp,$main,$null)
        Write-Host ('Original configuration backup: '+$backup)
    }
    Write-Host 'Connected. Return to X-Stage, select the same output device, and apply EQ.'
    Write-Host 'This does not verify APO is active. Use Device Selector, restart Windows if requested, then test audio.'
    Write-Host 'Existing APO filters remain active. X-Stage Bypass disables only X-Stage filters.'
} catch { Write-Host $_ -ForegroundColor Red; if (!$NoPause) { Read-Host 'Press Enter to close' }; exit 1 }
if (!$NoPause) { Read-Host 'Press Enter to close' }
exit 0
