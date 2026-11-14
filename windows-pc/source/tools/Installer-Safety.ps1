Set-StrictMode -Version 2

# Some restricted hosts expose the in-box JSON cmdlets but not Get-FileHash.
# Preserve SHA-256 verification there instead of weakening the backup checks.
if (!(Get-Command Get-FileHash -ErrorAction SilentlyContinue)) {
    function Get-FileHash {
        param([Parameter(Mandatory=$true)][string]$LiteralPath,
              [ValidateSet('SHA256')][string]$Algorithm='SHA256')
        $stream=[IO.File]::OpenRead($LiteralPath)
        $hash=[Security.Cryptography.SHA256]::Create()
        try {
            $value=([BitConverter]::ToString($hash.ComputeHash($stream))).Replace('-','')
            return [PSCustomObject]@{Path=$LiteralPath;Algorithm=$Algorithm;Hash=$value}
        } finally { $hash.Dispose(); $stream.Dispose() }
    }
}

function Assert-XStageTarget([string]$Target, [string]$File) {
    $base = [IO.Path]::GetFullPath($Target).TrimEnd('\')
    $full = [IO.Path]::GetFullPath($File)
    if (!$full.StartsWith($base+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Update path escapes the installation.' }
    $relative = $full.Substring($base.Length+1)
    $allowed = $relative -match '^(App|Source)\\' -or $relative -in @('Start-Karaoke.cmd','X-Stage Karaoke.cmd','Setup-Audio.cmd','X-Stage Karaoke.lnk')
    if (!$allowed) { throw ('Protected path cannot be updated: '+$relative) }
    $check = $full
    while ($check -and $check.Length -ge $base.Length) {
        if (Test-Path -LiteralPath $check) {
            if ((Get-Item -LiteralPath $check -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse points are not supported by the updater.' }
        }
        $check = Split-Path -Parent $check
    }
    return $relative
}

function Get-XStageUpdatePlan([string]$Target, [object[]]$Copies) {
    $seen = @{}
    $plan = @()
    foreach ($copy in $Copies) {
        $item = Get-Item -LiteralPath $copy.Item -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Package contains a reparse point.' }
        $destination = Join-Path $copy.Folder $item.Name
        $files = if ($item.PSIsContainer) { @(Get-ChildItem -LiteralPath $item.FullName -File -Recurse -Force) } else { @($item) }
        foreach ($file in $files) {
            if ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Package contains a file link.' }
            if ($file.FullName -match '\\__pycache__\\' -or $file.Extension -eq '.pyc') { continue }
            $to = if ($item.PSIsContainer) { Join-Path $destination $file.FullName.Substring($item.FullName.Length+1) } else { $destination }
            $relative = Assert-XStageTarget $Target $to
            if ($seen.ContainsKey($relative)) { continue }
            $seen[$relative] = $true
            if ((Test-Path -LiteralPath $to -PathType Leaf) -and
                (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash -eq (Get-FileHash -LiteralPath $to -Algorithm SHA256).Hash) { continue }
            $plan += [PSCustomObject]@{Source=$file.FullName;Destination=$to;Relative=$relative}
        }
    }
    foreach ($name in @('Start-Karaoke.cmd','X-Stage Karaoke.cmd','Setup-Audio.cmd','X-Stage Karaoke.lnk')) {
        $destination = Join-Path $Target $name
        $null = Assert-XStageTarget $Target $destination
        $plan += [PSCustomObject]@{Source=$null;Destination=$destination;Relative=$name}
    }
    return $plan
}

function Backup-XStageUpdate([string]$Target, [object[]]$Plan) {
    $base = [IO.Path]::GetFullPath($Target).TrimEnd('\')
    # Keep backups outside App/Source so an update never includes its own backup.
    $backup = Join-Path $base ('Backups\Program\'+[DateTime]::Now.ToString('yyyyMMdd-HHmmss-fff')+'-'+[Guid]::NewGuid().ToString('N'))
    $ancestor = Split-Path -Parent $backup
    while ($ancestor -and $ancestor.Length -ge $base.Length) {
        if ((Test-Path -LiteralPath $ancestor) -and ((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Backup path contains a reparse point.' }
        $ancestor = Split-Path -Parent $ancestor
    }
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    $records = @()
    foreach ($entry in $Plan) {
        $relative = Assert-XStageTarget $Target $entry.Destination
        $existed = Test-Path -LiteralPath $entry.Destination -PathType Leaf
        $hash = $null
        if ($existed) {
            $saved = Join-Path $backup $relative
            New-Item -ItemType Directory -Path (Split-Path -Parent $saved) -Force | Out-Null
            Copy-Item -LiteralPath $entry.Destination -Destination $saved -ErrorAction Stop
            $hash = (Get-FileHash -LiteralPath $entry.Destination -Algorithm SHA256).Hash
            if ((Get-FileHash -LiteralPath $saved -Algorithm SHA256).Hash -ne $hash) { throw 'Backup verification failed. Installation has not started.' }
        }
        $records += [PSCustomObject]@{Relative=$relative;Existed=$existed;SHA256=$hash}
    }
    [PSCustomObject]@{Schema=1;Target=$base;Files=@($records)} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $backup 'manifest.json') -Encoding UTF8
    return $backup
}

function Restore-XStageUpdate([string]$Target, [string]$Backup) {
    $info = Get-Content -LiteralPath (Join-Path $Backup 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($info.Target -ine [IO.Path]::GetFullPath($Target).TrimEnd('\')) { throw 'Backup belongs to another installation.' }
    # Validate the complete restore before replacing any file.
    foreach ($record in $info.Files) {
        $destination = Join-Path $Target $record.Relative
        $null = Assert-XStageTarget $Target $destination
        if ($record.Existed) {
            $saved = Join-Path $Backup $record.Relative
            if (!(Test-Path -LiteralPath $saved -PathType Leaf) -or (Get-FileHash -LiteralPath $saved -Algorithm SHA256).Hash -ne $record.SHA256) { throw 'Backup is incomplete or has changed.' }
        }
    }
    foreach ($record in $info.Files) {
        $destination = Join-Path $Target $record.Relative
        if ($record.Existed) {
            Copy-Item -LiteralPath (Join-Path $Backup $record.Relative) -Destination $destination -Force -ErrorAction Stop
        } elseif (Test-Path -LiteralPath $destination -PathType Leaf) {
            Remove-Item -LiteralPath $destination -Force -ErrorAction Stop
        }
    }
}
