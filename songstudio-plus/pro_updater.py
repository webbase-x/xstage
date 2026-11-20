"""Verified, Windows per-user self-updater for Song Studio Pro.

Never trust a displayed filename, never execute a partial download. The
published HTTPS release feed must supply a matching GitHub binary and SHA-256.
The current workspace and SQLite data are not replaced during an update.
"""
from __future__ import annotations

import hashlib
import http.client
import shutil
import time
import urllib.error
import urllib.parse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

VERSION="0.1.26"
MANIFEST_URL="https://webbase-x.github.io/xstage/downloads/song-studio-pro-latest.json"
RAW_MANIFEST_URL="https://raw.githubusercontent.com/webbase-x/xstage/main/downloads/song-studio-pro-latest.json"
RELEASE=re.compile(
    r"^https://github\\.com/webbase-x/xstage/releases/download/"
    r"song-studio-pro-v(\\d+\\.\\d+\\.\\d+)-preview/"
    r"(X-Stage-Song-Studio-Pro-v\\1-preview\\.exe)$")
MAX_FILE=600*1024*1024
CHUNK=1024*1024
DOWNLOAD_RETRIES=5
DOWNLOAD_HOSTS={"github.com","release-assets.githubusercontent.com",
                "objects.githubusercontent.com","github-releases.githubusercontent.com"}


def version_tuple(s):
    if not re.fullmatch(r"\\d+\\.\\d+\\.\\d+",str(s)):
        raise ValueError("เลขรุ่นไม่ถูกต้อง")
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


def _read_feed(url):
    # The main and fallback feeds are both published by webbase-x/xstage.
    # Ask both sources to avoid a stale GitHub Pages CDN response.
    source=urllib.parse.urlsplit(url)
    req=urllib.request.Request(
        url+("?r="+str(int(time.time()*1000))),
        headers={"User-Agent":"XStageSongStudioPro/"+VERSION,
                 "Accept":"application/json","Cache-Control":"no-cache"})
    with urllib.request.urlopen(req,timeout=15) as response:
        returned=urllib.parse.urlsplit(response.geturl())
        if returned.scheme!="https" or returned.hostname!=source.hostname:
            raise ValueError("เว็บไซต์แจ้งอัปเดตเปลี่ยนไปยังปลายทางที่ไม่อนุญาต")
        raw=response.read(16385)
    if len(raw)>16384:
        raise ValueError("ไฟล์แจ้งอัปเดตมีขนาดผิดปกติ")
    target=validate(json.loads(raw.decode("utf-8-sig")))
    target["feed"]=source.hostname
    return target


def check():
    candidates=[]
    errors=[]
    for url in (MANIFEST_URL,RAW_MANIFEST_URL):
        try:
            candidates.append(_read_feed(url))
        except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as exc:
            errors.append(str(exc)[:180])
    if not candidates:
        raise OSError("เชื่อมต่อข้อมูลรุ่นล่าสุดไม่ได้ (Pages และ GitHub): "+
                      " | ".join(errors))
    # Direct upgrade: choose the HIGHEST published verified EXE version,
    # not the next version after the one currently installed.
    target=max(candidates,key=lambda row:version_tuple(row["version"]))
    target["current_version"]=VERSION
    target["newer"]=version_tuple(target["version"])>version_tuple(VERSION)
    return target


def ready_file(workspace):
    directory=_staged_dir(workspace)
    pointer=directory/"ready.json"
    if not pointer.is_file():
        return None
    try:
        ready=json.loads(pointer.read_text(encoding="utf-8"))
        target=validate(ready)
        p=directory/target["filename"]
        if not p.is_file() or p.stat().st_size<1024*1024:
            return None
        with p.open("rb") as stream:
            digest=hashlib.file_digest(stream,"sha256").hexdigest()
        if digest!=target["sha256"]:
            return None
        return {**target,"path":str(p)}
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError):
        return None


