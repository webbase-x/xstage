"""Verified Windows release checks. No song library, queue or settings are touched.

Stable and verified unsigned preview channels are separate. Preview installation
always requires explicit user confirmation. UI/network work stays off playback.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
from tkinter import messagebox
from urllib.request import Request, urlopen

FEED = 'https://webbase-x.github.io/xstage/downloads/windows-pc-latest.json'
PREVIEW_FEED = 'https://webbase-x.github.io/xstage/downloads/windows-pc-preview-latest.json'
DOWNLOADS = 'https://webbase-x.github.io/xstage/downloads/'
FILE_PATTERN = re.compile(r'(?:X-StageKaraoke\.exe|X-Stage-Karaoke-PC-Windows-v[0-9.]+-build[0-9]+\.(?:exe|msi))\Z')
HEX_PATTERN = re.compile(r'[0-9a-fA-F]{64}\Z')
MAX_INSTALLER_BYTES = 300 * 1024 * 1024


def version_tuple(value):
    text = str(value).lstrip('vV')
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,3}', text):
        raise ValueError('Invalid Windows application version')
    parts = text.split('.')
    return tuple(int(n) for n in (parts + ['0'] * (4 - len(parts))))


def validate_manifest(info, current, current_build=0):
    if not isinstance(info, dict) or info.get('available') is not True:
        return None
    latest = str(info.get('version', ''))
    latest_parts = version_tuple(latest)
    current_parts = version_tuple(current)
    latest_build = info.get('build', 0)
    if not isinstance(latest_build, int) or latest_build < 0:
        raise ValueError('Invalid Windows build metadata')
    if latest_parts < current_parts or (latest_parts == current_parts and latest_build <= current_build):
        return None
    name = str(info.get('installer_file', ''))
    digest = str(info.get('sha256', ''))
    if not FILE_PATTERN.fullmatch(name) or not HEX_PATTERN.fullmatch(digest):
        raise ValueError('ข้อมูลไฟล์ติดตั้งหรือ SHA-256 ไม่ถูกต้อง')
    return {'version': latest, 'name': name, 'sha256': digest.lower()}


def _read_feed(url):
    request = Request(url, headers={'Cache-Control': 'no-cache', 'User-Agent': 'XStageWindowsUpdater/1'})
    with urlopen(request, timeout=12) as response:
        data = response.read(32769)
    if len(data) > 32768:
        raise ValueError('ข้อมูลเวอร์ชันมีขนาดผิดปกติ')
    return json.loads(data.decode('utf-8'))


def check_release(current, current_build=None):
    if current_build is None:
        from . import __build__
        current_build = __build__
    stable = validate_manifest(_read_feed(FEED), current, current_build)
    if stable:
        return dict(stable, channel='stable')
    preview = _read_feed(PREVIEW_FEED)
    if not isinstance(preview, dict) or preview.get('available') is not True:
        return None
    if preview.get('channel') != 'preview' or preview.get('platform') != 'windows-x64':
        raise ValueError('ข้อมูลช่องทาง Windows Preview ไม่ถูกต้อง')
    update = validate_manifest(preview, current, current_build)
    if update is None:
        return None
    if preview.get('download_url') != DOWNLOADS + update['name']:
        raise ValueError('ตำแหน่งดาวน์โหลด Preview ไม่ถูกต้อง')
    return dict(update, channel='preview')


def fetch_verified_installer(update, progress=None):
    if not FILE_PATTERN.fullmatch(update['name']) or not HEX_PATTERN.fullmatch(update['sha256']):
        raise ValueError('ข้อมูลตัวติดตั้งไม่ถูกต้อง')
    location = Path(tempfile.mkdtemp(prefix='XStageUpdate-'))
    destination = location / update['name']
    partial = destination.with_suffix(destination.suffix + '.part')
    digest = hashlib.sha256()
    count = 0
    try:
        request = Request(DOWNLOADS + update['name'], headers={'User-Agent': 'XStageWindowsUpdater/1'})
        with urlopen(request, timeout=45) as remote, partial.open('wb') as local:
            raw_total = remote.headers.get('Content-Length', '')
            total = int(raw_total) if str(raw_total).isdigit() else 0
            if total > MAX_INSTALLER_BYTES:
                raise ValueError('ไฟล์ติดตั้งมีขนาดเกินขีดจำกัด')
            while chunk := remote.read(1024 * 1024):
                count += len(chunk)
                if count > MAX_INSTALLER_BYTES:
                    raise ValueError('ไฟล์ติดตั้งมีขนาดเกินขีดจำกัด')
                digest.update(chunk)
                local.write(chunk)
                if progress:
                    progress(count, total)
        if digest.hexdigest() != update['sha256']:
            raise ValueError('SHA-256 ของตัวติดตั้งไม่ตรงกับรุ่นที่ประกาศ')
        os.replace(partial, destination)
        return destination
    finally:
        if partial.exists():
            partial.unlink()
        if not destination.exists():
            try:
                location.rmdir()
            except OSError:
                pass


def launch_installer(path):
    path = Path(path)
    if path.suffix.lower() == '.msi':
        subprocess.Popen(['msiexec.exe', '/i', str(path)], close_fds=True)
    else:
        subprocess.Popen([str(path)], close_fds=True)


def check_in_background(app, current_version, interactive=False):
    """Use after() only for notifications; installer launch requires explicit confirmation."""
    if getattr(app, '_xstage_update_check_running', False) or getattr(app, '_xstage_update_install_running', False):
        return
    app._xstage_update_check_running = True

    def on_ui(callback):
        try:
            app.after(0, callback)
        except (RuntimeError, AttributeError):
            pass

    def check_worker():
        try:
            update = check_release(current_version)
        except Exception as exc:
            detail = str(exc)
            if interactive:
                on_ui(lambda: messagebox.showwarning('ตรวจอัปเดต X-Stage',
                    'ไม่สามารถตรวจสอบรุ่นใหม่ได้\n' + detail, parent=app))
            return
        finally:
            on_ui(lambda: setattr(app, '_xstage_update_check_running', False))
        if update is None:
            if interactive:
                on_ui(lambda: messagebox.showinfo('ตรวจอัปเดต X-Stage',
                    f'X-Stage Karaoke PC v{current_version}: ยังไม่มีรุ่นใหม่ที่ผ่านการตรวจสอบและพร้อมติดตั้ง', parent=app))
            return

        def ask_update():
            preview = update.get('channel') == 'preview'
            warning = ('\nรุ่น Preview ผ่าน CI แต่ไม่มีลายเซ็น Authenticode อาจมี SmartScreen เตือน\n' if preview else '\n')
            if getattr(app, '_xstage_update_install_running', False):
                return
            if not messagebox.askyesno('มี X-Stage รุ่นใหม่',
                f"มี X-Stage Karaoke PC v{update['version']} พร้อมอัปเดต\n"
                + warning + 'ต้องการดาวน์โหลดและเปิดตัวติดตั้งตอนนี้หรือไม่?\n'
                'ระบบจะตรวจสอบ SHA-256 ก่อนเปิดตัวติดตั้ง และไม่ลบไฟล์เพลงของคุณ', parent=app, default='no'):
                return
            app._xstage_update_install_running = True
            threading.Thread(target=install_worker, args=(update,), daemon=True, name='XStageInstallerFetch').start()
        on_ui(ask_update)

    def install_worker(update):
        last_percent = -1
        def progress(done, total):
            nonlocal last_percent
            percent = min(100, int(done * 100 / total)) if total else done // (1024 * 1024)
            if percent == last_percent:
                return
            last_percent = percent
            label = f'ดาวน์โหลดอัปเดต {percent}%' if total else f'ดาวน์โหลดอัปเดต {percent} MB'
            def show():
                status = getattr(app, 'status_var', None)
                if status is not None:
                    status.set(label)
            on_ui(show)
        try:
            path = fetch_verified_installer(update, progress)
        except Exception as exc:
            message = str(exc)
            on_ui(lambda: setattr(app, '_xstage_update_install_running', False))
            on_ui(lambda: messagebox.showerror('อัปเดต X-Stage ไม่สำเร็จ', message, parent=app))
            return

        def confirm_install():
            app._xstage_update_install_running = False
            if getattr(app, 'scanning', False) or getattr(app, '_shared_build_busy', False):
                messagebox.showinfo('ตรวจอัปเดต X-Stage', 'กรุณาหยุดงานสร้างฐานเพลงอย่างปลอดภัยก่อนติดตั้ง', parent=app)
                return
            if not messagebox.askyesno('ยืนยันติดตั้ง X-Stage',
                'ดาวน์โหลดและตรวจ SHA-256 ผ่านแล้ว\n'
                'บันทึกงานและปิดการเล่นเพลงก่อนติดตั้งต่อ\n'
                'ต้องการเปิดตัวติดตั้งตอนนี้หรือไม่?', parent=app):
                return
            try:
                launch_installer(path)
            except OSError as exc:
                messagebox.showerror('เปิดตัวติดตั้งไม่สำเร็จ', str(exc), parent=app)
                return
            # Let the native installer request elevation and coordinate application shutdown.
            # Do not kill the player while the installer is still displaying confirmation.
        on_ui(confirm_install)

    threading.Thread(target=check_worker, daemon=True, name='XStageReleaseCheck').start()
