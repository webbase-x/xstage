"""Karaoke PC: non-destructive push of local media to Google Drive for desktop."""
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

from . import shared_drive_sync as sync


def open_drive_push(app):
    dialog = tk.Toplevel(app)
    dialog.title("X-Stage Karaoke PC · จัดการเพลงและปลายทาง Google Drive")
    dialog.geometry("900x470")
    dialog.minsize(750, 425)
    dialog.configure(bg="#081d58")
    dialog.transient(app)
    frame = ttk.Frame(dialog, padding=22)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="X-STAGE · GOOGLE DRIVE SYNC",
              font=("Leelawadee UI", 17, "bold")).pack(anchor="w")
    ttk.Label(frame, text="ส่งเพลง, SoundFont และ FX ไป XStageKaraoke โดยไม่แก้ DB/songs.sqlite3",
              style="Muted.TLabel").pack(anchor="w", pady=(0, 12))
    source_var = tk.StringVar()
    root_var = tk.StringVar(value=str(app.settings.get("shared_drive_root", "")))
    area_var = tk.StringVar(value="SONGS")
    status = tk.StringVar(value="เลือกต้นทางและปลายทาง แล้วกดตรวจรายการก่อนส่ง")
    preview = [None]
    cancel = threading.Event()
    work = [None]
    closed = [False]
    phase = [""]
    generation = [0]
    buttons = {}

    def choose(target, caption):
        location = filedialog.askdirectory(parent=dialog, title=caption,
                                           initialdir=target.get() or str(Path.home()))
        if location:
            target.set(location)
            reset()

    def input_row(title, var, action, caption):
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=5)
        ttk.Label(row, text=title, width=20).pack(side="left")
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="เลือกโฟลเดอร์…",
                   command=lambda:choose(var,caption)).pack(side="left")

    input_row("แหล่งไฟล์บนเครื่อง", source_var, None, "เลือกโฟลเดอร์เพลง/SoundFont/FX")
    input_row("Google Drive PC", root_var, None, "เลือกโฟลเดอร์ XStageKaraoke")
    options = ttk.Frame(frame)
    options.pack(fill="x", pady=(8, 10))
    ttk.Label(options, text="ประเภท").pack(side="left")
    types = ttk.Combobox(options, textvariable=area_var, state="readonly",
                         width=20, values=sync.AREAS)
    types.pack(side="left", padx=8)
    ttk.Label(options, text="SONGS · เพลง    SOUNDFONT · SF2/SF3    FX · เอฟเฟกต์",
              style="Muted.TLabel").pack(side="left")
    ttk.Label(frame, textvariable=status, style="Muted.TLabel",
              wraplength=800).pack(fill="x", pady=10)
    bar = ttk.Frame(frame)
    bar.pack(fill="x", pady=8)

    def is_running():
        return work[0] is not None and work[0].is_alive()

    def reset(*_):
        preview[0] = None
        buttons["push"].configure(state="disabled")
        if not is_running():
            status.set("แหล่งหรือประเภทเปลี่ยน · กรุณาตรวจรายการใหม่")

    def update_ui(progress, text):
        if closed[0]:
            return
        dialog.after(0, lambda: None if closed[0] else status.set(text))

    def run_job(kind, operation):
        if is_running():
            return
        cancel.clear()
        phase[0] = kind
        generation[0] += 1
        current = generation[0]
        for btn in ("preview","push"):
            buttons[btn].configure(state="disabled")
        buttons["stop"].configure(state="normal")
        def runner():
            try:
                output = operation(lambda details, message:update_ui(details, message), cancel)
                error = None
            except Exception as exc:
                output, error = None, str(exc)
            def done():
                if closed[0] or current != generation[0]:
                    return
                buttons["stop"].configure(state="disabled")
                buttons["preview"].configure(state="normal")
                if error:
                    preview[0] = None
                    buttons["push"].configure(state="disabled")
                    status.set("ไม่สำเร็จ: " + error)
                    return
                if kind == "preview":
                    preview[0] = output
                    stats = output["stats"]
                    can_push = stats["new"] > 0 and stats["conflict"] == 0
                    buttons["push"].configure(state="normal" if can_push else "disabled")
                    status.set("ตรวจ " + format(stats["scanned"], ",") + " ไฟล์ · ใหม่ " +
                               str(stats["new"]) + " · ตรงกัน " + str(stats["identical"]) +
                               " · ซ้ำ " + str(stats["duplicate"]) + " · ชื่อชน " +
                               str(stats["conflict"]) + " · " +
                               ("พร้อมส่ง" if can_push else "ยังส่งไม่ได้หรือไม่มีไฟล์ใหม่"))
                else:
                    preview[0] = None
                    buttons["push"].configure(state="disabled")
                    status.set("ส่งสำเร็จ " + str(output["published"]) +
                               " ไฟล์ · " + ("หยุดแล้ว ไฟล์ที่ส่งแล้วคงอยู่" if output["cancelled"] else
                               "รอ Drive ซิงก์ แล้วตรวจ DB จาก Karaoke Online"))
            try:
                app.after(0, done)
            except RuntimeError:
                pass
        work[0] = threading.Thread(target=runner, daemon=True,
                                   name="pc-drive-"+kind)
        work[0].start()

    def inspect():
        source = source_var.get().strip()
        root = root_var.get().strip()
        area = area_var.get().strip()
        if not source or not root:
            status.set("ต้องเลือกต้นทางและโฟลเดอร์หลัก XStageKaraoke")
            return
        reset()
        run_job("preview",lambda progress, stopped:
                sync.inspect(source,root,area,stopped,progress))

    def publish():
        plan = preview[0]
        if not plan or is_running():
            return
        source = source_var.get().strip()
        root = root_var.get().strip()
        area = area_var.get().strip()
        try:
            same_source = str(Path(source).expanduser().resolve(strict=True)) == plan["source"]
            same_root = str(sync.resolve_root(root)) == plan["root"]
        except (ValueError, OSError):
            same_source = same_root = False
        if not same_source or not same_root or area != plan["area"]:
            reset()
            status.set("พาธเปลี่ยน กรุณาตรวจรายการใหม่ก่อนส่ง")
            return
        stats = plan["stats"]
        if not messagebox.askyesno("ยืนยันส่งเข้า Google Drive",
            "ส่งไฟล์ใหม่ " + format(stats["new"], ",") + " รายการ / " +
            format(stats["bytes"] / 1048576, ".1f") + " MiB ไปที่ " +
            root + "/" + area + "?\n"
            "ไม่ลบไฟล์ต้นฉบับหรือไฟล์ใน Drive และไม่เขียนทับ SQLite",
            parent=dialog):
            return
        def operation(progress, stopped):
            return sync.publish(source,root,area,progress,stopped,plan=plan)
        run_job("publish",operation)

    buttons["preview"] = ttk.Button(bar,text="ตรวจไฟล์/ตรวจซ้ำ (ไม่แก้ข้อมูล)",command=inspect)
    buttons["preview"].pack(side="left",padx=(0,8))
    buttons["push"] = ttk.Button(bar,text="ยืนยันส่งขึ้น Google Drive",command=publish,state="disabled")
    buttons["push"].pack(side="left",padx=(0,8))
    buttons["stop"] = ttk.Button(bar,text="หยุดอย่างปลอดภัย",command=cancel.set,state="disabled")
    buttons["stop"].pack(side="left")
    ttk.Label(frame, text="Google Drive for desktop เป็นผู้ส่งไฟล์ขึ้นคลาวด์ต่อ · เมื่อซิงก์เสร็จต้องอัปเดตฐานเพลงใน Karaoke Online · ซ้ำ MIDI ภายใน XMID/XSK ตรวจอีกชั้นตอนสร้างฐาน",
              style="Muted.TLabel",wraplength=800).pack(anchor="w",pady=10)

    def close():
        cancel.set()
        closed[0] = True
        generation[0] += 1
        dialog.destroy()
    dialog.protocol("WM_DELETE_WINDOW",close)
    root_var.trace_add("write",reset)
    source_var.trace_add("write",reset)
    area_var.trace_add("write",reset)
    return dialog
