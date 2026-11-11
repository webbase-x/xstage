# X-Stage Windows PC update helper. Intended to be called by the Windows app's Update menu.
# A verified installer release must be published before this script offers installation.
param(
    [Parameter(Mandatory = $true)][string]$CurrentVersion,
    [switch]$Install
)
$ErrorActionPreference = 'Stop'
$metadataUri = 'https://webbase-x.github.io/xstage/downloads/windows-pc-latest.json'
try {
    $meta = Invoke-RestMethod -Uri ($metadataUri + '?t=' + [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) -TimeoutSec 15
    if ($meta.available -ne $true -or [string]::IsNullOrWhiteSpace($meta.installer_file)) {
        Write-Host 'ยังไม่มี X-Stage Windows PC รุ่นใหม่ที่ผ่านการตรวจสอบและพร้อมติดตั้ง'
        exit 0
    }
    $latest = [version]([string]$meta.version).TrimStart('v')
    $current = [version]([string]$CurrentVersion).TrimStart('v')
    if ($latest -le $current) {
        Write-Host "X-Stage Windows PC $CurrentVersion เป็นรุ่นล่าสุดแล้ว"
        exit 0
    }
    $file = [string]$meta.installer_file
    if ($file -notmatch '^X-Stage-Karaoke-Windows-v[0-9.]+-build[0-9]+\\.(exe|msi)$') {
        throw 'ชื่อไฟล์ตัวติดตั้งไม่ถูกต้อง'
    }
    $expected = [string]$meta.sha256
    if ($expected -notmatch '^[0-9a-fA-F]{64}$') { throw 'ไม่มี SHA-256 ของตัวติดตั้ง' }
    Write-Host "มี X-Stage Windows PC v$latest พร้อมอัปเดต"
    if (-not $Install) {
        Write-Host 'เรียกคำสั่งนี้อีกครั้งด้วย -Install เพื่อดาวน์โหลดและเปิดตัวติดตั้ง'
        exit 0
    }
    $uri = 'https://webbase-x.github.io/xstage/downloads/' + $file
    $downloadDirectory = Join-Path $env:TEMP 'XStageUpdates'
    New-Item -ItemType Directory -Force -Path $downloadDirectory | Out-Null
    $destination = Join-Path $downloadDirectory $file
    Invoke-WebRequest -Uri $uri -OutFile $destination -TimeoutSec 180
    $actual = (Get-FileHash -Path $destination -Algorithm SHA256).Hash
    if (-not $actual.Equals($expected, [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item $destination -Force -ErrorAction SilentlyContinue
        throw 'SHA-256 ไม่ตรงกัน ปฏิเสธการติดตั้ง'
    }
    Write-Host 'ตรวจสอบ SHA-256 ผ่าน กำลังเปิดตัวติดตั้ง (Windows อาจขอยืนยันสิทธิ์)'
    Start-Process -FilePath $destination
} catch {
    Write-Error ("ตรวจสอบหรือดาวน์โหลดอัปเดตไม่สำเร็จ: " + $_.Exception.Message)
    exit 1
}
