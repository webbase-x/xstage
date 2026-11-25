"""Windows PC menu for locally rebuilding the shared Karaoke PC/Online SQLite."""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path

from . import shared_catalog_builder as builder
from .library_setup import drive_roots, prepare_online, DRIVE_DOWNLOAD
import webbrowser
from tkinter import simpledialog


def open_builder(app, initial_root=None):
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
    ttk.Label(frame, text="PC + Online · เลือกคลังเพลงจากทุกแหล่ง · ฐานหลัก App/DB/songs.sqlite3",
              style="Muted.TLabel").pack(anchor="w", pady=(6, 15))
    row = ttk.Frame(frame)
    row.pack(fill="x", pady=(2, 12))
    folder = tk.StringVar(value=str(initial_root or app.settings.get("shared_drive_root", "")))
    ttk.Entry(row, textvariable=folder).pack(side="left", fill="x", expand=True, padx=(0, 8))
    def select():
        name = filedialog.askdirectory(parent=panel, title="เลือกโฟลเดอร์คลังเพลง",
                                       initialdir=folder.get() or str(Path.home()))
        if name:
            folder.set(name)
            state["approved"] = None
    ttk.Button(row, text="เลือกคลังเพลง…", command=select).pack(side="left")

    full_verify = tk.BooleanVar(value=False)
    ttk.Checkbutton(frame, text="ตรวจแพ็กเกจใหม่ทั้งหมด (ช้ากว่า)", variable=full_verify).pack(anchor="w")
    status = tk.StringVar(value="เลือกคลังเพลง แล้วกดสร้างฐานและซิงก์ · ไม่ตรวจเพลงซ้ำ")
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
                       " · MIDI ซ้ำ " + str(info.get("duplicates", 0)) + " · ใช้ผลเดิม " + str(info.get("reused", 0)))
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
        drive = None
        name = None
        if publish:
            roots = drive_roots()
            if not roots:
                if messagebox.askyesno("ไม่พบ Google Drive", "PC + Online ต้องใช้ Google Drive for desktop ที่เข้าสู่ระบบแล้ว\nเปิดหน้าดาวน์โหลด Google Drive หรือไม่?", parent=panel):
                    webbrowser.open(DRIVE_DOWNLOAD)
                return
            chosen = filedialog.askdirectory(parent=panel, title="เลือก My Drive ของ Google Drive", initialdir=str(roots[0]), mustexist=True)
            if not chosen:
                return
            drive = Path(chosen).resolve()
            if drive not in [p.resolve() for p in roots]:
                messagebox.showwarning("เลือก Google Drive", "กรุณาเลือก My Drive โดยตรง", parent=panel)
                return
            name = simpledialog.askstring("ชื่อคลัง Google Drive", "ชื่อโฟลเดอร์หลัก (ใช้ของเดิมถ้ามี)", initialvalue="XStageKaraoke", parent=panel)
            if not name:
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
        verify_all = full_verify.get()
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
                if publish and getattr(app, "shared_drive_mode", False):
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
                root = prepare_online(requested, drive, name, cancel=stop, progress=update) if publish else Path(requested).resolve()
                result = builder.build(root, progress=update, cancel=stop,
                                       publish=publish, cache_dir=Path(app.data_dir) / "index-cache",
                                       full_verify=verify_all, deduplicate=not publish,
                                       local_database=(Path(app.home) / "DB" / "songs.sqlite3") if publish else None)
                result["root"] = str(root)
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
                confirm.configure(state="normal")
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
                    if app.settings.get("shared_drive_root") != result["root"]:
                        app.settings.pop("shared_drive_folder_id", None)
                    app.settings["shared_drive_root"] = result["root"]
                    if messagebox.askyesno(
                        "ใช้ฐานหลัก PC ในเครื่อง",
                        "สร้างฐานเพลงร่วมสำเร็จแล้ว\n"
                        "ต้องการใช้ App/DB/songs.sqlite3 "
                        "เป็นฐานเพลงหลักของ Karaoke PC หลังเปิดโปรแกรมใหม่หรือไม่?\n"
                        "ฐาน Song Studio Pro จะไม่เปลี่ยน",
                        parent=panel):
                        app.settings["library_mode"] = "google-drive"
                        app.settings["shared_local_master"] = True
                    app.save_settings()
                    status.set("สร้าง SQLite ใหม่สำเร็จ "+str(result["accepted"]) +
                               " เพลง · ไม่ตรวจเพลงซ้ำ "+str(result["duplicates"]) +
                               " · รอ Google Drive ซิงก์ (ยังไม่ยืนยัน Cloud) · File ID รอตรวจ "+str(result["pending_drive_ids"]) +
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

    inspect = ttk.Button(buttons, text="ตรวจเพลงซ้ำ (คลัง Drive)", command=lambda: submit(False))
    inspect.pack(side="left", padx=(0, 10))
    confirm = ttk.Button(buttons, text="สร้างฐานและซิงก์ (เร็วที่สุด)",
                         command=lambda: submit(True))
    confirm.pack(side="left", padx=(0, 10))
    cancel = ttk.Button(buttons, text="หยุดอย่างปลอดภัย",
                        command=stop.set, state="disabled")
    cancel.pack(side="left")
    ttk.Label(frame, text="ตรวจสถานะซิงก์ใน Google Drive for desktop แล้วตรวจฐานบน Karaoke Online · ใช้โฟลเดอร์หลักเดียวกันทั้ง PC และ Web "
              "· SQLite ของ Song Studio Pro ยังแยก · ไม่มีการลบไฟล์เพลงต้นฉบับ",
              style="Muted.TLabel", wraplength=860).pack(anchor="w")
    def close():
        stop.set()
        state["closed"] = True
        panel.destroy()
    panel.protocol("WM_DELETE_WINDOW", close)
    return panel
