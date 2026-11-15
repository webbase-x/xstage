"""Checked Song Studio PC Ready release channel; never execute downloaded ZIP."""
from __future__ import annotations
import hashlib
import json
import re
import urllib.request
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
