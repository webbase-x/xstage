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
    ttk.Label(body, text="GOOGLE DRIVE · XSTAGEKARAOKE",
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
            title="เลือก XStageKaraoke ใน Google Drive for desktop",
            initialdir=selected_root.get() or str(Path.home()))
        if chosen:
            selected_root.set(chosen)
            load()
    ttk.Button(row, text="เลือกโฟลเดอร์ Google Drive…", command=browse).pack(side="left")
    summary = tk.StringVar(value="เลือกโฟลเดอร์ XStageKaraoke ที่ซิงก์อยู่บนเครื่อง")
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
        busy[0] = True
        summary.set("กำลังอ่าน SQLite จาก Google Drive PC (อ่านอย่างเดียว)…")
        def work():
            try:
                info = catalog.summary(root_text)
                rows = catalog.search(info["root"], query.get().strip(), 150)
                error = None
            except (OSError, ValueError, RuntimeError, Exception) as exc:
                info, rows, error = None, None, str(exc)
            def finish():
                if closing[0] or current != revision[0]:
                    return
                busy[0] = False
                if error:
                    report_error(error)
                    return
                selected_root.set(info["root"])
                app.settings["shared_drive_root"] = info["root"]
                app.save_settings()
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
        if not messagebox.askyesno("ใช้ไฟล์เพลงจาก Google Drive PC",
            "นำไฟล์นี้เข้าแค็ตตาล็อกการเล่นชั่วคราวของ PC แล้วเล่นเลย?\n"
            "ข้อมูลเพลงหลักยังอ่านจาก DB/songs.sqlite3 บน Google Drive และไม่แก้ไขฐานนั้น",
            parent=window):
            return
        try:
            from .library import QueueItem
            ids = app.library.add_files([Path(path)])
            if not ids:
                raise ValueError("ไฟล์ชนิดนี้ยังเล่นผ่านเครื่องเล่น PC ไม่ได้")
            app.start_song(QueueItem(int(ids[0])))
        except Exception as error:
            messagebox.showerror("เปิดเพลงไม่สำเร็จ", str(error), parent=window)

    refresh = ttk.Button(search_row, text="ตรวจฐาน / ค้นหา", command=load)
    refresh.pack(side="left", padx=(8, 0))
    search_input.bind("<Return>", lambda event: load())
    ttk.Button(actions, text="เล่นไฟล์ที่เลือกใน PC", command=play_selected).pack(side="left")
    ttk.Button(actions, text="ปิด", command=window.destroy).pack(side="right")
    ttk.Label(body, text="การเล่นไฟล์อาจใช้ดัชนีภายใน PC เพื่อคิวและประวัติ แต่ไม่มีการเขียน DB/songs.sqlite3 ของ Google Drive",
              style="Muted.TLabel", wraplength=900).pack(anchor="w")

    def close():
        closing[0] = True
        revision[0] += 1
        window.destroy()
    window.protocol("WM_DELETE_WINDOW", close)
    if selected_root.get().strip():
        load()
    return window
