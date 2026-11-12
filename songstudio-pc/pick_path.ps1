#requires -Version 5.1
# X-Stage Song Studio — interactive Windows folder / file picker.
# Runs within the logged-in user's desktop session, never inside a remote web page.
param(
    [Parameter(Mandatory=$true)][ValidateSet('source','workspace','download','soundfont','oauth','vocal')]
    [string]$Kind,
    [string]$InitialPath = '',
    [switch]$SelfTest
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
if ($SelfTest) {
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("C:\ทดสอบ\เพลง"))
    Write-Output "PICKER_SELFTEST:$encoded"
    exit 0
}
[System.Windows.Forms.Application]::EnableVisualStyles()

# A tiny top-most owner ensures the dialog is above Edge (app window mode),
# not hidden behind the browser or the PowerShell host window.
$owner = New-Object System.Windows.Forms.Form
$owner.FormBorderStyle = 'None'
$owner.ShowInTaskbar = $false
$owner.TopMost = $true
$owner.Width = 1
$owner.Height = 1
$owner.Opacity = 0.01
$owner.StartPosition = 'CenterScreen'
$dialog = $null
try {
    if ($Kind -in @('source','workspace','download')) {
        $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
        $dialog.Description = @{
            source = 'เลือกโฟลเดอร์เพลงต้นฉบับ'
            workspace = 'เลือกโฟลเดอร์เก็บเพลงที่สร้าง'
            download = 'เลือกโฟลเดอร์ดาวน์โหลด'
        }[$Kind]
        $dialog.ShowNewFolderButton = $true
        if ($InitialPath -and (Test-Path -LiteralPath $InitialPath -PathType Container)) {
            $dialog.SelectedPath = $InitialPath
        }
    } else {
        $dialog = New-Object System.Windows.Forms.OpenFileDialog
        $dialog.Title = if ($Kind -eq 'vocal') { 'นำเข้าเพลงใหม่สำหรับสร้างเนื้อร้อง AI' } elseif ($Kind -eq 'soundfont') { 'เลือก SoundFont (.sf2 / .sf3)' } else { 'เลือก Google OAuth JSON' }
        $dialog.Filter = if ($Kind -eq 'soundfont') {
            'SoundFont (*.sf2;*.sf3)|*.sf2;*.sf3|All files (*.*)|*.*'
        } elseif ($Kind -eq 'vocal') {
            'Audio (*.mp3;*.m4a;*.wav;*.flac;*.aac;*.ogg;*.wma;*.mp4;*.oga)|*.mp3;*.m4a;*.wav;*.flac;*.aac;*.ogg;*.wma;*.mp4;*.oga'
        } else {
            'Google OAuth JSON (*.json)|*.json|All files (*.*)|*.*'
        }
        $dialog.CheckFileExists = $true
        $dialog.Multiselect = $Kind -eq 'vocal'
        $dialog.RestoreDirectory = $true
        if ($InitialPath) {
            if (Test-Path -LiteralPath $InitialPath -PathType Leaf) {
                $dialog.InitialDirectory = Split-Path -Parent $InitialPath
                $dialog.FileName = Split-Path -Leaf $InitialPath
            } elseif (Test-Path -LiteralPath $InitialPath -PathType Container) {
                $dialog.InitialDirectory = $InitialPath
            }
        }
    }
    [void]$owner.Show()
    [void]$owner.Activate()
    $answer = $dialog.ShowDialog($owner)
    if ($answer -eq [System.Windows.Forms.DialogResult]::OK) {
        $chosen = if ($Kind -eq 'vocal') { ConvertTo-Json -InputObject @($dialog.FileNames) -Compress } elseif ($Kind -in @('source','workspace','download')) { $dialog.SelectedPath } else { $dialog.FileName }
        if ([string]::IsNullOrWhiteSpace($chosen)) {
            throw 'หน้าต่างเลือกไฟล์ไม่คืนค่าที่เลือก'
        }
        # Encode Unicode paths on stdout, independent of Windows OEM / Thai code pages.
        $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($chosen))
        Write-Output "PICKED:$encoded"
    } else {
        Write-Output 'CANCELLED'
    }
} finally {
    if ($null -ne $dialog) { $dialog.Dispose() }
    $owner.Close()
    $owner.Dispose()
}
