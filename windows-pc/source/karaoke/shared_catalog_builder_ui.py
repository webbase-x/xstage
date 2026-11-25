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
    status = tk.StringVar(value="สร้างฐานหลัก App/DB/songs.sqlite3 ก่อน แล้วสำเนาไป Google Drive/DB")
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
        if state["busy"] or getattr(app, "_shared_build_busy", False) or getattr(app, "scanning", False):
            return
        requested = folder.get().strip()
        if not requested:
            status.set("กรุณาเลือก XStageKaraoke ก่อน")
            return
        drive = None
        name = None
        if publish:
            if getattr(app, "engine", None) is not None:
                status.set("หยุดเล่นเพลงก่อนเปลี่ยนฐานหลัก PC · คิวเดิมจะเก็บไว้")
                return
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
                "จะคัดลอก XMID/XSK2 ไปยังคลัง Google Drive หากอยู่นอกคลัง\n"
                "เก็บต้นฉบับไว้ ไม่เขียนทับไฟล์ชื่อเดียวกันที่ต่างกัน\n"
                "สร้างฐานหลัก App/DB/songs.sqlite3 และตรวจ SQLite ให้เสร็จก่อน\n"
                "จากนั้นสำรองฐาน Drive เดิมและสำเนาไป Google Drive/DB/songs.sqlite3\n"
                "หากฐาน Drive เปลี่ยนหรือกำลังเผยแพร่ จะไม่เขียนทับ · ฐาน PC ยังอยู่\n"
                "ฐานงานผลิตของ Song Studio ไม่เปลี่ยน",
                parent=panel
            ):
                return
        verify_all = full_verify.get()
        state["busy"] = True
        app._shared_build_busy = True
        if publish:
            app.scanning = True
            panel.grab_set()
        stop.clear()
        inspect.configure(state="disabled")
        confirm.configure(state="disabled")
        retry.configure(state="disabled")
        cancel.configure(state="normal")
        status.set("กำลังตรวจ XMID/XSK2 ใน SONGS…")
        def work():
            error = None
            reader_stopped = False
            try:
                # Windows refuses to atomically replace an open SQLite file.
                # Close the long-lived PC search reader without touching the
                # playback engine; reopen search after publication.
                if publish:
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
                                       full_verify=verify_all, deduplicate=True,
                                       local_database=(Path(app.home) / "DB" / "songs.sqlite3") if publish else None)
                result["root"] = str(root)
            except Exception as exc:
                result, error = None, str(exc)
            finally:
                if reader_stopped:
                    app._search_stopping = False
            def finish():
                app._shared_build_busy = False
                if publish:
                    app.scanning = False
                    try:
                        panel.grab_release()
                    except tk.TclError:
                        pass
                if state["closed"]:
                    return
                if reader_stopped and error:
                    # Recreate only the search worker, not the active player.
                    try:
                        app.refresh_library()
                    except (OSError, ValueError):
                        pass
                state["busy"] = False
                inspect.configure(state="normal")
                confirm.configure(state="normal")
                retry.configure(state="normal" if app.settings.get("shared_local_master") else "disabled")
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
                    folder.set(result["root"])
                    from .shared_song_library import SharedSongLibrary
                    from .library import SongQueue
                    previous_shared = getattr(app, "shared_drive_mode", False)
                    if app.settings.get("shared_drive_root") != result["root"]:
                        app.settings.pop("shared_drive_folder_id", None)
                    app.settings.update(library_mode="google-drive", shared_local_master=True,
                                        shared_drive_root=result["root"],
                                        local_master_generation=result["generation"])
                    for key in ("pending_pc_only", "pending_online_master", "pending_shared_drive"):
                        app.settings.pop(key, None)
                    if result.get("pc_only_backup"):
                        app.settings["pc_only_backup"] = result["pc_only_backup"]
                    app.library = SharedSongLibrary(result["root"], app.settings, app.save_settings,
                                                    database=Path(result["database"]))
                    app.shared_drive_mode = True
                    app.shared_drive_error = ""
                    retry.configure(state="normal")
                    if not previous_shared:
                        app.song_queue = SongQueue(Path(app.data_dir) / "drive-queue.json")
                    try:
                        app.save_settings()
                    except (OSError, ValueError) as exc:
                        status.set("ฐานหลัก PC บันทึกแล้ว · บันทึกค่าตั้งไม่สำเร็จ: "+str(exc))
                        return
                    try:
                        app.refresh_library()
                        app.refresh_queue()
                    except (OSError, ValueError):
                        pass
                    if result.get("drive_copied"):
                        messagebox.showinfo("สร้างฐานและสำเนาสำเร็จ",
                            "ฐานหลัก: "+result["database"]+"\nสำเนา: "+result["drive_database"]+
                            "\nSHA-256 ตรงกัน · รอ Google Drive for desktop ซิงก์ขึ้น Cloud",
                            parent=panel)
                        status.set("สร้างฐาน PC "+str(result["accepted"])+" เพลง · สำเนา Drive/DB สำเร็จ · ยังไม่ยืนยัน Cloud")
                    else:
                        messagebox.showwarning("ฐาน PC พร้อม · สำเนา Drive ยังไม่เสร็จ",
                            "ฐานหลัก PC ใช้งานได้แล้ว\n"+result.get("drive_error","ตรวจการเชื่อมต่อ Drive"),
                            parent=panel)
                        status.set("ฐาน PC บันทึกแล้ว · ยังไม่สำเนา Drive: "+result.get("drive_error",""))
            try:
                app.after(0, finish)
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True,
                         name="xstage-shared-sqlite-pc-build").start()

    inspect = ttk.Button(buttons, text="ตรวจเพลงซ้ำ (คลัง Drive)", command=lambda: submit(False))
    inspect.pack(side="left", padx=(0, 10))
    confirm = ttk.Button(buttons, text="สร้างฐานและสำเนาไป Drive",
                         command=lambda: submit(True))
    confirm.pack(side="left", padx=(0, 10))
    def retry_copy():
        if state["busy"] or getattr(app,"_shared_build_busy",False) or getattr(app,"scanning",False):
            return
        root = app.settings.get("shared_drive_root")
        generation = app.settings.get("local_master_generation")
        if not root or not generation or not app.settings.get("shared_local_master"):
            status.set("ยังไม่มีฐานหลัก PC ที่พร้อมสำเนา")
            return
        if not messagebox.askyesno("สำเนาฐาน PC อีกครั้ง",
                "ส่งเฉพาะ App/DB/songs.sqlite3 ที่สร้างเสร็จไปยังคลัง Drive เดิม?\n"
                "ไม่สแกนเพลงใหม่และไม่เขียนทับหากฐาน Drive เปลี่ยน",parent=panel):
            return
        state["busy"] = True
        app._shared_build_busy = True
        stop.clear()
        for button in (inspect,confirm,retry):
            button.configure(state="disabled")
        cancel.configure(state="normal")
        status.set("กำลังสำเนาฐาน PC ที่บันทึกแล้ว · ไม่ตรวจเพลงใหม่")
        def work():
            try:
                target = builder.retry_local_copy(Path(app.home)/"DB"/"songs.sqlite3",root,generation,stop)
                message = "สำเนา Drive/DB สำเร็จ · SHA-256 ตรงกัน · รอซิงก์ Cloud: "+target
            except Exception as error:
                message = "ยังไม่สำเนา Drive · ฐาน PC ไม่เปลี่ยน: "+str(error)
            def finish():
                app._shared_build_busy = False
                if state["closed"]:
                    return
                state["busy"] = False
                for button in (inspect,confirm,retry):
                    button.configure(state="normal")
                cancel.configure(state="disabled")
                status.set(message)
            try:
                app.after(0,finish)
            except RuntimeError:
                pass
        threading.Thread(target=work,daemon=True,name="xstage-retry-db-copy").start()

    retry = ttk.Button(buttons,text="สำเนาฐานเดิมอีกครั้ง",command=retry_copy,
                       state="normal" if app.settings.get("shared_local_master") else "disabled")
    retry.pack(side="left",padx=(0,10))
    cancel = ttk.Button(buttons, text="หยุดอย่างปลอดภัย",
                        command=stop.set, state="disabled")
    cancel.pack(side="left")
    def pc_only():
        if state["busy"] or getattr(app, "_shared_build_busy", False):
            return
        if not messagebox.askyesno("Karaoke PC เท่านั้น",
                "สลับกลับฐาน PC ภายในเครื่องเมื่อเปิดโปรแกรมใหม่หรือไม่?\nเก็บฐานร่วมและเพลงต้นฉบับไว้",
                parent=panel):
            return
        app.settings["pending_pc_only"] = True
        app.settings.pop("pending_online_master", None)
        app.save_settings()
        status.set("เปิดโปรแกรมใหม่เพื่อใช้ฐาน PC เท่านั้น")
    ttk.Button(buttons, text="ใช้ PC เท่านั้น", command=pc_only).pack(side="left", padx=8)

    ttk.Label(frame, text="ตรวจสถานะซิงก์ใน Google Drive for desktop แล้วตรวจฐานบน Karaoke Online · ใช้โฟลเดอร์หลักเดียวกันทั้ง PC และ Web "
              "· SQLite ของ Song Studio Pro ยังแยก · ไม่มีการลบไฟล์เพลงต้นฉบับ",
              style="Muted.TLabel", wraplength=860).pack(anchor="w")
    def close():
        if state["busy"]:
            stop.set()
            status.set("กำลังหยุดอย่างปลอดภัย · ปิดหน้าต่างได้เมื่อหยุดแล้ว")
            return
        state["closed"] = True
        panel.destroy()
    panel.protocol("WM_DELETE_WINDOW", close)
    return panel
