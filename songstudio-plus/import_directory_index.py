"""Bounded import-scoped directory index; never copies media or sidecars."""
from __future__ import annotations

import os
import re
import stat
from collections import defaultdict
from pathlib import Path

_HASH = re.compile(r"(.+)-[0-9a-fA-F]{16}\Z")
_SIDE = frozenset((".lyr", ".cur", ".lrc", ".json"))


class ImportDirectoryIndex:
    """Reuse directory listings; revalidate when folder mtime changes."""

    def __init__(self, max_directories=128):
        self.max_directories = max(1, int(max_directories))
        self._cache = {}

    def _listing(self, folder):
        folder = Path(folder)
        key = str(folder)
        try:
            info = os.stat(folder)
        except OSError:
            self._cache.pop(key, None)
            return None
        if not stat.S_ISDIR(info.st_mode):
            self._cache.pop(key, None)
            return None
        stamp = (info.st_mtime_ns, info.st_size, info.st_ino)
        cached = self._cache.pop(key, None)
        if cached and cached[0] == stamp:
            self._cache[key] = cached
            return cached[1]
        names = set()
        folded = {}
        by_code = defaultdict(list)
        try:
            with os.scandir(folder) as entries:
                for item in entries:
                    try:
                        if not item.is_file(follow_symlinks=False):
                            continue
                    except OSError:
                        continue
                    name = item.name
                    names.add(name)
                    folded.setdefault(name.casefold(), name)
                    stem, ext = os.path.splitext(name)
                    ext = ext.casefold()
                    if ext not in _SIDE:
                        continue
                    by_code[(stem, ext)].append(name)
                    match = _HASH.fullmatch(stem)
                    if match:
                        by_code[(match.group(1), ext)].append(name)
        except OSError:
            return None
        listing = (names, folded, by_code)
        self._cache[key] = (stamp, listing)
        while len(self._cache) > self.max_directories:
            self._cache.pop(next(iter(self._cache)))
        return listing

    @staticmethod
    def _valid(path):
        return path if path.is_file() and not path.is_symlink() else None

    def exact(self, folder, stem, ext):
        listing = self._listing(folder)
        if listing is None:
            return None
        names, folded, _ = listing
        for suffix in (ext, ext.upper()):
            wanted = stem + suffix
            found = wanted if wanted in names else folded.get(wanted.casefold())
            if found:
                candidate = self._valid(Path(folder) / found)
                if candidate is not None:
                    return candidate
        return None

    def cloud_code(self, folder, code, ext):
        # The cloud matcher must never silently choose an ambiguous sidecar.
        if Path(folder).is_symlink():
            return None
        listing = self._listing(folder)
        if listing is None:
            return None
        matched = listing[2].get((code, ext.casefold()), ())
        if len(matched) != 1:
            return None
        return self._valid(Path(folder) / matched[0])
