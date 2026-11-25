"""Dedicated Classic PC dialog for the SAME SQLite catalog used by Karaoke Online."""
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

from . import drive_online_catalog as catalog


def open_shared_drive_catalog(app):
    window = tk.Toplevel(app)
    window.title("X-Stage Karaoke PC · Google Drive / ฐานเพลงร่วม")
    window.geometry("980x640")
    window.minsize(780, 520)
    window.configure(bg="#081d58")
    window.transient(app)
    body = ttk.Frame(window, padding=18)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="GOOGLE DRIVE · คลังเพลงที่ผู้ใช้เลือก",
              font=("Leelawadee UI", 17, "bold")).pack(anchor="w")
    ttk.Label(body, text="อ่านฐาน DB/songs.sqlite3 จาก Google Drive บนเครื่องโดยตรง · ไม่แก้ SQLite ของ Online",
              style="Muted.TLabel").pack(anchor="w", pady=(3, 12))
    row = ttk.Frame(body)
    row.pack(fill="x", pady=4)
    selected_root = tk.StringVar(value=str(app.settings.get("shared_drive_root", "")))
    root_entry = ttk.Entry(row, textvariable=selected_root)
    root_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
    def browse():
        chosen = filedialog.askdirectory(parent=window,
            title="เลือกโฟลเดอร์หลักคลังเพลงใน Google Drive for desktop",
            initialdir=selected_root.get() or str(Path.home()))
        if chosen:
            if str(Path(chosen).resolve()) != str(Path(selected_root.get() or chosen).resolve()):
                drive_id.set("")
            selected_root.set(chosen)
            load()
    ttk.Button(row, text="เลือกโฟลเดอร์ Google Drive…", command=browse).pack(side="left")
    id_row = ttk.Frame(body)
    id_row.pack(fill="x", pady=(0, 7))
    ttk.Label(id_row, text="Folder ID / ลิงก์ Google Drive").pack(side="left", padx=(0, 8))
    drive_id = tk.StringVar(value=str(app.settings.get("shared_drive_folder_id", "")))
    ttk.Entry(id_row, textvariable=drive_id).pack(side="left", fill="x", expand=True)
    summary = tk.StringVar(value="เลือกโฟลเดอร์คลังเพลงที่ Google Drive for desktop ซิงก์กับ Folder ID นี้")
    ttk.Label(body, textvariable=summary, style="Muted.TLabel", wraplength=900).pack(anchor="w", pady=(3, 9))
    search_row = ttk.Frame(body)
    search_row.pack(fill="x")
    ttk.Label(search_row, text="ค้นหาเพลง/ศิลปิน/รหัส").pack(side="left", padx=(0, 6))
    query = tk.StringVar()
    search_input = ttk.Entry(search_row, textvariable=query)
    search_input.pack(side="left", fill="x", expand=True)
    box = ttk.Frame(body)
    box.pack(fill="both", expand=True, pady=10)
    columns = ("code", "title", "artist", "format", "available")
    tree = ttk.Treeview(box, columns=columns, show="headings", height=16)
    for name, label, width in (
        ("code", "รหัส", 105), ("title", "ชื่อเพลง", 300),
        ("artist", "ศิลปิน", 175), ("format", "ประเภท", 90),
        ("available", "ไฟล์ในเครื่อง", 110)
    ):
        tree.heading(name, text=label)
        tree.column(name, width=width, minwidth=60, stretch=name in ("title", "artist"))
    scroll = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    actions = ttk.Frame(body)
    actions.pack(fill="x", pady=(0, 8))
    results = {}
    revision = [0]
    closing = [False]
    busy = [False]

    def report_error(error):
        summary.set("ไม่สามารถอ่านฐานร่วมได้: " + str(error))

    def load():
        if closing[0]:
            return
        root_text = selected_root.get().strip()
        revision[0] += 1
        current = revision[0]
        lookup = query.get().strip()
        busy[0] = True
        summary.set("กำลังอ่าน SQLite จาก Google Drive PC (อ่านอย่างเดียว)…")
        def work():
            try:
                info = catalog.summary(root_text)
                rows = catalog.search(info["root"], lookup, 150)
                error = None
            except Exception as exc:
                info, rows, error = None, None, str(exc)
            def finish():
                if closing[0] or current != revision[0]:
                    return
                busy[0] = False
                if error:
                    report_error(error)
                    return
                selected_root.set(info["root"])
                # Browsing does not change the active PC library root.
                results.clear()
                for item in tree.get_children():
                    tree.delete(item)
                for index, song in enumerate(rows):
                    ident = str(index)
                    results[ident] = song
                    tree.insert("", "end", iid=ident, values=(
                        song.get("code") or "", song.get("title") or "",
                        song.get("artist") or "", song.get("source_format") or "",
                        "พร้อม" if song.get("local_path") else "ยังไม่ซิงก์"
                    ))
                summary.set("ฐานร่วม: " + info["database"] + " · " +
                            format(info["songs"], ",") + " เพลง · แสดง " + str(len(rows)) +
                            " · MIDI ซ้ำในฐาน " + str(info["duplicate_midi_groups"]) + " กลุ่ม")
            try:
                app.after(0, finish)
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True, name="drive-online-catalog-read").start()

    def play_selected():
        selection = tree.selection()
        if not selection:
            return
        song = results.get(selection[0])
        if not song:
            return
        path = song.get("local_path")
        if not path:
            messagebox.showwarning("เพลงยังไม่พร้อม",
                "ไฟล์เพลงยังไม่ถูกซิงก์ลง Google Drive PC หรือไม่มีพาธตรงกับฐาน Online\n"
                "ตรวจ Google Drive for desktop ก่อน ไม่เดาตำแหน่งไฟล์จากชื่อเพลง",
                parent=window)
            return
        try:
            from .library import QueueItem, SUPPORTED
            if Path(path).suffix.lower() not in SUPPORTED:
                raise ValueError("รูปแบบไฟล์นี้ยังเล่นบน Karaoke PC ไม่ได้")
            # The shared SQLite is authoritative. Playback reads its local
            # media path without ever inserting a second song registry row.
            app._shared_drive_playback_song = {
                "id": -1, "path": path,
                "code": str(song.get("code") or ""),
                "title": str(song.get("title") or "ไม่ระบุชื่อเพลง"),
                "artist": str(song.get("artist") or ""),
                "kind": "MIDI" if Path(path).suffix.lower() in
                        (".mid", ".midi", ".kar", ".emk", ".xsk", ".xmid") else "AUDIO",
                "favorite": 0, "format": str(song.get("source_format") or "")
            }
            if not app.start_song(QueueItem(-1)):
                raise ValueError("เครื่องเล่น PC ยังไม่สามารถเปิดเพลงนี้ได้")
        except Exception as error:
            messagebox.showerror("เปิดเพลงไม่สำเร็จ", str(error), parent=window)

    def use_shared_as_main():
        try:
            from .shared_catalog_builder import _root
            root = str(_root(selected_root.get().strip()))
        except (ValueError, OSError) as error:
            messagebox.showerror("ยังใช้ฐานร่วมไม่ได้", str(error), parent=window)
            return
        from .shared_catalog_builder_ui import open_builder
        open_builder(app, initial_root=root)

    def use_published_as_main():
        try:
            from .shared_song_library import validate_shared
            root = str(validate_shared(selected_root.get().strip()))
            from .shared_drive_layout import drive_folder_id
            verified_id = drive_folder_id(drive_id.get())
            if not messagebox.askyesno("ใช้ฐานที่เผยแพร่แล้ว",
                "สำเนา DB/songs.sqlite3 ที่ซิงก์จาก Google Drive ไป App/DB/songs.sqlite3 เป็นฐานหลักเมื่อเปิดโปรแกรมใหม่?\nตรวจให้ Drive ซิงก์เสร็จก่อน",
                parent=window):
                return
            app.settings["pending_shared_drive"] = {"root": root}
            app.settings["shared_drive_folder_id"] = verified_id
            app.settings.pop("pending_pc_only", None)
            app.settings.pop("pending_online_master", None)
            app.save_settings()
            summary.set("เลือกฐานร่วมที่เผยแพร่แล้ว · เปิด PC ใหม่เพื่อใช้ฐานเดียวกับ Online")
        except Exception as error:
            messagebox.showerror("ยังใช้ฐานร่วมไม่ได้",str(error),parent=window)

    def use_local_as_main():
        if not messagebox.askyesno("กลับไปใช้ฐานภายใน PC",
            "สลับกลับไปใช้ฐานเพลงภายในเครื่องเมื่อเปิดโปรแกรมใหม่? "
            "ไม่ลบฐาน Google Drive หรือคิวเพลงเดิม", parent=window):
            return
        app.settings["pending_pc_only"] = True
        app.settings.pop("pending_online_master", None)
        app.settings.pop("pending_shared_drive", None)
        app.save_settings()
        summary.set("เลือกฐานภายใน PC แล้ว · มีผลหลังเปิดโปรแกรมใหม่")

    refresh = ttk.Button(search_row, text="ตรวจฐาน / ค้นหา", command=load)
    refresh.pack(side="left", padx=(8, 0))
    search_input.bind("<Return>", lambda event: load())
    ttk.Button(actions, text="สร้างฐาน PC และสำเนา Drive", command=use_shared_as_main).pack(side="left", padx=(0,8))
    ttk.Button(actions, text="ใช้ฐานร่วมที่เผยแพร่แล้ว", command=use_published_as_main).pack(side="left", padx=(0,8))
    ttk.Button(actions, text="กลับใช้ฐานในเครื่อง", command=use_local_as_main).pack(side="left", padx=(0,8))
    ttk.Button(actions, text="เล่นจากฐาน Google Drive ใน PC", command=play_selected).pack(side="left")
    ttk.Button(actions, text="ปิด", command=window.destroy).pack(side="right")
    ttk.Label(body, text="เลือกเล่นเพลงจาก SQLite ของ Google Drive โดยตรง · ไม่เพิ่มแถวเพลงเข้า SQLite ในเครื่องหรือแก้ฐาน Online · ต้องมีไฟล์เพลงซิงก์บนเครื่อง",
              style="Muted.TLabel", wraplength=900).pack(anchor="w")

    def close():
        closing[0] = True
        revision[0] += 1
        window.destroy()
    window.protocol("WM_DELETE_WINDOW", close)
    if selected_root.get().strip():
        load()
    return window
