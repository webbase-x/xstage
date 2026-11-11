# X-Stage Windows PC release update. Do not advertise source ZIPs as installers.
# The installed X-Stage launcher or app calls this when the app starts.
# -Install launches a verified newer Windows installer, with Windows consent.
param(
    [string]$CurrentVersion = '0.0.0',
    [int]$CurrentBuild = 0,
    [switch]$Install,
    [switch]$Startup
)
$ErrorActionPreference = 'Stop'
$metadataUri = 'https://webbase-x.github.io/xstage/downloads/windows-pc-latest.json'

try {
    $metaUrl = $metadataUri + '?t=' + [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $meta = Invoke-RestMethod -Uri $metaUrl -TimeoutSec 15
    if ($meta.available -ne $true -or [string]::IsNullOrWhiteSpace($meta.installer_file)) {
        if (-not $Startup) { Write-Host 'ยังไม่มี Windows Installer รุ่นใหม่ที่เผยแพร่และตรวจสอบแล้ว' }
        exit 0
    }
    $latest = [version]([string]$meta.version).TrimStart('v')
    $current = [version]([string]$CurrentVersion).TrimStart('v')
    $newBuild = [int]$meta.build
    $newer = ($latest -gt $current) -or ($latest -eq $current -and
        $CurrentBuild -gt 0 -and $newBuild -gt $CurrentBuild)
    if (-not $newer) {
        if (-not $Startup) { Write-Host "X-Stage Windows PC $CurrentVersion เป็นรุ่นล่าสุดแล้ว" }
        exit 0
    }
    $file = [string]$meta.installer_file
    $expectedFile = "X-Stage-Karaoke-Windows-v$($meta.version)-build$($meta.build)"
    if ($file -notin @("$expectedFile.exe", "$expectedFile.msi") -or
        $file -notmatch '^X-Stage-Karaoke-Windows-v[0-9.]+-build[0-9]+\.(exe|msi)$') {
        throw 'ข้อมูลชื่อไฟล์ Windows Installer ไม่ตรงกับรุ่นที่ประกาศ'
    }
    $expected = [string]$meta.sha256
    if ($expected -notmatch '^[0-9a-fA-F]{64}$') {
        throw 'ไม่มี SHA-256 ที่ถูกต้องสำหรับตรวจสอบ Windows Installer'
    }
    Write-Host "พบ X-Stage Windows PC v$latest (Build $newBuild)"
    if (-not $Install) {
        Write-Host 'เรียกสคริปต์ด้วย -Install เพื่อดาวน์โหลดและเปิดตัวติดตั้ง'
        exit 0
    }

    $uri = 'https://webbase-x.github.io/xstage/downloads/' + [uri]::EscapeDataString($file)
    $downloadDirectory = Join-Path $env:LOCALAPPDATA 'XStageKaraoke\Updates'
    New-Item -ItemType Directory -Force -Path $downloadDirectory | Out-Null
    $destination = Join-Path $downloadDirectory $file
    # Never launch an existing cached installer before checking its integrity.
    if ((Test-Path $destination -PathType Leaf) -and
        (Get-FileHash -Path $destination -Algorithm SHA256).Hash -ine $expected) {
        Remove-Item $destination -Force
    }
    if (-not (Test-Path $destination -PathType Leaf)) {
        $tempFile = "$destination.download"
        try {
            Invoke-WebRequest -Uri $uri -OutFile $tempFile -TimeoutSec 180
            $actual = (Get-FileHash -Path $tempFile -Algorithm SHA256).Hash
            if ($actual -ine $expected) { throw 'ไฟล์อัปเดตไม่ผ่านการตรวจสอบ SHA-256' }
            Move-Item -LiteralPath $tempFile -Destination $destination -Force
        } finally {
            Remove-Item $tempFile -Force -ErrorAction SilentlyContinue
        }
    }
    $actual = (Get-FileHash -Path $destination -Algorithm SHA256).Hash
    if ($actual -ine $expected) { throw 'ไฟล์อัปเดตที่ดาวน์โหลดไม่ตรงกับ SHA-256' }
    Write-Host 'ตรวจ SHA-256 ผ่าน · กำลังเปิดตัวติดตั้ง Windows'
    # The installer itself may request UAC/close the running app. Never bypass.
    Start-Process -FilePath $destination -ErrorAction Stop
} catch {
    Write-Error ("ตรวจสอบหรือดาวน์โหลดอัปเดตไม่สำเร็จ: " + $_.Exception.Message)
    exit 1
}