def _write_ready(root,target):
    payload={"name":"X-Stage Song Studio Pro","available":True,
             "version":target["version"],"download_url":target["url"],
             "sha256":target["sha256"]}
    temp=root/"ready.json.tmp"
    temp.write_text(json.dumps(payload,ensure_ascii=False),encoding="utf-8")
    os.replace(temp,root/"ready.json")


def _hash_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def _emit(progress,received,total,message,attempt):
    if progress:
        progress({"done":received,"total":total,
                  "downloaded_bytes":received,"attempt":attempt,
                  "max_attempts":DOWNLOAD_RETRIES},message)


def download(workspace,info,progress=None,cancel=None):
    """Download the newest verified release in one jump, with safe HTTP resume.

    A partial is NEVER executed. Retries preserve verified source identity via
    .partial.json, validate HTTP Range responses, and hash all final bytes.
    """
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
    marker=root/(target["filename"]+".partial.json")
    identity={"url":target["url"],"sha256":target["sha256"],
              "version":target["version"]}
    try:
        remembered=json.loads(marker.read_text(encoding="utf-8"))
    except (OSError,ValueError,json.JSONDecodeError):
        remembered=None
    if remembered!=identity:
        partial.unlink(missing_ok=True)
    marker.write_text(json.dumps(identity,ensure_ascii=False),encoding="utf-8")

    if destination.is_file() and destination.stat().st_size>=1024*1024:
        if _hash_file(destination)==target["sha256"]:
            _write_ready(root,target)
            return {**target,"path":str(destination)}

    last_error=None
    for attempt in range(1,DOWNLOAD_RETRIES+1):
        if cancel and cancel.is_set():
            raise InterruptedError("ผู้ใช้หยุดการดาวน์โหลด ไฟล์ที่รับไว้ยังสามารถดาวน์โหลดต่อได้")
        offset=partial.stat().st_size if partial.is_file() else 0
        if offset>MAX_FILE:
            partial.unlink(missing_ok=True)
            offset=0
        headers={"User-Agent":"XStageSongStudioPro/"+VERSION,
                 "Accept":"application/octet-stream",
                 "Cache-Control":"no-cache"}
        if offset:
            headers["Range"]="bytes="+str(offset)+"-"
        req=urllib.request.Request(target["url"],headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=45) as response:
                final=urllib.parse.urlsplit(response.geturl())
                if final.scheme!="https" or final.hostname not in DOWNLOAD_HOSTS:
                    raise ValueError("ปลายทางดาวน์โหลดไม่ใช่ GitHub HTTPS ที่อนุญาต")
                status=getattr(response,"status",response.getcode())
                length=int(response.headers.get("Content-Length") or 0)
                if length<0 or length>MAX_FILE:
                    raise ValueError("ขนาดข้อมูลจาก GitHub ไม่ถูกต้อง")
                if offset and status==206:
                    cr=response.headers.get("Content-Range","")
                    match=re.fullmatch(r"bytes (\\d+)-(\\d+)/(\\d+|\\*)",cr)
                    if not match or int(match.group(1))!=offset:
                        raise ValueError("GitHub ตอบช่วงข้อมูลไม่ตรงกับไฟล์ที่โหลดค้าง")
                    total=int(match.group(3)) if match.group(3)!="*" else 0
                    if total and (total>MAX_FILE or
                                  int(match.group(2))>=total or
                                  (length and offset+length>total)):
                        raise ValueError("ข้อมูลแบ่งช่วงดาวน์โหลดมีขนาดไม่ถูกต้อง")
                elif status==200:
                    # No Range support on this redirect: restart with this
                    # response, rather than append duplicated EXE bytes.
                    offset=0
                    total=length
                else:
                    raise ValueError("GitHub ไม่รองรับการดาวน์โหลดต่อในรอบนี้")
                if total>MAX_FILE:
                    raise ValueError("ไฟล์อัปเดตเกินขนาดที่อนุญาต")
                if total and shutil.disk_usage(root).free<max(0,total-offset)+16*1024*1024:
                    raise OSError("พื้นที่ดิสก์ไม่พอสำหรับดาวน์โหลด EXE รุ่นล่าสุด")
                received=offset
                _emit(progress,received,total,
                      "ดาวน์โหลด v"+target["version"]+" · รอบ "+str(attempt)+
                      "/"+str(DOWNLOAD_RETRIES)+
                      (" · ต่อจากไฟล์เดิม" if offset else ""),attempt)
                with partial.open("ab" if offset else "wb") as output:
                    next_report=received+4*1024*1024
                    while True:
                        if cancel and cancel.is_set():
                            raise InterruptedError("ยกเลิกการดาวน์โหลด โดยเก็บไฟล์ไว้ทำต่อ")
                        chunk=response.read(CHUNK)
                        if not chunk:
                            break
                        output.write(chunk)
                        received+=len(chunk)
                        if received>MAX_FILE:
                            raise ValueError("ไฟล์อัปเดตใหญ่เกินขนาดสูงสุด")
                        if received>=next_report:
                            _emit(progress,received,total,
                                  "กำลังดาวน์โหลดรุ่นล่าสุด "+target["version"],attempt)
                            next_report=received+4*1024*1024
                if total and received!=total:
                    raise OSError("การเชื่อมต่อขาดช่วง ได้รับ "+
                                  str(received)+" จาก "+str(total)+" ไบต์")
            if received<1024*1024:
                raise OSError("ดาวน์โหลดได้ไฟล์เล็กผิดปกติ")
            _emit(progress,received,received,"กำลังตรวจ SHA-256 ของไฟล์ EXE",attempt)
            found=_hash_file(partial)
            if found!=target["sha256"]:
                # A corrupt or HTTP-intercepted transfer may not be resumed.
                partial.unlink(missing_ok=True)
                raise OSError("SHA-256 ไม่ตรงกับไฟล์ GitHub (ได้ "+
                              found[:12]+" คาดหวัง "+target["sha256"][:12]+")")
            for swap_attempt in range(4):
                try:
                    os.replace(partial,destination)
                    break
                except PermissionError:
                    if swap_attempt==3:
                        raise
                    time.sleep(.5)
            marker.unlink(missing_ok=True)
            _write_ready(root,target)
            _emit(progress,received,received,
                  "ดาวน์โหลดรุ่น "+target["version"]+" และตรวจ SHA-256 ผ่าน",attempt)
            return {**target,"path":str(destination)}
        except InterruptedError:
            raise
        except ValueError:
            # Invalid HTTPS source or Range metadata is a safety failure.
            # Do not silently retry with unverified bytes.
            raise
        except (OSError,urllib.error.URLError,TimeoutError,
                ConnectionError,http.client.IncompleteRead) as exc:
            last_error=exc
            if isinstance(exc,urllib.error.HTTPError):
                if exc.code in (400,401,403,404,410):
                    raise OSError("GitHub ตอบ HTTP "+str(exc.code)+
                                  " · ลองดาวน์โหลด EXE โดยตรงจากหน้า Release") from exc
            if attempt==DOWNLOAD_RETRIES:
                break
            _emit(progress,partial.stat().st_size if partial.is_file() else 0,
                  0,"การเชื่อมต่อขาดช่วง ("+str(exc)[:120]+
                  ") · ลองอีกครั้ง "+str(attempt+1)+"/"+
                  str(DOWNLOAD_RETRIES),attempt)
            time.sleep(min(1.5*attempt,5))
    raise OSError("ดาวน์โหลดรุ่น "+target["version"]+" ไม่สำเร็จหลังลอง "+
                  str(DOWNLOAD_RETRIES)+" ครั้ง: "+str(last_error)[:240]+
                  " · เปิด Log หรือใช้ลิงก์ EXE ทางตรง")



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
