"""Authorized direct HTTPS song downloader for X-Stage Song Studio Pro.

Downloads to the user's Downloads directory (outside the SQLite workspace),
preserves original bytes, and indexes exactly that one file. This module does
not scrape platforms, bypass access controls, or handle private Drive links.
"""
from __future__ import annotations

import hashlib
import ipaddress
import os
from pathlib import Path
import secrets
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

import plus_core as core

MAX_BYTES=8*1024**3
ALLOWED_EXT=frozenset(core.MEDIA_EXT)
BLOCK_SIZE=1024*1024


def validate_remote_url(url):
    if not isinstance(url,str) or len(url)>4096:
        raise ValueError("ลิงก์ไฟล์เพลงยาวเกินไป")
    try:
        parts=urllib.parse.urlsplit(url.strip())
        port=parts.port
    except ValueError as exc:
        raise ValueError("รูปแบบ URL ไม่ถูกต้อง") from exc
    if (parts.scheme.lower()!="https" or not parts.hostname
            or parts.username is not None or parts.password is not None
            or port not in (None,443)
            or not parts.path or any(ord(x)<32 for x in url)):
        raise ValueError("รองรับเฉพาะลิงก์ HTTPS ของไฟล์เพลงโดยตรง")
    host=parts.hostname.rstrip(".")
    if not host or host.lower() in ("localhost","localhost.localdomain"):
        raise ValueError("ไม่อนุญาตลิงก์เครือข่ายภายในเครื่อง")
    # Numeric IP literals must be checked directly, not via a resolver that
    # may rebind or return an unrelated address.
    try:
        literal=ipaddress.ip_address(host)
    except ValueError:
        literal=None
    if literal is not None and not literal.is_global:
        raise ValueError("ไม่อนุญาตลิงก์เครือข่ายภายในเครื่อง")
    try:
        endpoints=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("ไม่สามารถตรวจสอบที่อยู่เซิร์ฟเวอร์") from exc
    if not endpoints or any(
            not ipaddress.ip_address(addr[4][0]).is_global
            for addr in endpoints):
        raise ValueError("ไม่อนุญาตลิงก์เครือข่ายภายในหรือที่อยู่ไม่ใช่สาธารณะ")
    return parts


def safe_filename(url):
    parts=urllib.parse.urlsplit(url)
    filename=Path(urllib.parse.unquote(parts.path)).name
    if (not filename or filename in (".","..") or
            filename.startswith(".") or any(ord(x)<32 for x in filename)
            or len(filename)>190):
        raise ValueError("ลิงก์ไม่มีชื่อไฟล์เพลงที่ถูกต้อง")
    if Path(filename).suffix.lower() not in ALLOWED_EXT:
        raise ValueError("ลิงก์ต้องลงท้ายด้วย .mid/.midi/.kar หรือไฟล์เพลงและวิดีโอที่รองรับ")
    return filename


class PublicHttpsRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        validate_remote_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def download_and_import(workspace,url,progress=None,cancel=None,
                        destination=None,opener=None):
    """Download one direct song file and register it without scanning others.

    Unlike copying into the SQLite workspace, keeping the source in Downloads
    lets the legacy verified-source resolver find it for later XMID exports.
    """
    validate_remote_url(url)
    filename=safe_filename(url)
    workspace=Path(workspace).expanduser().resolve()
    base=Path(destination).expanduser().resolve() if destination else (
        Path.home()/"Downloads"/"XStageSongStudioPro").resolve()
    if base==workspace or base.is_relative_to(workspace) or workspace.is_relative_to(base):
        raise ValueError("โฟลเดอร์ดาวน์โหลดต้องแยกจากคลัง SQLite")
    folder=base/secrets.token_hex(8)
    folder.mkdir(parents=True,exist_ok=False)
    target=folder/filename
    temp=folder/(filename+".part")
    transfer=opener or urllib.request.build_opener(PublicHttpsRedirect())
    started=time.monotonic()
    downloaded=0
    sha=hashlib.sha256()
    try:
        req=urllib.request.Request(url,headers={
            "User-Agent":"XStageSongStudioPro/1.0",
            "Accept":"application/octet-stream"})
        try:
            response=transfer.open(req,timeout=25)
        except urllib.error.HTTPError as exc:
            raise ValueError("เซิร์ฟเวอร์ตอบ HTTP "+str(exc.code)) from exc
        with response as source:
            validate_remote_url(source.geturl())
            ctype=source.headers.get("Content-Type","").lower()
            if "text/html" in ctype or "application/json" in ctype:
                raise ValueError("ลิงก์ส่งหน้าเว็บหรือ JSON ไม่ใช่ไฟล์เพลงโดยตรง")
            length=source.headers.get("Content-Length")
            expected=int(length) if length and length.isdecimal() else 0
            if expected>MAX_BYTES:
                raise ValueError("ไฟล์ดาวน์โหลดใหญ่เกินขีดจำกัด 8 GiB")
            last_report=0.0
            with temp.open("wb") as output:
                while True:
                    if cancel is not None and cancel.is_set():
                        raise RuntimeError("ผู้ใช้ยกเลิกการดาวน์โหลด")
                    chunk=source.read(BLOCK_SIZE)
                    if not chunk:
                        break
                    downloaded+=len(chunk)
                    if downloaded>MAX_BYTES:
                        raise ValueError("ไฟล์ดาวน์โหลดใหญ่เกินขีดจำกัด 8 GiB")
                    sha.update(chunk)
                    output.write(chunk)
                    now=time.monotonic()
                    if progress and (now-last_report>.25 or downloaded==expected):
                        progress({"downloaded_bytes":downloaded,"total":expected},
                                 "ดาวน์โหลด "+filename+" · "+str(downloaded//1048576)+" MB")
                        last_report=now
                output.flush()
                os.fsync(output.fileno())
            if expected and downloaded!=expected:
                raise ValueError("ดาวน์โหลดไฟล์ไม่ครบตามขนาดที่เซิร์ฟเวอร์แจ้ง")
            if downloaded==0:
                raise ValueError("ไฟล์ดาวน์โหลดว่าง")
        os.replace(temp,target)
        if progress:
            progress({"downloaded_bytes":downloaded,"total":downloaded,
                      "phase":"import"},"ดาวน์โหลดเสร็จ · กำลังนำเข้า SQLite")
        def import_progress(info,msg):
            if progress:
                progress({**info,"downloaded_bytes":downloaded,
                          "total":downloaded,"phase":"import"},msg)
        imported=core.import_folder(workspace,str(folder),import_progress,cancel,
                                    selected_file=str(target))
        return {"download_path":str(target),"sha256":sha.hexdigest(),
                "downloaded_bytes":downloaded,"import":imported,
                "elapsed_seconds":round(time.monotonic()-started,3)}
    finally:
        temp.unlink(missing_ok=True)
        if not target.exists():
            try: folder.rmdir()
            except OSError: pass
