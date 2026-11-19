"""Verified, Windows per-user self-updater for Song Studio Pro.

Never trust a displayed filename, never execute a partial download. The
published HTTPS release feed must supply a matching GitHub binary and SHA-256.
The current workspace and SQLite data are not replaced during an update.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

VERSION="0.1.22"
MANIFEST_URL="https://webbase-x.github.io/xstage/downloads/song-studio-pro-latest.json"
RELEASE=re.compile(
    r"^https://github\.com/webbase-x/xstage/releases/download/"
    r"song-studio-pro-v(\d+\.\d+\.\d+)-preview/"
    r"(X-Stage-Song-Studio-Pro-v\1-preview\.exe)$")
MAX_FILE=600*1024*1024

def version_tuple(s):
    if not re.fullmatch(r"\d+\.\d+\.\d+",str(s)):raise ValueError("เลขรุ่นไม่ถูกต้อง")
    return tuple(map(int,str(s).split(".")))

def _staged_dir(workspace):
    d=Path(workspace)/"UPDATES"
    d.mkdir(parents=True,exist_ok=True)
    return d

def validate(data):
    if data.get("name")!="X-Stage Song Studio Pro" or not data.get("available"):
        raise ValueError("ยังไม่มีไฟล์ Song Studio Pro ที่ยืนยันแล้ว")
    version=str(data.get("version",""))
    version_tuple(version)
    url=str(data.get("download_url",""))
    match=RELEASE.fullmatch(url)
    if not match or match.group(1)!=version:
        raise ValueError("URL ดาวน์โหลดไม่ใช่ Release ของ Song Studio Pro")
    digest=str(data.get("sha256","")).lower()
    if not re.fullmatch(r"[a-f0-9]{64}",digest):
        raise ValueError("ไม่มี SHA-256 ที่ใช้ยืนยันโปรแกรม")
    return {"version":version,"url":url,"sha256":digest,
            "filename":match.group(2)}

def check():
    req=urllib.request.Request(MANIFEST_URL,headers={
        "User-Agent":"XStageSongStudioPro/"+VERSION,
        "Cache-Control":"no-cache"})
    with urllib.request.urlopen(req,timeout=12) as res:
        if res.url.split("?")[0]!=MANIFEST_URL:
            raise ValueError("แหล่งตรวจอัปเดตถูกเปลี่ยนเส้นทาง")
        raw=res.read(16385)
    if len(raw)>16384:
        raise ValueError("ไฟล์แจ้งอัปเดตมีขนาดผิดปกติ")
    target=validate(json.loads(raw.decode("utf-8")))
    target["current_version"]=VERSION
    target["newer"]=version_tuple(target["version"])>version_tuple(VERSION)
    return target

def ready_file(workspace):
    directory=_staged_dir(workspace)
    pointer=directory/"ready.json"
    if not pointer.is_file():return None
    try:
        ready=json.loads(pointer.read_text(encoding="utf-8"))
        target=validate(ready)
        p=directory/target["filename"]
        if not p.is_file() or not p.is_file() or p.stat().st_size<1024*1024:return None
        with p.open("rb") as stream:
            digest=hashlib.file_digest(stream,"sha256").hexdigest()
        if digest!=target["sha256"]:
            return None
        return {**target,"path":str(p)}
    except (OSError,ValueError,KeyError,TypeError):
        return None

def download(workspace,info,progress,cancel):
    target=validate(info)
    if version_tuple(target["version"])<=version_tuple(VERSION):
        raise ValueError("ยังไม่มีรุ่นใหม่กว่าโปรแกรมที่ใช้อยู่")
    if sys.platform!="win32" or not getattr(sys,"frozen",False):
        raise ValueError("การติดตั้งอัตโนมัติใช้ได้จาก Windows EXE เท่านั้น")
    old=ready_file(workspace)
    if old and old["sha256"]==target["sha256"]:
        return old
    root=_staged_dir(workspace)
    destination=root/target["filename"]
    partial=root/(target["filename"]+".partial")
    req=urllib.request.Request(target["url"],
        headers={"User-Agent":"XStageSongStudioPro/"+VERSION})
    bytes_read=0
    h=hashlib.sha256()
    try:
        with urllib.request.urlopen(req,timeout=30) as response,partial.open("wb") as output:
            if not response.url.startswith("https://"):
                raise ValueError("การดาวน์โหลดไม่ได้ใช้ HTTPS")
            size=int(response.headers.get("Content-Length") or 0)
            if size>MAX_FILE:raise ValueError("ไฟล์อัปเดตใหญ่ผิดปกติ")
            while True:
                if cancel and cancel.is_set():
                    raise RuntimeError("ยกเลิกการดาวน์โหลดอัปเดตแล้ว")
                chunk=response.read(1024*1024)
                if not chunk:break
                bytes_read+=len(chunk)
                if bytes_read>MAX_FILE:raise ValueError("ไฟล์อัปเดตเกินขนาดสูงสุด")
                output.write(chunk);h.update(chunk)
                if progress and (bytes_read%(4*1024*1024)<len(chunk)):
                    progress({"done":bytes_read,"total":size,
                              "downloaded_bytes":bytes_read}, "กำลังดาวน์โหลดรุ่น "+target["version"])
        if bytes_read<1024*1024 or h.hexdigest()!=target["sha256"]:
            raise ValueError("SHA-256 ไม่ตรงกับไฟล์ที่เผยแพร่ ยกเลิกการติดตั้ง")
        os.replace(partial,destination)
        (root/"ready.json").write_text(json.dumps({
            "name":"X-Stage Song Studio Pro","available":True,
            "version":target["version"],"download_url":target["url"],
            "sha256":target["sha256"]},ensure_ascii=False),encoding="utf-8")
        if progress:progress({"done":bytes_read,"total":bytes_read,
                              "downloaded_bytes":bytes_read},"ดาวน์โหลดและตรวจ SHA-256 สำเร็จ")
        return {**target,"path":str(destination)}
    finally:
        partial.unlink(missing_ok=True)

def _ps_string(value):
    return "'"+str(value).replace("'","''")+"'"

def install_and_restart(workspace,old_pid=None):
    """Start detached PowerShell helper that swaps EXE after current PID exits."""
    ready=ready_file(workspace)
    if not ready:raise ValueError("ยังไม่มีไฟล์อัปเดตที่ตรวจสอบ SHA-256 สำเร็จ")
    if sys.platform!="win32" or not getattr(sys,"frozen",False):
        raise ValueError("อัปเดตและเปิดใหม่อัตโนมัติใช้ได้จาก Windows EXE เท่านั้น")
    root=_staged_dir(workspace)
    local=os.environ.get("LOCALAPPDATA")
    if not local or not Path(local).is_dir():
        raise ValueError("Windows ไม่พบ Local AppData ที่ปลอดภัยสำหรับติดตั้ง")
    target=Path(local)/"Programs"/"X-Stage Song Studio Pro"/"X-Stage Song Studio Pro.exe"
    target.parent.mkdir(parents=True,exist_ok=True)
    workspace=str(Path(workspace).resolve())
    pid=old_pid or os.getpid()
    # Script never deletes the user's SQLite or media; it replaces only
    # the version-managed EXE after the old process has exited.
    log=root/"last-update.log"
    script=root/"apply-update.ps1"
    content=f"""
