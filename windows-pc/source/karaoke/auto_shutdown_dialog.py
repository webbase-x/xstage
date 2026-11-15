"""Opt-in Windows shutdown after a verified, completed catalog build.

No OS shutdown command is issued until the visible 60-second countdown has
finished, and user cancellation remains possible throughout the countdown.
"""
from __future__ import annotations

import os
import subprocess
import time
import tkinter as tk
from tkinter import ttk, messagebox

from .dialog_layout import DialogWindow


def shutdown_allowed(app, result, *, platform=None):
    platform = os.name if platform is None else platform
    return (platform == 'nt' and bool(getattr(result, 'safe_to_shutdown', False))
            and not bool(getattr(app, 'scanning', False))
            and not bool(getattr(app, '_cloud_backup_busy', False))
            and not bool(getattr(app, '_cleanup_busy', False))
            and not bool(getattr(app, 'engine', None))
            and not bool(getattr(app, 'cancel_scan', None) and app.cancel_scan.is_set()))


class AutoShutdownCountdown:
    def __init__(self, app, result, seconds=60):
        self.app = app
        self.result = result
        self.deadline = time.monotonic() + seconds
        self.timer = None
        self.cancelled = False
        self.window = DialogWindow(app)
        self.window.title('ปิดเครื่องอัตโนมัติ — X-Stage Karaoke')
        self.window.geometry('570x235')
        self.window.transient(app)
        self.window.protocol('WM_DELETE_WINDOW', self.cancel)
        self.window.bind('<Escape>', lambda _: self.cancel())
        self.caption = tk.StringVar(self.window)
        ttk.Label(self.window.content, text='สร้างรายการเพลงสำเร็จและตรวจการบันทึกแล้ว',
                  font=('Leelawadee UI', 14, 'bold'), padding=(18, 16, 18, 8)).pack(anchor='w')
        ttk.Label(self.window.content, textvariable=self.caption, wraplength=510,
                  font=('Leelawadee UI', 11), padding=(18, 4)).pack(anchor='w')
        ttk.Label(self.window.content, text='โปรดบันทึกงานในโปรแกรมอื่นก่อนปิด Windows · ไม่ใช้คำสั่งบังคับปิดแอป',
                  wraplength=510, padding=(18, 10)).pack(anchor='w')
        actions = ttk.Frame(self.window.footer, padding=12)
        actions.pack(fill='x')
        ttk.Button(actions, text='ยกเลิกการปิดเครื่อง', command=self.cancel).pack(side='right')
        self.window.lift()
        self.tick()

    def tick(self):
        if self.cancelled:
            return
        if not shutdown_allowed(self.app, self.result):
            self.cancel()
            return
        remaining = max(0, int(self.deadline - time.monotonic() + .999))
        self.caption.set(f'Windows จะปิดเครื่องในอีก {remaining} วินาที  (กดยกเลิกได้)')
        if remaining:
            self.timer = self.window.after(200, self.tick)
        else:
            self.timer = None
            self.execute()

    def execute(self):
        if not shutdown_allowed(self.app, self.result):
            self.cancel()
            return
        try:
            # Never use /f: Windows must retain its native unsaved-work safeguards.
            subprocess.run(['shutdown.exe', '/s', '/t', '0'], check=True,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=10)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            self.cancel()
            messagebox.showerror('ปิดเครื่องไม่สำเร็จ', str(error), parent=self.app)

    def cancel(self):
        self.cancelled = True
        if self.timer is not None:
            try:self.window.after_cancel(self.timer)
            except tk.TclError:pass
            self.timer = None
        try:self.window.destroy()
        except tk.TclError:pass
        if getattr(self.app, '_catalog_shutdown_dialog', None) is self:
            self.app._catalog_shutdown_dialog = None


def maybe_schedule_shutdown(app, result):
    if not getattr(result, 'safe_to_shutdown', False):
        return False
    if os.name != 'nt':
        return False
    if not shutdown_allowed(app, result):
        return False
    previous = getattr(app, '_catalog_shutdown_dialog', None)
    if previous is not None:
        previous.cancel()
    app._catalog_shutdown_dialog = AutoShutdownCountdown(app, result)
    return True
