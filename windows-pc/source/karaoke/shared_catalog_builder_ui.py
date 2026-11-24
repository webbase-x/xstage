"""Windows PC menu for locally rebuilding the shared Karaoke PC/Online SQLite."""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path

from . import shared_catalog_builder as builder


def open_builder(app):
    panel = tk.Toplevel(app)
    panel.title("X-Stage Karaoke PC · สร้างฐานใหม่สำหรับ PC / Online")
    panel.geometry("930x450")
    panel.minsize(780, 400)
    panel.configure(bg="#081d58")
    panel.transient(app)
    frame = ttk.Frame(panel, padding=24)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="สร้างฐานใหม่สำหรับ PC / Online",
              font=("Leelawadee UI", 17, "bold")).pack(anchor="w")
    ttk.Label(frame, text="สร้าง DB/songs.sqlite3 จาก XMID/XSK2 ใน XStageKaraoke/SONGS · รหัสและพาธตรงกัน",
              style="Muted.TLabel").pack(anchor="w", pady=(6, 15))
    row = ttk.Frame(frame)
    row.pack(fill="x", pady=(2, 12))
    folder = tk.StringVar(value=str(app.settings.get("shared_drive_root", "")))
    ttk.Entry(row, textvariable=folder).pack(side="left", fill="x", expand=True, padx=(0, 8))
    def select():
        name = filedialog.askdirectory(parent=panel, title="เลือก XStageKaraoke บน Google Drive for desktop",
                                       initialdir=folder.get() or str(Path.home()))
        if name:
            folder.set(name)
            confirm.configure(state="disabled")
            state["approved"] = None
    ttk.Button(row, text="เลือก Google Drive…", command=select).pack(side="left")

    status = tk.StringVar(value="เลือกคลังหลัก แล้วกดตรวจไฟล์และเพลงซ้ำก่อนสร้างฐาน")
    ttk.Label(frame, textvariable=status, style="Muted.TLabel",
              wraplength=860).pack(fill="x", pady=8)
    progress = ttk.Progressbar(frame, mode="determinate", maximum=100)
    progress.pack(fill="x", pady=(7, 16))
    state = {"busy": False, "approved": None, "closed": False}
    stop = threading.Event()
    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(4, 10))

    def update(info, message):
        if state["closed"]:
            return
        def paint():
            if state["closed"]:
                return
            total = info.get("total") or 0
            if total:
                progress.configure(value=min(100, info.get("scanned", 0) * 100 / total))
            status.set(message + " · " + str(info.get("scanned", 0)) + " / " +
                       str(total) + " · พร้อม " + str(info.get("accepted", 0)) +
                       " · MIDI ซ้ำ " + str(info.get("duplicates", 0)))
        try:
            app.after(0, paint)
        except RuntimeError:
            pass

    def submit(publish):
        if state["busy"]:
            return
        requested = folder.get().strip()
        if not requested:
            status.set("กรุณาเลือก XStageKaraoke ก่อน")
            return
        if publish:
            if not state["approved"] or state["approved"] != requested:
                status.set("ปลายทางเปลี่ยน กรุณาตรวจไฟล์ใหม่")
                confirm.configure(state="disabled")
                return
            if not messagebox.askyesno(
                "ยืนยันสร้าง SQLite ใหม่จาก Karaoke PC",
                "ต้องการสร้างและเผยแพร่ XStageKaraoke/DB/songs.sqlite3 ใหม่จาก XMID/XSK2 "
                "ทุกไฟล์ใน Google Drive PC ใช่หรือไม่?\n"
                "ระบบตรวจ SHA-256/MIDI ซ้ำและสำรองฐานเดิมก่อนแทนที่\n"
                "หลัง Drive ซิงก์ขึ้นคลาวด์ Online จะจับคู่ File ID ที่ยังไม่รู้ก่อนเล่น\n"
                "ฐานงานผลิตของ Song Studio ไม่เปลี่ยน",
                parent=panel
            ):
                return
        state["busy"] = True
        stop.clear()
        inspect.configure(state="disabled")
        confirm.configure(state="disabled")
        cancel.configure(state="normal")
        status.set("กำลังตรวจ XMID/XSK2 ใน SONGS…")
        def work():
            error = None
            reader_stopped = False
            try:
                # Windows refuses to atomically replace an open SQLite file.
                # Close the long-lived PC search reader without touching the
                # playback engine; reopen search after publication.
                if publish and getattr(app, "shared_drive_mode", False) and str(
                        getattr(getattr(app, "library", None), "root", "")) == str(
                        Path(requested).resolve()):
                    condition = getattr(app, "_search_condition", None)
                    if condition is not None:
                        with condition:
                            app._search_stopping = True
                            condition.notify_all()
                        reader = getattr(app, "_active_reader", None)
                        if reader is not None:
                            try:
                                reader.interrupt()
                            except Exception:
                                pass
                        worker = getattr(app, "_search_thread", None)
                        if worker is not None:
                            worker.join(timeout=6)
                            if worker.is_alive():
                                raise ValueError("ตัวอ่าน SQLite ของ PC ยังใช้งานอยู่ · หยุดค้นหาก่อนสร้างฐาน")
                        app._active_reader = None
                        app._search_thread = None
                        reader_stopped = True
                result = builder.build(requested, progress=update, cancel=stop,
                                       publish=publish)
            except Exception as exc:
                result, error = None, str(exc)
            finally:
                if reader_stopped:
                    app._search_stopping = False
            def finish():
                if state["closed"]:
                    return
                if reader_stopped and getattr(app, "shared_drive_mode", False):
                    # Recreate only the search worker, not the active player.
                    try:
                        app.refresh_library()
                    except (OSError, ValueError):
                        pass
                state["busy"] = False
                inspect.configure(state="normal")
                cancel.configure(state="disabled")
                if error:
                    state["approved"] = None
                    status.set("ไม่สำเร็จ · "+error+" · ฐานเดิมยังไม่ถูกแทนที่")
                    return
                if not publish:
                    state["approved"] = requested
                    confirm.configure(state="normal" if result["accepted"] else "disabled")
                    status.set("พร้อม "+str(result["accepted"])+" เพลง · MIDI ซ้ำ "+
                        str(result["duplicates"])+" · ยังไม่มี Drive File ID "+
                        str(result["pending_drive_ids"])+" รายการ · กดยืนยันสร้างฐาน")
                else:
                    state["approved"] = None
                    app.settings["shared_drive_root"] = requested
                    app.save_settings()
                    status.set("สร้าง SQLite ใหม่สำเร็จ "+str(result["accepted"]) +
                               " เพลง · ข้าม MIDI ซ้ำ "+str(result["duplicates"]) +
                               " · รอซิงก์ File ID "+str(result["pending_drive_ids"]) +
                               " เพลง · เมื่อ Online เปิดเพลงจะตรวจจับคู่กับ Drive")
                    if getattr(app, "shared_drive_mode", False):
                        try:
                            app.refresh_library()
                            app.refresh_queue()
                        except (OSError, ValueError):
                            pass
            try:
                app.after(0, finish)
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True,
                         name="xstage-shared-sqlite-pc-build").start()

    inspect = ttk.Button(buttons, text="1. ตรวจไฟล์และ MIDI ซ้ำ", command=lambda: submit(False))
    inspect.pack(side="left", padx=(0, 10))
    confirm = ttk.Button(buttons, text="2. สร้างฐานใหม่สำหรับ PC / Online",
                         command=lambda: submit(True), state="disabled")
    confirm.pack(side="left", padx=(0, 10))
    cancel = ttk.Button(buttons, text="หยุดอย่างปลอดภัย",
                        command=stop.set, state="disabled")
    cancel.pack(side="left")
    ttk.Label(frame, text="ใช้ Google Drive for desktop โฟลเดอร์หลักเดียวกันทั้ง PC และ Web "
              "· SQLite ของ Song Studio Pro ยังแยก · ไม่มีการลบไฟล์เพลงต้นฉบับ",
              style="Muted.TLabel", wraplength=860).pack(anchor="w")
    def close():
        stop.set()
        state["closed"] = True
        panel.destroy()
    panel.protocol("WM_DELETE_WINDOW", close)
    return panel