$ErrorActionPreference = 'Stop'
$source = {_ps_string(ready['path'])}
$dest = {_ps_string(str(target))}
$workspace = {_ps_string(workspace)}
$expected = {_ps_string(ready['sha256'])}
$log = {_ps_string(str(log))}
$pidToWait = {int(pid)}
try {{
  for($n = 0; $n -lt 180; $n++) {{
    if (-not (Get-Process -Id $pidToWait -ErrorAction SilentlyContinue)) {{ break }}
    Start-Sleep -Milliseconds 500
  }}
  if (Get-Process -Id $pidToWait -ErrorAction SilentlyContinue) {{
    throw 'The old Song Studio Pro process is still running'
  }}
  $found = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($found -ne $expected) {{ throw 'Downloaded EXE SHA-256 mismatch' }}
  Move-Item -LiteralPath $source -Destination $dest -Force
  Start-Process -FilePath $dest -ArgumentList @('--workspace',('"' + $workspace + '"'))
  'Pro updated and started at ' + (Get-Date) | Out-File -LiteralPath $log -Encoding UTF8
}} catch {{
  $_.Exception.Message | Out-File -LiteralPath $log -Encoding UTF8
  exit 1
}}
"""
    script.write_text(content,encoding="utf-8-sig")
    subprocess.Popen(["powershell.exe","-NoProfile","-NonInteractive",
                      "-ExecutionPolicy","Bypass","-File",str(script)],
                     creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),
                     close_fds=True)
    return {"scheduled":True,"version":ready["version"],
            "install_path":str(target)}
