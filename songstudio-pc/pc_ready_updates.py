"""Verified Song Studio PC Ready updates, safely installed side-by-side."""
from __future__ import annotations
import hashlib
import json
import re
import urllib.request
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

METADATA_URL = ("https://raw.githubusercontent.com/webbase-x/xstage/"
                "main/downloads/song-studio-latest.json")
RELEASE_PREFIX = "https://github.com/webbase-x/xstage/releases/download/"
NAME = re.compile(r"^X-Stage-Song-Studio-PC-Ready-v(\d+\.\d+\.\d+)-build(\d+)\.zip$")
SHA = re.compile(r"^[0-9a-f]{64}$")
MAX_SIZE = 2 * 1024 ** 3


def _version(text):
    try:
        return tuple(int(n) for n in str(text).split("."))
    except (TypeError, ValueError):
        return (0,)


def _metadata():
    req = urllib.request.Request(METADATA_URL, headers={
        "User-Agent": "X-Stage-Song-Studio-PC-Ready-Updater/1"})
    with urllib.request.urlopen(req, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError("GitHub ไม่คืนข้อมูลเวอร์ชัน")
        payload = response.read(32769)
    if len(payload) > 32768:
        raise ValueError("ข้อมูลอัปเดตมีขนาดผิดปกติ")
    doc = json.loads(payload.decode("utf-8-sig"))
    if not isinstance(doc, dict):
        raise ValueError("รูปแบบข้อมูลอัปเดตไม่ถูกต้อง")
    filename = doc.get("archive_file", "")
    match = NAME.fullmatch(filename) if isinstance(filename, str) else None
    if (doc.get("channel") != "pc-ready" or
            doc.get("platform") != "windows-x64" or
            doc.get("package_type") != "portable_zip" or
            doc.get("available") is not True or not match or
            doc.get("version") != match.group(1) or
            type(doc.get("build")) is not int or
            doc["build"] != int(match.group(2)) or
            not isinstance(doc.get("sha256"), str) or
            not SHA.fullmatch(doc["sha256"]) or
            not isinstance(doc.get("download_url"), str) or
            doc["download_url"] != RELEASE_PREFIX +
                "song-studio-pc-ready-v" + match.group(1) +
                "-build" + match.group(2) + "/" + filename):
        raise ValueError("ข้อมูลรุ่นใหม่ไม่ตรงกับไฟล์ Ready ที่เผยแพร่")
    return doc


def _newer(doc, version, build):
    return (_version(doc["version"]), doc["build"]) > (
        _version(version), int(build) if str(build).isdigit() else 0)


def check(version, build):
    doc = _metadata()
    available = _newer(doc, version, build)
    return {"update": available, "version": doc["version"], "build": doc["build"],
            "status": "available" if available else "current",
            "url": doc["download_url"] if available else "",
            "message": ("พบรุ่นใหม่ v" + doc["version"] + " Build " + str(doc["build"]) +
                        " · สามารถดาวน์โหลด ZIP ที่ตรวจ SHA-256 ได้" if available else
                        "ใช้รุ่นล่าสุดที่เผยแพร่แล้ว v" + doc["version"] +
                        " Build " + str(doc["build"]))}


def download(folder, version, build, *, cancelled=None, on_progress=None):
    doc = _metadata()
    if not _newer(doc, version, build):
        return {"update": False, "message": "ไม่มีรุ่นที่ใหม่กว่าให้ดาวน์โหลด"}
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / doc["archive_file"]
    expected = doc["sha256"]
    if output.is_file():
        with output.open("rb") as existing:
            digest = hashlib.file_digest(existing, "sha256").hexdigest()
        if digest == expected:
            return {"update": True, "version": doc["version"], "path": str(output),
                    "message": "พบ ZIP ที่ตรวจ SHA-256 แล้ว: " + str(output)}
    temporary = output.with_suffix(".zip.partial")
    try:
        req = urllib.request.Request(doc["download_url"], headers={
            "User-Agent": "X-Stage-Song-Studio-PC-Ready-Updater/1"})
        with urllib.request.urlopen(req, timeout=45) as response:
            if response.status != 200 or response.geturl()[:8] != "https://":
                raise RuntimeError("ไม่สามารถดาวน์โหลด ZIP ผ่าน HTTPS")
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_SIZE:
                raise ValueError("ไฟล์อัปเดตใหญ่ผิดปกติ")
            sha = hashlib.sha256()
            done = 0
            with temporary.open("wb") as out:
                while True:
                    if cancelled is not None and cancelled.is_set():
                        raise RuntimeError("ยกเลิกการดาวน์โหลดแล้ว")
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    done += len(block)
                    if done > MAX_SIZE:
                        raise ValueError("ไฟล์อัปเดตใหญ่ผิดปกติ")
                    sha.update(block)
                    out.write(block)
                    if on_progress:
                        on_progress(done, int(length or 0))
        if sha.hexdigest() != expected:
            raise ValueError("SHA-256 ของไฟล์ดาวน์โหลดไม่ตรง ห้ามใช้ ZIP นี้")
        temporary.replace(output)
        return {"update": True, "version": doc["version"], "build": doc["build"],
                "path": str(output), "sha256": expected,
                "message": ("ดาวน์โหลดและตรวจ SHA-256 ผ่านแล้ว: " + str(output) +
                            " · ปิดโปรแกรมและแตก ZIP รุ่นใหม่แยกโฟลเดอร์ก่อนเปิดใช้")}
    finally:
        temporary.unlink(missing_ok=True)

# Download bytes are authenticated against the exact release checksum before
# any archive member is inspected. Never replace the current running bundle.
MAX_UNPACKED = 5 * 1024 ** 3
MAX_MEMBERS = 18000
MANDATORY = (
    ".engine-ready-manifest.json",
    "Start-Song-Studio-Ready.ps1",
    "Start-Song-Studio.cmd",
    "engine.py",
    "pc_ready_updates.py",
    "studio/index.html",
    "studio/app.js",
    ".runtime/python/python.exe",
    ".runtime/python/pythonw.exe",
    ".runtime/tools/ffmpeg.exe",
    ".runtime/soundfonts/GeneralUser-GS.sf2",
    ".runtime/models/htdemucs_fp16weights.onnx",
)

def _inspect_archive(archive, expected_root):
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
        if not infos or len(infos) > MAX_MEMBERS:
            raise ValueError("จำนวนไฟล์ ZIP อัปเดตผิดปกติ")
        total = 0
        files = set()
        for entry in infos:
            p = entry.filename.replace("\\", "/")
            parts = p.rstrip("/").split("/")
            if (not parts or parts[0] != expected_root or
                any(part in ("", ".", "..") for part in parts) or
                p.startswith("/") or ":" in p or
                (entry.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError("พบเส้นทางไฟล์ไม่ปลอดภัยใน ZIP")
            if entry.flag_bits & 1:
                raise ValueError("ZIP ต้องไม่เข้ารหัสไฟล์ภายใน")
            total += entry.file_size
            if total > MAX_UNPACKED:
                raise ValueError("ขนาดไฟล์หลังแตก ZIP มากเกินกำหนด")
            if not entry.is_dir():
                if p in files:
                    raise ValueError("ZIP มีรายการไฟล์ซ้ำ")
                files.add(p)
        if not all(expected_root + "/" + name in files for name in MANDATORY):
            raise ValueError("ZIP รุ่นใหม่ขาดไฟล์ที่จำเป็น")
    return total

def _verify_extracted(root):
    manifest = root / ".engine-ready-manifest.json"
    doc = json.loads(manifest.read_text(encoding="utf-8-sig"))
    if doc.get("bundle_type") != "ready-offline" or doc.get("platform") != "windows-x64":
        raise ValueError("Manifest ไม่ใช่ PC Ready Offline")
    for entry in doc.get("files", []):
        name = entry.get("path", "")
        sha = entry.get("sha256", "")
        parts = name.replace("\\", "/").split("/")
        if (not parts or any(x in ("", ".", "..") for x in parts)
                or not SHA.fullmatch(str(sha))):
            raise ValueError("Manifest มีรายการไฟล์ไม่ปลอดภัย")
        item = root.joinpath(*parts)
        if not item.is_file() or not item.resolve().is_relative_to(root.resolve()):
            raise ValueError("ไฟล์ใน Manifest ไม่ครบ: " + name)
        with item.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if digest != sha:
            raise ValueError("ไฟล์ติดตั้งตรวจ SHA-256 ไม่ผ่าน: " + name)
    if not doc.get("files"):
        raise ValueError("Manifest ไม่มีรายการตรวจสอบไฟล์")
    return doc

def install(archive, current_root, *, cancelled=None, on_progress=None,
            launch=True):
    """Install a verified Ready ZIP into a sibling version folder.

    Caller MUST pass the archive returned by download(); this function
    independently re-checks release metadata and archive SHA. The running
    directory is never modified. Existing destination is never overwritten.
    """
    if os.name != "nt" and launch:
        raise RuntimeError("การเปิดโปรแกรมหลังติดตั้งรองรับ Windows เท่านั้น")
    doc = _metadata()
    archive = Path(archive).resolve(strict=True)
    current = Path(current_root).resolve(strict=True)
    if not (current / ".engine-ready-manifest.json").is_file():
        raise ValueError("ติดตั้งอัตโนมัติได้เฉพาะ PC Ready Offline")
    if archive.name != doc["archive_file"]:
        raise ValueError("ชื่อไฟล์รุ่นใหม่ไม่ตรงกับข้อมูลเผยแพร่")
    with archive.open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != doc["sha256"]:
            raise ValueError("ZIP ตรวจ SHA-256 ไม่ผ่าน")
    folder_name = archive.stem
    _inspect_archive(archive, folder_name)
    target = current.parent / folder_name
    if target.resolve() == current:
        raise ValueError("ไม่อนุญาตให้ติดตั้งทับรุ่นที่กำลังใช้งาน")
    if target.exists():
        raise FileExistsError("พบโฟลเดอร์รุ่นใหม่อยู่แล้ว กรุณาตรวจสอบ: " + str(target))
    if cancelled is not None and cancelled.is_set():
        raise RuntimeError("ยกเลิกการติดตั้งแล้ว")
    # Stage next to the final destination so the final rename is atomic.
    with tempfile.TemporaryDirectory(prefix=".xstage-update-",dir=current.parent) as staging:
        stage = Path(staging)
        with zipfile.ZipFile(archive) as zf:
            for i, item in enumerate(zf.infolist()):
                if cancelled is not None and cancelled.is_set():
                    raise RuntimeError("ยกเลิกการติดตั้งแล้ว")
                zf.extract(item, stage)
                if on_progress and i % 150 == 0:
                    on_progress(i + 1, len(zf.infolist()))
        extracted = stage / folder_name
        info = _verify_extracted(extracted)
        if info.get("version") != doc["version"] or info.get("build") != doc["build"]:
            raise ValueError("เลขรุ่นใน ZIP ไม่ตรงกับข้อมูลเผยแพร่")
        extracted.rename(target)
    if launch:
        # The new launcher's signal is written only AFTER it verifies the offline
        # bundle and confirms the new Engine remains alive. Never terminate
        # the old Engine on a mere PowerShell process-spawn success.
        signal = target.parent / (".xstage-ready-" + os.urandom(12).hex() + ".signal")
        try:
            import time
            proc = subprocess.Popen([
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(target / "Start-Song-Studio-Ready.ps1"),
                "-ReadySignal", str(signal)
            ], cwd=str(target),
               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
               stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if cancelled is not None and cancelled.is_set():
                    raise RuntimeError("ยกเลิกการสลับรุ่นแล้ว · รุ่นเก่ายังเปิดอยู่")
                if signal.exists():
                    contents = signal.read_text(encoding="utf-8").strip()
                    if contents.startswith("READY:") and contents[6:].isdigit():
                        break
                    raise RuntimeError("ข้อมูลยืนยันการเปิดรุ่นใหม่ไม่ถูกต้อง")
                if proc.poll() is not None:
                    raise RuntimeError("เปิดรุ่นใหม่ไม่สำเร็จ · ดู start-ready.log ในโฟลเดอร์รุ่นใหม่")
                time.sleep(0.25)
            else:
                raise RuntimeError("รุ่นใหม่ไม่ยืนยันการเปิดภายในเวลาที่กำหนด · รุ่นเก่ายังเปิดอยู่")
        except OSError as exc:
            raise RuntimeError("ติดตั้งแล้วแต่เปิดรุ่นใหม่ไม่สำเร็จ: " + str(target)) from exc
        finally:
            signal.unlink(missing_ok=True)
        _retarget_existing_shortcut(current, target)
    return {"installed": True, "version": doc["version"], "build": doc["build"],
            "path": str(target), "launched": bool(launch),
            "message": "ติดตั้งรุ่นใหม่เสร็จแล้ว: " + str(target)}

def _retarget_existing_shortcut(current, target):
    """Modify only the existing desktop shortcut when it points at this bundle."""
    if os.name != "nt":
        return
    # PowerShell script is invoked with positional args, never interpolated paths.
    ps = r"""
$old=$args[0];$new=$args[1]
$desktop=[Environment]::GetFolderPath('DesktopDirectory')
$link=Join-Path $desktop 'X-Stage Song Studio PC.lnk'
if(!(Test-Path -LiteralPath $link)){exit 0}
$w=New-Object -ComObject WScript.Shell
$s=$w.CreateShortcut($link)
$expected=Join-Path $old 'Start-Song-Studio.cmd'
if([string]::Equals($s.TargetPath,$expected,[StringComparison]::OrdinalIgnoreCase)){
  $s.TargetPath=Join-Path $new 'Start-Song-Studio.cmd'
  $s.WorkingDirectory=$new
  $s.IconLocation=(Join-Path $new 'studio\\app-icon.ico')+',0'
  $s.Save()
}
"""
    try:
        subprocess.run(["powershell.exe","-NoProfile","-Command",ps,
                        str(current),str(target)],timeout=20,
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                       creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    except (OSError, subprocess.TimeoutExpired):
        pass  # Never roll back an installed release due to optional shortcut.
