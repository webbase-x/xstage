"""Bounded producer/consumer discovery for incremental MIDI-to-XSK batches.

Discover in one thread while the authenticated XSK builder consumes prior batches.
No full upfront source scan, no source modification, no unbounded in-memory list.
An unreadable source directory fails the job rather than silently omitting songs.
"""
from __future__ import annotations

import os
import queue
import threading
from contextlib import contextmanager
from pathlib import Path

EXTENSIONS = {".mid", ".midi", ".kar"}


@contextmanager
def source_batches(source, destination, *, cancelled, on_scan=None,
                   batch_size=32, max_batches=4):
    if type(batch_size) is not int or not 1 <= batch_size <= 256:
        raise ValueError("ขนาดชุด MIDI ต้องอยู่ระหว่าง 1–256 เพลง")
    if type(max_batches) is not int or not 1 <= max_batches <= 16:
        raise ValueError("ขนาดคิว MIDI ไม่ถูกต้อง")
    source = Path(source).expanduser()
    destination = Path(destination).expanduser()
    if not source.is_dir() or source.is_symlink():
        raise ValueError("ไม่พบโฟลเดอร์ MIDI ต้นทาง หรือเป็น Symbolic Link")
    if destination.is_symlink():
        raise ValueError("ไม่อนุญาตโฟลเดอร์ปลายทางแบบ Symbolic Link")
    source_real, destination_real = source.resolve(), destination.resolve()
    if source_real == destination_real or destination_real in source_real.parents:
        raise ValueError("ปลายทาง XSK ต้องไม่เป็นโฟลเดอร์หลักหรือโฟลเดอร์แม่ของ MIDI")
    output = destination_real / "MIDI" / "XSK"
    inbox = queue.Queue(maxsize=max_batches)
    stopped = threading.Event()
    completed = threading.Event()
    problems = []
    state = {"files": 0, "found": 0, "batches": 0}

    def is_cancelled():
        return stopped.is_set() or (cancelled is not None and cancelled.is_set())

    def enqueue(items):
        if not items:
            return
        while not is_cancelled():
            try:
                inbox.put(items[:], timeout=.2)
                state["batches"] += 1
                if on_scan is not None:
                    on_scan(dict(state), False, inbox.qsize())
                return
            except queue.Full:
                pass

    def produce():
        batch = []
        folders = [source]
        try:
            while folders and not is_cancelled():
                folder = folders.pop()
                # Do not let the generated XSK outputs get scanned as inputs,
                # even when user selected an ancestor folder.
                resolved = folder.resolve()
                if resolved == destination_real or destination_real in resolved.parents:
                    continue
                try:
                    listing = os.scandir(folder)
                except OSError as exc:
                    raise RuntimeError("อ่านโฟลเดอร์ย่อยไม่ได้: " + str(folder)) from exc
                children = []
                with listing:
                    for entry in listing:
                        if is_cancelled():
                            break
                        try:
                            if entry.is_symlink():
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                candidate = Path(entry.path)
                                if candidate.resolve() != destination_real and not (
                                        destination_real in candidate.resolve().parents):
                                    children.append(candidate)
                                continue
                            if not entry.is_file(follow_symlinks=False):
                                continue
                        except OSError as exc:
                            raise RuntimeError("ตรวจรายการไฟล์ไม่ได้: " + entry.path) from exc
                        state["files"] += 1
                        if Path(entry.name).suffix.lower() not in EXTENSIONS:
                            continue
                        state["found"] += 1
                        path = Path(entry.path)
                        batch.append({"path": str(path), "code": path.stem,
                                      "title": path.stem, "artist": "",
                                      "kind": path.suffix.lstrip(".").upper()})
                        if len(batch) >= batch_size:
                            enqueue(batch)
                            batch.clear()
                if batch:
                    # Start the first batch even when this directory has only
                    # a few MIDI files; discovery continues in other folders.
                    enqueue(batch)
                    batch.clear()
                if on_scan is not None:
                    on_scan(dict(state), False, inbox.qsize())
                folders.extend(reversed(sorted(children, key=lambda p: p.name.casefold())))
            if batch and not is_cancelled():
                enqueue(batch)
        except BaseException as exc:
            problems.append(exc)
        finally:
            completed.set()
            if on_scan is not None:
                on_scan(dict(state), True, inbox.qsize())

    thread = threading.Thread(target=produce, daemon=True,
                              name="xstage-xsk-midi-discovery")
    thread.start()

    def consume():
        while True:
            if cancelled is not None and cancelled.is_set():
                raise RuntimeError("ผู้ใช้ยกเลิกการสแกนและสร้าง .XSK")
            try:
                part = inbox.get(timeout=.2)
            except queue.Empty:
                if completed.is_set():
                    if problems:
                        raise RuntimeError("สแกน MIDI ไม่ครบ: " + str(problems[0])) from problems[0]
                    return
                continue
            for row in part:
                if cancelled is not None and cancelled.is_set():
                    raise RuntimeError("ผู้ใช้ยกเลิกการสร้าง .XSK")
                yield row

    try:
        yield consume()
    finally:
        stopped.set()
        thread.join(timeout=5)
