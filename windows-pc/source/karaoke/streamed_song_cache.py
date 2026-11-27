"""Verified disk cache for packed XMID/XSK on streamed Google Drive folders."""
from __future__ import annotations
import hashlib
import json
import os
import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MIB = 1024 * 1024
MAX_BYTES = 512 * MIB
CHUNK = MIB


def media_descriptor(song):
    try:
        row = song or {}
        payload = row.get("payload")
        payload = json.loads(payload) if isinstance(payload, str) else payload
        media = payload.get("xmid") or payload.get("xsk")
        digest = str(media.get("md5Checksum", "")).lower()
        size = int(media.get("size", row.get("original_file_size", 0)))
        source = Path(row["path"])
        suffix = source.suffix.lower()
        if suffix not in (".xmid", ".xsk") or not re.fullmatch("[0-9a-f]{32}", digest) or not 0 < size <= MAX_BYTES:
            return None
        return (source, digest, size, suffix)
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


class StreamedSongCache:
    """Serial queue; completed content-addressed files survive app restart.

    Never cache standalone MIDI/audio here: their external lyrics may be needed.
    Copy in bounded chunks, resume a partial only if its prefix matches source,
    check the whole MD5 and publish atomically. No source file is modified.
    """
    def __init__(self, directory, max_bytes=MAX_BYTES):
        self.root = Path(directory)
        self.max_bytes = max(1, int(max_bytes))
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="xstage-stream-cache")
        self.generation = 0
        self.requested = ()
        self.closed = False
        self.future = None

    def _target(self, desc):
        _, digest, size, suffix = desc
        return self.root / (f"{digest}-{size}{suffix}")

    def lookup(self, song):
        desc = media_descriptor(song)
        if desc is None:
            return None
        target = self._target(desc)
        try:
            if self.root.is_symlink() or target.is_symlink() or not target.is_file() or target.stat().st_size != desc[2]:
                return None
            return target
        except OSError:
            return None

    def request(self, songs):
        descriptions = tuple(dict.fromkeys(d for s in songs[:3] if (d := media_descriptor(s))))
        with self.lock:
            if self.closed or descriptions == self.requested:
                return
            self.generation += 1
            generation = self.generation
            self.requested = descriptions
            if self.future:
                self.future.cancel()
            self.future = self.executor.submit(self._run, descriptions, generation)

    def _current(self, generation):
        with self.lock:
            return not self.closed and self.generation == generation

    def _reserve(self, remaining, pinned, partial):
        # Include partials in the disk budget and evict unpinned oldest files.
        entries = [p for p in self.root.iterdir() if p.is_file() and not p.is_symlink()
                   and re.fullmatch(r"[0-9a-f]{32}-[0-9]+\.(?:xmid|xsk)(?:\.part)?", p.name)]
        total = sum(p.stat().st_size for p in entries)
        for item in sorted(entries, key=lambda p: p.stat().st_mtime_ns):
            if total + remaining <= self.max_bytes and shutil.disk_usage(self.root).free >= remaining + 32*MIB:
                break
            if item in pinned or item == partial:
                continue
            # On Windows an active decoder can hold a file; never force-delete it.
            try:
                size = item.stat().st_size
                item.unlink()
                total -= size
            except OSError:
                pass
        return total + remaining <= self.max_bytes and shutil.disk_usage(self.root).free >= remaining + 32*MIB

    def _run(self, descriptions, generation):
        if self.root.is_symlink() or getattr(self.root, "is_junction", lambda: False)():
            return
        self.root.mkdir(parents=True, exist_ok=True)
        pinned = {self._target(d) for d in descriptions}
        for desc in descriptions:
            if not self._current(generation):
                return
            try:
                self._copy(desc, generation, pinned)
            except (OSError, ValueError):
                # Keep a valid partial for the next retry, never present it as ready.
                continue

    def _copy(self, desc, generation, pinned):
        source, expected, size, _ = desc
        target = self._target(desc)
        partial = target.with_suffix(target.suffix + ".part")
        if target.is_symlink() or partial.is_symlink() or source.is_symlink():
            return
        if target.is_file() and target.stat().st_size == size:
            return
        if not source.is_file() or source.stat().st_size != size:
            return
        received = partial.stat().st_size if partial.is_file() else 0
        if received > size:
            partial.unlink()
            received = 0
        if not self._reserve(size-received, pinned, partial):
            return
        digest = hashlib.md5(usedforsecurity=False)
        # Content key identifies expected source bytes; a matching prefix
        # still has to be verified before seeking to the resumed position.
        with source.open("rb") as incoming:
            if received:
                remaining = received
                with partial.open("rb") as saved:
                    while remaining:
                        if not self._current(generation):
                            return
                        block = saved.read(min(CHUNK, remaining))
                        if not block or incoming.read(len(block)) != block:
                            remaining = -1
                            break
                        digest.update(block)
                        remaining -= len(block)
                if remaining != 0:
                    partial.unlink(missing_ok=True)
                    received = 0
                    incoming.seek(0)
                    digest = hashlib.md5(usedforsecurity=False)
            with partial.open("ab" if received else "wb") as outgoing:
                while received < size:
                    if not self._current(generation):
                        return
                    block = incoming.read(min(CHUNK, size-received))
                    if not block:
                        return
                    outgoing.write(block)
                    digest.update(block)
                    received += len(block)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            if incoming.read(1) or digest.hexdigest() != expected:
                partial.unlink(missing_ok=True)
                return
        if self._current(generation):
            os.replace(partial, target)

    def close(self):
        with self.lock:
            self.closed = True
            self.generation += 1
        self.executor.shutdown(wait=False, cancel_futures=True)
