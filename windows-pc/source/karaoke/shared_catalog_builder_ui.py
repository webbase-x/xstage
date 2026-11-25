"""Windows PC menu for locally rebuilding the shared Karaoke PC/Online SQLite."""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path

from . import shared_catalog_builder as builder
from .library_setup import remembered_drive_root, drive_library, remember_drive_library
from .shared_drive_layout import setup
import webbrowser


def open_builder(app, initial_root=None, *, parent=None):
    if parent is None:
        from .catalog_window import open_song_management
        return open_song_management(app, 'build', initial_root)
    panel = parent.winfo_toplevel()
    frame = ttk.Frame(parent, padding=24)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="สร้างฐานใหม่สำหรับ PC / Online",
              font=("Leelawadee UI", 17, "bold")).pack(anchor="w")
    ttk.Label(frame, text="ไฟล์เพลงอยู่ที่ใดก็ได้ · ฐานหลัก PC อยู่ในโฟลเดอร์ติดตั้ง DB/songs.sqlite3",
              style="Muted.TLabel").pack(anchor="w", pady=(6, 15))
    row = ttk.Frame(frame)
    row.pack(fill="x", pady=(2, 12))
    saved_root = remembered_drive_root(app.settings)
    folder = tk.StringVar(value=str(initial_root or app.settings.get("catalog_source") or saved_root))
    target = tk.StringVar(value=saved_root)
    ttk.Label(row, text="ต้นทางเพลง").pack(side="left", padx=(0, 8))
    ttk.Entry(row, textvariable=folder, state="readonly", width=20).pack(side="left", fill="x", expand=True, padx=(0, 8))
    def select():
        name = filedialog.askdirectory(parent=panel, title="เลือกโฟลเดอร์คลังเพลง",
                                       initialdir=folder.get() or str(Path.home()))
        if name and not state["busy"]:
            set_source(name)
    ttk.Button(row, text="เปลี่ยนต้นทางเพลง…", command=select).pack(side="left")
    target_row = ttk.Frame(frame)
    target_row.pack(fill="x", pady=(0, 8))
    ttk.Label(target_row, text="สำเนา DB Online").pack(side="left", padx=(0, 8))
    ttk.Entry(target_row, textvariable=target, state="readonly", width=20).pack(side="left", fill="x", expand=True)
    def change_target():
        if state["busy"] or getattr(app, "_shared_build_busy", False):
            return
        chosen = filedialog.askdirectory(parent=panel, title="เปลี่ยนโฟลเดอร์หลัก Google Drive", initialdir=target.get() or str(Path.home()), mustexist=True)
        if chosen:
            try:
                _, root = remember_drive_library(app, chosen)
                target.set(str(root))
                state["approved"] = None
            except (ValueError, OSError) as exc:
                status.set(str(exc))
    ttk.Button(target_row, text="เปลี่ยนคลัง…", command=change_target).pack(side="left", padx=(8, 0))

    ttk.Label(frame, text="ฐานหลัก PC: " + str(Path(getattr(app, "home", app.data_dir)) / "DB" / "songs.sqlite3"), style="Muted.TLabel", wraplength=640).pack(anchor="w", pady=5)
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
        if state["busy"] or getattr(app, "_shared_build_busy", False) or getattr(app, "scanning", False) or getattr(getattr(app, "duplicate_review_window", None), "busy", False):
            return
        requested = folder.get().strip()
        if not requested:
            status.set("กรุณาเลือก XStageKaraoke ก่อน")
            return
        try:
            source = Path(requested).resolve(strict=True)
            if not source.is_dir():
                raise ValueError("ไม่พบโฟลเดอร์ต้นทางเพลง")
            # The selected source and the Online destination are independent.
            if (source / "SONGS").is_dir():
                source = source / "SONGS"
            selected = target.get() or remembered_drive_root(app.settings)
            if not selected:
                try:
                    _, source_root = drive_library(requested)
                    _, source_root = remember_drive_library(app, source_root)
                    selected = str(source_root)
                except (ValueError, OSError):
                    if publish:
                        change_target()
                        selected = target.get()
            if not selected:
                status.set("เลือกปลายทางสำเนา DB Online ครั้งแรก")
                return
            drive, root = drive_library(selected, explicit=True, remembered=selected)
            target.set(str(root))
            # Retain paths relative to SONGS if user chose the shared root.
            source = source.resolve(strict=True)
        except (ValueError, OSError) as exc:
            status.set(str(exc))
            return
        if publish:
            if not messagebox.askyesno(
                "ยืนยันสร้าง SQLite ใหม่จาก Karaoke PC",
                "อ่านไฟล์จากต้นทางเดิม ไม่คัดลอกหรือย้ายไฟล์เพลง\n"
                "Online ต้องมีเพลงตรงกันใน SONGS ของคลัง Drive จึงจะเล่นได้\n"
                "สร้างฐานหลักใน App/DB และทำสำเนาไป Drive โดยไม่ตรวจเพลงซ้ำ\n"
                "หลัง Drive ซิงก์ขึ้นคลาวด์ Online จะจับคู่ File ID ที่ยังไม่รู้ก่อนเล่น\n"
                "ฐานงานผลิตของ Song Studio ไม่เปลี่ยน",
                parent=panel
            ):
                return
        selected_library = root
        selected_source = source
        verify_all = full_verify.get()
        state["busy"] = True
        app._shared_build_busy = True
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
                if publish and getattr(app, "shared_drive_mode", False) and not app.settings.get("shared_local_master"):
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
                root = selected_library
                if publish:
                    setup(root)
                result = builder.build(root, progress=update, cancel=stop,
                                       publish=publish, cache_dir=Path(app.data_dir) / "index-cache",
                                       full_verify=verify_all, deduplicate=not publish, source_songs=selected_source,
                                       local_database=(Path(app.home) / "DB" / ".online-pending.sqlite3") if publish else None)
                result["root"] = str(root)
            except Exception as exc:
                result, error = None, str(exc)
            finally:
                if reader_stopped:
                    app._search_stopping = False
            def finish():
                app._shared_build_busy = False
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
                    status.set("ไม่สำเร็จ · "+error+" · เก็บต้นฉบับและงานที่บันทึกแล้วไว้")
                    return
                if not publish:
                    state["approved"] = requested
                    confirm.configure(state="normal" if result["accepted"] else "disabled")
                    status.set("พร้อม "+str(result["accepted"])+" เพลง · MIDI ซ้ำ "+
                        str(result["duplicates"])+" · ยังไม่มี Drive File ID "+
                        str(result["pending_drive_ids"])+" รายการ · กดยืนยันสร้างฐาน")
                else:
                    state["approved"] = None
                    app.settings["pending_online_master"] = {
                        "root": result["root"], "generation": result["generation"],
                        "source_songs": str(selected_source)}
                    app.settings.pop("pending_pc_only", None)
                    app.save_settings()
                    app.settings["catalog_source"] = requested
                    app.save_settings()
                    messagebox.showinfo("สร้างฐานเพลงสำเร็จ",
                        "ฐานหลัก PC และสำเนา Google Drive พร้อมแล้ว\nเปิดโปรแกรมใหม่เพื่อใช้งานฐานหลักใน DB/songs.sqlite3",
                        parent=panel)
                    status.set("สร้าง SQLite ใหม่สำเร็จ "+str(result["accepted"]) +
                               " เพลง · ไม่ตรวจเพลงซ้ำ" +
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

    inspect = ttk.Button(buttons, text="ตรวจเพลงซ้ำ (PC + Online)", command=lambda: submit(False))
    inspect.pack(side="left", padx=(0, 10))
    confirm = ttk.Button(buttons, text="สร้างฐาน PC + สำเนา Online",
                         command=lambda: submit(True))
    confirm.pack(side="left", padx=(0, 10))
    cancel = ttk.Button(buttons, text="หยุดอย่างปลอดภัย",
                        command=stop.set, state="disabled")
    cancel.pack(side="left")
    def pc_only():
        if state["busy"] or getattr(app, "_shared_build_busy", False):
            return
        requested = folder.get().strip()
        if not requested or not Path(requested).is_dir():
            status.set("กรุณาเลือกโฟลเดอร์ต้นทางเพลง")
            return
        app.settings["catalog_source"] = requested
        app.save_settings()
        if not getattr(app, "shared_drive_mode", False):
            from .catalog_window import open_song_management
            manager = open_song_management(app, "local")
            manager.source = Path(requested)
            manager.source_text.set(requested)
            manager.usage.set("pc")
            manager._start("quick")
            return
        if not messagebox.askyesno("Karaoke PC เท่านั้น",
                "สลับกลับฐาน PC ภายในเครื่องเมื่อเปิดโปรแกรมใหม่หรือไม่?\nเก็บฐานร่วมและเพลงต้นฉบับไว้",
                parent=panel):
            return
        app.settings["pending_pc_only"] = True
        app.settings.pop("pending_online_master", None)
        app.save_settings()
        status.set("เปิดโปรแกรมใหม่เพื่อใช้ฐาน PC เท่านั้น")
    ttk.Button(buttons, text="สร้างฐาน PC เท่านั้น", command=pc_only).pack(side="left", padx=8)

    ttk.Label(frame, text="ตรวจสถานะซิงก์ใน Google Drive for desktop แล้วตรวจฐานบน Karaoke Online · ใช้โฟลเดอร์หลักเดียวกันทั้ง PC และ Web "
              "· SQLite ของ Song Studio Pro ยังแยก · ไม่มีการลบไฟล์เพลงต้นฉบับ",
              style="Muted.TLabel", wraplength=860).pack(anchor="w")
    def set_source(value):
        if not state["busy"]:
            folder.set(str(value))
            app.settings["catalog_source"] = str(value)
            if hasattr(app, "save_settings"):
                app.save_settings()
            if not target.get():
                try:
                    _, root = remember_drive_library(app, value, explicit=False)
                    target.set(str(root))
                except (ValueError, OSError):
                    pass
            state["approved"] = None

    def refresh_target():
        if not state["busy"]:
            old = target.get()
            saved = remembered_drive_root(app.settings)
            if saved and saved != old:
                target.set(saved)
                state["approved"] = None
    frame.refresh_target = refresh_target

    def on_destroy(event):
        if event.widget is frame:
            state["closed"] = True
            stop.set()

    frame.set_source = set_source
    frame.bind("<Destroy>", on_destroy, add="+")
    return frame
