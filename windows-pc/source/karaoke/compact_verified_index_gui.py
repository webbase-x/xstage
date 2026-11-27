"""PC-only UI for verifying original XMIDs without changing their catalog."""
from __future__ import annotations
import json
import os
import queue
import shutil
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .compact_verified_index import build

def main():
    root = tk.Tk()
    root.title("X-Stage · Verify original XMID")
    root.geometry("850x440")
    root.minsize(680, 400)
    body = ttk.Frame(root, padding=16)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="Verify original XMID · Build 1224", font=("Segoe UI", 16, "bold")).pack(anchor="w")
    ttk.Label(body, text="Read-only source. Select the authoritative original XMID folder, not an unverified mirror.").pack(anchor="w", pady=(4, 12))
    form = ttk.Frame(body)
    form.pack(fill="x")
    form.columnconfigure(1, weight=1)
    fields = {}
    buttons = []
    def field(row, name, label, folder=False):
        value = tk.StringVar()
        fields[name] = value
        ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(form, textvariable=value).grid(row=row, column=1, sticky="ew", padx=8)
        def choose():
            p = filedialog.askdirectory() if folder else filedialog.askopenfilename(filetypes=[("SQLite", "*.sqlite3"), ("All files", "*.*")])
            if p:
                value.set(p)
                if name == "source":
                    adjacent = Path(p).with_name("songs.search.sqlite3")
                    if adjacent.is_file() and not fields["compact"].get():
                        fields["compact"].set(str(adjacent))
        b = ttk.Button(form, text="Browse", command=choose)
        b.grid(row=row, column=2)
        buttons.append(b)
    field(0,"source","Stable songs.sqlite3")
    field(1,"compact","songs.search.sqlite3")
    field(2,"original","Original XMID folder",True)
    field(3,"output","Local output folder",True)
    ttk.Label(body, text="The local verification journal survives cancellation; a complete output never overwrites an existing file.").pack(anchor="w", pady=12)
    bar = ttk.Progressbar(body, mode="determinate")
    bar.pack(fill="x", pady=5)
    status = tk.StringVar(value="Choose all four locations.")
    ttk.Label(body, textvariable=status, wraplength=800).pack(anchor="w", pady=8)
    actions = ttk.Frame(body)
    actions.pack(fill="x", pady=6)
    messages = queue.Queue()
    cancel = threading.Event()
    running = False
    closing_requested = False
    def set_running(value):
        nonlocal running
        running=value
        run.configure(state="disabled" if value else "normal")
        abort.configure(state="normal" if value else "disabled")
        for b in buttons: b.configure(state="disabled" if value else "normal")
    def start():
        if running: return
        if not all(v.get().strip() for v in fields.values()):
            messagebox.showerror("X-Stage", "Choose all four locations.");return
        p = {k:Path(v.get()).resolve() for k,v in fields.items()}
        target = p["output"] / "songs.verified.sqlite3"
        if target.exists():
            messagebox.showerror("X-Stage", "Output already exists. Select a new local output folder; no overwrite.");return
        if not messagebox.askokcancel("Original source", "Confirm that the selected XMID folder contains your authoritative original files and is not being modified during verification."):
            return
        cancel.clear()
        set_running(True)
        status.set("Verifying source database and original files…")
        def worker():
            try:
                journal = Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "XStage" / "Verification"
                journal.mkdir(parents=True,exist_ok=True)
                stats=build(p["source"],p["compact"],p["original"],target,journal/"verified-original-v1.sqlite3",
                    cancel=cancel,progress=lambda done,total: messages.put(("progress",(done,total))) if done%25==0 or done==total else None)
                with closing(sqlite3.connect(target.as_uri()+"?mode=ro&immutable=1",uri=True)) as db:
                    meta=dict(db.execute("SELECT key,value FROM catalog_meta"))
                stats["expected"]=int(meta["expectedCount"])
                stats["publishable"]=stats["verified"]==stats["expected"] and stats["rejected"]==0
                report=target.with_name("verification-result.json")
                with report.open("x",encoding="utf-8") as f: json.dump(stats,f,indent=2,ensure_ascii=False)
                messages.put(("done",(stats,target)))
            except Exception as e: messages.put(("error",str(e)))
        threading.Thread(target=worker,daemon=True).start()
    def poll():
        try:
            while True:
                kind,data=messages.get_nowait()
                if kind=="progress":
                    done,total=data
                    bar.configure(maximum=max(total,1),value=done)
                    status.set(f"Checked {done:,} / {total:,}")
                elif kind=="done":
                    stats,target=data
                    set_running(False)
                    status.set(f"Verified {stats['verified']:,} / {stats['expected']:,} · rejected {stats['rejected']:,} · reused {stats['reused']:,}")
                    if stats["publishable"]:
                        messagebox.showinfo("Verified",f"Complete output: {target}\nCopy this file to XStageKaraoke/DB only after checking the report. Source unchanged.")
                    else:
                        messagebox.showwarning("Not publishable","Some entries were rejected. Do not upload this output. Review the verification_errors table, correct the original source and rerun in a new folder. Journal retained.")
                elif kind=="error":
                    set_running(False);status.set(data)
                    if not closing_requested: messagebox.showerror("Verification stopped",data)
        except queue.Empty: pass
        if closing_requested and not running: root.destroy();return
        root.after(100,poll)
    def close():
        nonlocal closing_requested
        if running:
            closing_requested=True;cancel.set();status.set("Cancelling safely…")
        else: root.destroy()
    run=ttk.Button(actions,text="Verify originals",command=start);run.pack(side="left")
    abort=ttk.Button(actions,text="Cancel safely",command=cancel.set,state="disabled");abort.pack(side="left",padx=8)
    root.protocol("WM_DELETE_WINDOW",close)
    root.after(100,poll)
    root.mainloop()

if __name__=="__main__":main()
