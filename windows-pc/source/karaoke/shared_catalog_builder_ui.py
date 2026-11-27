"""Windows PC menu for locally rebuilding the shared Karaoke PC/Online SQLite."""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path

from . import shared_catalog_builder as builder
from .library_setup import remembered_drive_root, drive_library, remember_drive_library


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
    from .local_master import kind
    legacy_db = tk.StringVar(value="")
    home_path=Path(getattr(app,"home",app.data_dir))
    for candidate in (home_path/"DB"/"songs.sqlite3", Path(app.data_dir)/"songs.sqlite3"):
        try:
            if kind(candidate) == "pc":
                legacy_db.set(str(candidate))
                break
        except (OSError,ValueError):
            pass
    legacy_row = ttk.Frame(frame)
    legacy_row.pack(fill="x", pady=(0,8))
    ttk.Label(legacy_row,text="ฐาน PC เดิม (ถ้ามี)").pack(side="left",padx=(0,8))
    ttk.Entry(legacy_row,textvariable=legacy_db,state="readonly").pack(side="left",fill="x",expand=True)
    def choose_legacy():
        if state["busy"]: return
        chosen=filedialog.askopenfilename(parent=panel,title="เลือกฐาน SQLite ของ PC เดิม",filetypes=[("SQLite","*.sqlite3 *.sqlite *.db"),("All files","*.*")])
        if chosen: legacy_db.set(chosen)
    ttk.Button(legacy_row,text="เลือกฐาน…",command=choose_legacy).pack(side="left",padx=4)
    ttk.Button(legacy_row,text="ไม่ใช้ฐานเดิม",command=lambda:legacy_db.set("") if not state["busy"] else None).pack(side="left")
    full_verify = tk.BooleanVar(value=False)
    ttk.Checkbutton(frame, text="ตรวจแพ็กเกจใหม่ทั้งหมด (ช้ากว่า)", variable=full_verify).pack(anchor="w")
    status = tk.StringVar(value="เลือกต้นทางเพลง แล้วสร้างฐาน PC · คัดลอกฐานไป Drive ได้ภายหลัง")
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
            status.set("กรุณาเลือกโฟลเดอร์ต้นทางเพลงก่อน")
            return
        try:
            source = Path(requested).resolve(strict=True)
            if not source.is_dir():
                raise ValueError("ไม่พบโฟลเดอร์ต้นทางเพลง")
            # The selected source and the Online destination are independent.
            if (source / "SONGS").is_dir():
                source = source / "SONGS"
            root = Path(app.home).resolve(strict=True)
            # Retain paths relative to SONGS if user chose the shared root.
            source = source.resolve(strict=True)
        except (ValueError, OSError) as exc:
            status.set(str(exc))
            return
        selected_legacy=legacy_db.get().strip()
        if publish and not messagebox.askyesno(
                "สร้างฐาน SQLite สำหรับ PC / Web / APK",
                ("ย้ายข้อมูลจากฐาน PC เดิม รักษารหัสเพลงและจำนวนรายการ ตรวจไฟล์จริง\n" if selected_legacy else
                 "สร้างฐานร่วมจากเพลงที่เลือกใน App/DB เท่านั้น\n")+
                "ไม่คัดลอกเพลงหรือเชื่อม Google Drive\nเปิดโปรแกรมใหม่เพื่อใช้ฐานที่สร้าง",
                parent=panel, default="no"):
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
            try:
                if selected_legacy:
                    from .legacy_catalog_migration import migrate
                    result=migrate(selected_legacy,selected_source,selected_library,
                        progress=update,cancel=stop,publish=publish,
                        cache_dir=Path(app.data_dir)/"index-cache",full_verify=verify_all)
                else:
                    result = builder.build(selected_library, progress=update, cancel=stop,
                                           publish=publish, cache_dir=Path(app.data_dir) / "index-cache",
                                           full_verify=verify_all, deduplicate=not publish,
                                           source_songs=selected_source, local_only=True)
                result["root"] = str(selected_library)
            except Exception as exc:
                result, error = None, str(exc)
            def finish():
                app._shared_build_busy = False
                if state["closed"]:
                    return
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
                        "source_songs": str(selected_source), "local_only": True,
                        "legacy_migration": bool(result.get("legacy_migration") and
                            Path(selected_legacy).resolve() == Path(getattr(app.library,"path",Path(app.home)/"DB"/"songs.sqlite3")).resolve())}
                    app.settings.pop("pending_pc_only", None)
                    app.save_settings()
                    app.settings["catalog_source"] = requested
                    app.save_settings()
                    messagebox.showinfo("สร้างฐานเพลงสำเร็จ",
                        "ฐาน PC พร้อมแล้ว · ไม่ได้ส่งไป Drive" +
                        "\nเปิดโปรแกรมใหม่เพื่อใช้งานฐานหลักใน DB/songs.sqlite3",
                        parent=panel)
                    status.set("สร้าง SQLite ใหม่สำเร็จ "+str(result["accepted"]) +
                               " เพลง · ไม่ตรวจเพลงซ้ำ" +
                               " · เปิดโปรแกรมใหม่เพื่อใช้ฐาน PC")
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

    inspect = ttk.Button(buttons, text="ตรวจเพลงซ้ำจากต้นทาง", command=lambda: submit(False))
    inspect.pack(side="left", padx=(0, 10))
    confirm = ttk.Button(buttons, text="สร้าง/อัปเดตฐาน PC",
                         command=lambda: submit(True))
    confirm.pack(side="left", padx=(0, 10))
    cancel = ttk.Button(buttons, text="หยุดอย่างปลอดภัย",
                        command=stop.set, state="disabled")
    cancel.pack(side="left")
    def export_database():
        if state["busy"] or getattr(app, "_shared_build_busy", False) or getattr(app, "scanning", False):
            return
        pending=app.settings.get("pending_online_master")
        if not target.get():
            change_target()
        try:
            _, root = drive_library(target.get(), explicit=True, remembered=target.get())
            destination = root / "DB" / "songs.sqlite3"
            overwrite = destination.exists()
            live=home_path/"DB"/"songs.sqlite3"
            selected_legacy=legacy_db.get().strip()
            if not pending and kind(live) != "online":
                selected_legacy=selected_legacy or (str(live) if kind(live)=="pc" else "")
                if not selected_legacy:
                    raise ValueError("ยังไม่มีฐาน PC · กรุณาสร้างหรือเลือกฐานเดิมก่อน")
            else:
                selected_legacy=""
            if not messagebox.askyesno("คัดลอกฐาน PC ไป Online",
                    ("แปลงฐาน PC เดิมเป็นฐานร่วมโดยตรวจไฟล์ใน SONGS ก่อนส่ง\n" if selected_legacy else
                     "ตรวจสอบเพลงใน SONGS แล้วคัดลอกฐาน PC ไปยังคลังที่เลือก\n")+
                    "ปิดโปรแกรมที่ใช้ฐานบน Drive ทุกเครื่อง และรอ Drive ซิงก์ก่อน\n"
                    "ระบบสำรองฐานเดิมไป BACKUP ก่อนแทนที่ · ไม่ลบ WAL/SHM โดยตรง\n" + str(destination),
                    parent=panel, default="no"):
                return
        except (ValueError, OSError) as exc:
            status.set(str(exc))
            return
        state["busy"] = True
        app._shared_build_busy = True
        stop.clear()
        inspect.configure(state="disabled")
        confirm.configure(state="disabled")
        export_button.configure(state="disabled")
        cancel.configure(state="normal")
        status.set("กำลังตรวจและคัดลอกฐาน SQLite ไป Google Drive…")
        def worker():
            from .local_master import export_portable, prepare_legacy_export
            prepared=None
            try:
                unchanged = []
                if selected_legacy:
                    prepared=prepare_legacy_export(home_path,selected_legacy,root,
                        progress=update,cancel=stop,cache_dir=Path(app.data_dir)/"index-cache")
                result = export_portable(home_path, root, overwrite=overwrite, cancel=stop,
                                         on_unchanged=lambda: unchanged.append(True),
                                         pending=bool(pending or prepared),progress=update)
                message = ("ฐาน SQLite เหมือนเดิม · ไม่ส่งซ้ำ: " if unchanged else
                           "คัดลอกฐานสำเร็จ · รอ Google Drive ซิงก์: ") + str(result)
            except Exception as exc:
                message = "ไม่สำเร็จ · " + str(exc)
            def done():
                if prepared:
                    app.settings["pending_online_master"]={
                        "root":str(home_path),"generation":prepared["generation"],
                        "source_songs":str(root/"SONGS"),"local_only":True,
                        "legacy_migration":Path(selected_legacy).resolve()==Path(
                            getattr(app.library,"path",home_path/"DB"/"songs.sqlite3")).resolve()}
                    app.settings.pop("pending_pc_only",None)
                    app.save_settings()
                app._shared_build_busy = False
                state["busy"] = False
                if not state["closed"]:
                    inspect.configure(state="normal")
                    confirm.configure(state="normal")
                    export_button.configure(state="normal")
                    cancel.configure(state="disabled")
                    status.set(message)
            try:
                app.after(0, done)
            except RuntimeError:
                pass
        threading.Thread(target=worker, daemon=True, name="xstage-catalog-export").start()

    export_button = ttk.Button(buttons, text="คัดลอกฐานไป Google Drive", command=export_database)
    export_button.pack(side="left", padx=8)

    ttk.Label(frame, text="คัดลอก SONGS ทั้งโฟลเดอร์ไปยังคลังที่เลือกก่อนคัดลอก DB · ตรวจสถานะ Google Drive ซิงก์ "
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
