"""Windows-native folder/file picker independent of Qt WebEngine.

The local HTTP engine may be used from Edge/Chrome/Firefox.  Picker requests
launch Windows PowerShell in STA mode and use System.Windows.Forms dialogs,
so the browser never needs filesystem-path privileges and no QWebEngine bridge
is involved.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import threading
from pathlib import Path

_PICKER_LOCK=threading.Lock()

_SCRIPT=r"""
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
$kind=$env:XSTAGE_PICKER_KIND
$current=$env:XSTAGE_PICKER_CURRENT
# Resolve the actual application HWND. A hidden, TopMost owner that is first
# shown and activated flashes and steals focus in Qt WebEngine on Windows.
# Reuse the real main window instead; if unavailable, keep the fallback owner
# INVISIBLE (do not call Show or Activate).
Add-Type -TypeDefinition @'
using System;
using System.Windows.Forms;
using System.Runtime.InteropServices;
public sealed class XStagePickerOwner : IWin32Window {
    public IntPtr Handle {get; private set;}
    public XStagePickerOwner(IntPtr handle) {Handle=handle;}
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
}
'@ -ReferencedAssemblies @('System.Windows.Forms')
$parentHandle=[IntPtr]::Zero
try {
    $parentProcess=Get-Process -Id ([int]$env:XSTAGE_PICKER_PARENT_PID) -ErrorAction SilentlyContinue
    if ($null -ne $parentProcess) {$parentHandle=$parentProcess.MainWindowHandle}
} catch {}
if ($parentHandle -eq [IntPtr]::Zero) {
    $parentHandle=[XStagePickerOwner]::GetForegroundWindow()
}
$fallback=$null
if ($parentHandle -ne [IntPtr]::Zero) {
    $owner=[XStagePickerOwner]::new($parentHandle)
} else {
    $fallback=New-Object System.Windows.Forms.Form
    $fallback.ShowInTaskbar=$false
    $fallback.Opacity=0
    $fallback.Width=1
    $fallback.Height=1
    $null=$fallback.Handle
    $owner=$fallback
}
try {
if ($kind -eq 'folder') {
    $dlg=New-Object System.Windows.Forms.FolderBrowserDialog
    $dlg.Description='เลือกโฟลเดอร์เพลงต้นฉบับ'
    $dlg.ShowNewFolderButton=$false
    if ($current -and (Test-Path -LiteralPath $current -PathType Container)) {
        $dlg.SelectedPath=$current
    }
    $result=$dlg.ShowDialog($owner)
    if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
        [Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
        [Console]::Write($dlg.SelectedPath)
    }
    $dlg.Dispose()
}
elseif ($kind -eq 'media') {
    $dlg=New-Object System.Windows.Forms.OpenFileDialog
    $dlg.Title='เลือกไฟล์เพลงสำหรับนำเข้า'
    $dlg.Filter='ไฟล์เพลงและวิดีโอ (*.mid;*.midi;*.kar;*.mp3;*.m4a;*.wav;*.flac;*.mp4;*.mkv;*.webm;*.mov)|*.mid;*.midi;*.kar;*.mp3;*.m4a;*.wav;*.flac;*.mp4;*.mkv;*.webm;*.mov|ไฟล์ทั้งหมด (*.*)|*.*'
    $dlg.CheckFileExists=$true
    if ($current -and (Test-Path -LiteralPath $current -PathType Leaf)) {
        $dlg.InitialDirectory=[System.IO.Path]::GetDirectoryName($current)
    }
    $result=$dlg.ShowDialog($owner)
    if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
        [Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
        [Console]::Write($dlg.FileName)
    }
    $dlg.Dispose()
}
elseif ($kind -eq 'lrc') {
    $dlg=New-Object System.Windows.Forms.OpenFileDialog
    $dlg.Title='เลือกไฟล์เนื้อร้อง .LRC'
    $dlg.Filter='ไฟล์เนื้อร้อง LRC (*.lrc)|*.lrc|ไฟล์ทั้งหมด (*.*)|*.*'
    $dlg.CheckFileExists=$true
    if ($current) {
        if (Test-Path -LiteralPath $current -PathType Container) {
            $dlg.InitialDirectory=$current
        } elseif (Test-Path -LiteralPath $current -PathType Leaf) {
            $dlg.InitialDirectory=[System.IO.Path]::GetDirectoryName($current)
        }
    }
    $result=$dlg.ShowDialog($owner)
    if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
        [Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
        [Console]::Write($dlg.FileName)
    }
    $dlg.Dispose()
}
else {
    [Console]::Error.Write('invalid picker kind')
    exit 2
}
} finally {
    if ($null -ne $fallback) {$fallback.Dispose()}
}
"""

def pick(kind,current="",log=None):
    if sys.platform!="win32":
        raise RuntimeError("หน้าต่างเลือกโฟลเดอร์ Windows ใช้ได้เฉพาะ Windows")
    if kind not in ("folder","lrc","media"):
        raise ValueError("ประเภทการเลือกไม่ถูกต้อง")
    current=str(current or "").strip().strip('"')
    env=os.environ.copy()
    env["XSTAGE_PICKER_KIND"]=kind
    env["XSTAGE_PICKER_CURRENT"]=current
    env["XSTAGE_PICKER_PARENT_PID"]=str(os.getpid())
    started=time.monotonic()
    if log:
        log("picker.launch",kind=kind,current=current)
    flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
    if not _PICKER_LOCK.acquire(blocking=False):
        if log: log("picker.busy",kind=kind)
        raise RuntimeError("หน้าต่างเลือกไฟล์หรือโฟลเดอร์ยังเปิดอยู่")
    try:
        try:
            run=subprocess.run(
                ["powershell.exe","-NoProfile","-STA","-NonInteractive",
                 "-ExecutionPolicy","Bypass","-Command",_SCRIPT],
                env=env,capture_output=True,text=True,encoding="utf-8",
                errors="replace",timeout=300,creationflags=flags,check=False)
        except subprocess.TimeoutExpired as exc:
            if log: log("picker.timeout",kind=kind,elapsed=round(time.monotonic()-started,3))
            raise TimeoutError("หน้าต่างเลือกโฟลเดอร์ไม่ตอบสนองภายใน 5 นาที") from exc
    finally:
        _PICKER_LOCK.release()
    if run.returncode!=0:
        error=(run.stderr or run.stdout or "Windows Picker failed").strip()
        if log: log("picker.error",kind=kind,code=run.returncode,
                    elapsed=round(time.monotonic()-started,3),error=error[:800])
        raise RuntimeError("เปิดหน้าต่างเลือกโฟลเดอร์ของ Windows ไม่สำเร็จ: "+error[:500])
    chosen=(run.stdout or "").strip().lstrip("\ufeff")
    if chosen:
        p=Path(chosen)
        if kind=="folder" and not p.is_dir():
            if log: log("picker.invalid_result",kind=kind,path=chosen)
            raise RuntimeError("Windows ส่งพาธโฟลเดอร์ที่ไม่พบกลับมา")
        if kind in ("lrc","media") and not p.is_file():
            if log: log("picker.invalid_result",kind=kind,path=chosen)
            raise RuntimeError("Windows ส่งพาธไฟล์ที่ไม่พบกลับมา")
    if log: log("picker.result",kind=kind,cancelled=not bool(chosen),path=chosen,
                elapsed=round(time.monotonic()-started,3))
    return {"path":chosen,"cancelled":not bool(chosen)}
