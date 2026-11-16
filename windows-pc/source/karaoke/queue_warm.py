"""Bounded background warmup for Karaoke PC's LOCAL queue.

PC songs already live on disk: do NOT duplicate a full MP3/video/XSK in RAM.
Read only small file headers into a capped per-session cache, letting Windows
manage the page cache. Real Windows available physical RAM is reported only
when GlobalMemoryStatusEx succeeds. Audio/SoundFont native resources remain
owned by their playback engines and are never touched by this worker.
"""
from __future__ import annotations

import ctypes
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from pathlib import Path

MiB = 1024 * 1024
MAX_ITEMS = 2
MAX_HEADER = 64 * 1024
MAX_HELD = MAX_ITEMS * MAX_HEADER


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def physical_memory():
    """Return actual Windows RAM measurements, or None (never invent values)."""
    if os.name != "nt":
        return None
    try:
        stats = MEMORYSTATUSEX()
        stats.dwLength = ctypes.sizeof(stats)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
        kernel.GlobalMemoryStatusEx.restype = wintypes.BOOL
        if not kernel.GlobalMemoryStatusEx(ctypes.byref(stats)):
            return None
        if not stats.ullTotalPhys:
            return None
        return {"total": int(stats.ullTotalPhys),
                "available": int(stats.ullAvailPhys),
                "used_percent": int(stats.dwMemoryLoad)}
    except (AttributeError, OSError, ValueError):
        return None


def memory_level(info):
    if not info:
        return "unknown"
    ratio = info["available"] / max(info["total"], 1)
    return ("high" if ratio < .16 or info["available"] < 512 * MiB else
            "medium" if ratio < .30 else "low")


class QueueWarmup:
    """At most two shallow reads; never opens audio devices or holds full songs."""

    def __init__(self):
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="xstage-pc-warm")
        self._future = None
        self._paths = ()
        self._headers = {}
        self._closed = False
        self._generation = 0

    def request(self, paths):
        normalized = tuple(str(Path(p)) for p in paths[:MAX_ITEMS])
        with self._lock:
            if self._closed or self._paths == normalized:
                return
            self._generation += 1
            generation = self._generation
            self._paths = normalized
            self._headers = {p: data for p, data in self._headers.items()
                             if p in normalized}
            if self._future is not None and not self._future.done():
                self._future.cancel()
            self._future = self._pool.submit(self._warm, normalized, generation)

    def _warm(self, paths, generation):
        if memory_level(physical_memory()) == "high":
            with self._lock:
                if generation == self._generation:
                    self._headers.clear()
            return
        for path in paths:
            with self._lock:
                if self._closed or generation != self._generation:
                    return
                if path in self._headers:
                    continue
            try:
                file = Path(path)
                if not file.is_file() or file.is_symlink():
                    continue
                # Each read is bounded independently of the song file size.
                with file.open("rb") as source:
                    head = source.read(MAX_HEADER)
            except OSError:
                continue
            with self._lock:
                if self._closed or generation != self._generation:
                    return
                if sum(map(len, self._headers.values()))+len(head) <= MAX_HELD:
                    self._headers[path] = head

    def snapshot(self):
        with self._lock:
            bytes_held = sum(map(len, self._headers.values()))
            count = len(self._headers)
        ram = physical_memory()
        return {"count": count, "bytes": bytes_held, "ram": ram,
                "level": memory_level(ram)}

    def close(self):
        with self._lock:
            self._closed = True
            self._generation += 1
            self._paths = ()
            self._headers.clear()
            if self._future is not None:
                self._future.cancel()
        self._pool.shutdown(wait=False, cancel_futures=True)
