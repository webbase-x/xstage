$ErrorActionPreference = 'Stop'
function Assert-XStagePlatform {
    if ([Environment]::OSVersion.Platform -ne 'Win32NT' -or -not [Environment]::Is64BitOperatingSystem -or [Environment]::OSVersion.Version.Major -lt 10) { throw 'X-Stage requires Windows 10/11 x64.' }
    if (-not [Environment]::Is64BitProcess) { throw 'Run the 64-bit Install-to-D.cmd launcher.' }
    if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') { throw 'This package is for AMD64/Intel x64. Native ARM64 is not supported.' }
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
}
function Get-XStageDownload([string]$Url,[string]$Name,[string]$Offline,[scriptblock]$Validate) {
    $local = Join-Path $Offline $Name
    if (Test-Path -LiteralPath $local -PathType Leaf) {
        try { if ($Validate) { & $Validate $local | Out-Null }; return $local }
        catch { Write-Warning ('Offline package invalid; keeping original and downloading a fresh copy: '+$local) }
    }
    $cache = Join-Path $env:LOCALAPPDATA 'XStageKaraoke\DownloadCache'
    New-Item -ItemType Directory -Path $cache -Force | Out-Null
    $path = Join-Path $cache $Name
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        try { if ($Validate) { & $Validate $path | Out-Null }; return $path }
        catch { Write-Warning ('Discarding invalid download cache: '+$path); Remove-Item -LiteralPath $path -Force }
    }
    $partial = $path + '.' + [Guid]::NewGuid().ToString('N') + '.partial'
    try {
        for ($attempt=1; $attempt -le 3; $attempt++) {
            try {
                Write-Host ("Download {0} ({1}/3)" -f $Name,$attempt)
                Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $partial -TimeoutSec 180
                if ((Get-Item -LiteralPath $partial).Length -lt 1024) { throw 'Download is empty or incomplete.' }
                if ($Validate) { & $Validate $partial | Out-Null }
                Move-Item -LiteralPath $partial -Destination $path -Force
                return $path
            } catch {
                if ($attempt -eq 3) { throw ("Cannot download {0}. Check internet/proxy or place the publisher package in {1}. {2}" -f $Name,$Offline,$_.Exception.Message) }
                Start-Sleep -Seconds 2
            }
        }
    } finally { if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force } }
}
function Assert-XStagePublisher([string]$Path,[string]$Publisher) {
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne 'Valid' -or -not $signature.SignerCertificate -or $signature.SignerCertificate.Subject -notmatch $Publisher) { throw ('Publisher signature validation failed: '+$Path) }
}
function Assert-XStagePE([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $reader = New-Object IO.BinaryReader($stream)
    try {
        if ($stream.Length -lt 64 -or $reader.ReadUInt16() -ne 0x5a4d) { throw 'Missing MZ header' }
        $stream.Position=0x3c; $offset=$reader.ReadUInt32()
        if ($offset -gt $stream.Length-6) { throw 'Invalid PE offset' }
        $stream.Position=$offset
        if ($reader.ReadUInt32() -ne 0x4550 -or $reader.ReadUInt16() -ne 0x8664) { throw 'Not an x64 PE library' }
    } catch { throw ('Invalid native file '+$Path+': '+$_.Exception.Message) }
    finally { $reader.Dispose() }
}

function Assert-XStageArchive([string]$Path,[string]$Dll) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip=[IO.Compression.ZipFile]::OpenRead($Path)
    $temp=[IO.Path]::GetTempFileName()
    try {
        $entry=$zip.Entries | Where-Object { $_.FullName.Replace('\','/') -ieq ('x64/'+$Dll) } | Select-Object -First 1
        if (-not $entry) { throw ('Missing x64/'+$Dll) }
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entry,$temp,$true)
        Assert-XStagePE $temp
    } finally { $zip.Dispose(); Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue }
}
