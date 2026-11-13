"""Two-source, non-destructive song-code reconciliation for X-Stage Song Studio.

Remote XStageWeb codes take precedence when they identify DIFFERENT audio.
No existing audio file is ever overwritten/renamed: immutable local catalogs
receive an updated code + new generated lyrics JSON referencing the same audio.
The source's filename and original code are preserved for traceability.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

NUMERIC = re.compile(r"^[0-9]{1,12}$")


class CodeConflict(RuntimeError):
    pass


def media_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def codes_of(rows):
    return {str(row.get("code") or "").strip() for row in rows
            if isinstance(row, dict) and str(row.get("code") or "").strip()}


class CodeAllocator:
    """Allocate unique codes using both local and remote existing catalogs.

    Missing numbers between occupied IDs are preferred, then append to the
    highest used number of the same width. This does NOT free codes or delete
    historical songs. User-defined alphanumeric unique codes stay unchanged.
    """

    def __init__(self, local_rows, online_rows, local_songs: Path):
        self.root = Path(local_songs)
        self.local = list(local_rows)
        self.online = list(online_rows)
        self.remote_by_code = defaultdict(list)
        self.local_by_code = defaultdict(list)
        for row in self.online:
            self.remote_by_code[str(row.get("code") or "").casefold()].append(row)
        for row in self.local:
            self.local_by_code[str(row.get("code") or "").casefold()].append(row)
        self.used = {code.casefold() for code in codes_of([*self.online, *self.local])}
        self.audio_cache = {}
        widths = defaultdict(int)
        for code in codes_of([*self.online, *self.local]):
            if NUMERIC.fullmatch(code):
                widths[len(code)] += 1
        self.default_width = max(widths, key=lambda w: (widths[w], w)) if widths else 6
        self.changed = []
        self.allocated = []

    def _same_audio(self, local, remote):
        local_path = (local.get("audio") or {}).get("path")
        if not isinstance(local_path, str):
            return False
        try:
            path = (self.root / local_path).resolve()
            if (not path.is_relative_to(self.root.resolve()) or
                    not path.is_file() or not local_path.startswith("audio/")):
                return False
            if local_path not in self.audio_cache:
                self.audio_cache[local_path] = media_md5(path)
            other = (remote.get("audio") or {}).get("md5Checksum")
            return isinstance(other, str) and other.casefold() == self.audio_cache[local_path]
        except OSError:
            return False

    def _new_code(self, suggested):
        suggested = str(suggested or "")
        width = len(suggested) if NUMERIC.fullmatch(suggested) else self.default_width
        used_numbers = sorted({int(c) for c in self.used
                               if len(c) == width and NUMERIC.fullmatch(c)})
        if used_numbers:
            # Never allocate below the lowest previously-used number. Filling
            # true gaps from BOTH sources is the first preference.
            candidate = used_numbers[0]
            for occupied in used_numbers:
                if occupied > candidate:
                    break
                candidate = occupied + 1
        else:
            candidate = 1
        if candidate >= 10 ** width:
            raise CodeConflict("รหัสตัวเลขครบช่วงความยาว " + str(width) + " หลัก")
        assigned = str(candidate).zfill(width)
        if assigned.casefold() in self.used:
            raise CodeConflict("ไม่สามารถจัดสรรรหัสที่ไม่ซ้ำได้")
        self.used.add(assigned.casefold())
        self.allocated.append(assigned)
        return assigned

    def reconcile_existing(self):
        """Plan code fixes for previously built PC songs, without file writes.

        If the same code is already in Drive for the same audio bytes,
        preserve the local code. Otherwise Drive wins; local gets a new code.
        For a local-only duplicate code, keep the first record and reassign
        every DIFFERENT song after it. Equal audio is left for review.
        """
        for key, rows in sorted(self.local_by_code.items()):
            remote = self.remote_by_code.get(key, [])
            winner = None
            if remote:
                for local in rows:
                    if any(self._same_audio(local, item) for item in remote):
                        winner = local
                        break
            else:
                winner = rows[0] if rows else None
            for local in rows:
                if local is winner:
                    continue
                if not remote and winner is not None and self._same_local_audio(local, winner):
                    continue
                assigned = self._new_code(local.get("code"))
                self.changed.append((local, assigned))
        return list(self.changed)

    def _same_local_audio(self, first, second):
        a = (first.get("audio") or {}).get("path")
        b = (second.get("audio") or {}).get("path")
        if not a or not b:
            return False
        try:
            for relative in (a, b):
                if relative not in self.audio_cache:
                    path = (self.root / relative).resolve()
                    if (not relative.startswith("audio/") or
                            not path.is_relative_to(self.root.resolve())):
                        return False
                    self.audio_cache[relative] = media_md5(path)
            return self.audio_cache[a] == self.audio_cache[b]
        except OSError:
            return False

    def assign_new(self, preferred):
        """Assign a new song code, considering remote + existing + prior picks."""
        preferred = str(preferred or "").strip()
        if preferred and preferred.casefold() not in self.used:
            self.used.add(preferred.casefold())
            return preferred
        return self._new_code(preferred)


def apply_changes(root: Path, changes, export):
    """Journal then publish immutable catalog remaps without touching M4A.

    Rewrites only the *generated* lyrics JSON to a new unique path, keeping
    manual LRC text and all source components unmodified. Existing pointer
    remains valid until immutable catalog + journal have been written.
    """
    root = Path(root).resolve()
    count = 0
    for original, new_code in changes:
        old = str(original.get("code") or "")
        if old == new_code:
            continue
        if not export.record_is_complete(root, original):
            raise CodeConflict("ไฟล์เพลงเดิมไม่ครบ · ไม่เปลี่ยนรหัส " + old)
        row = dict(original)
        row["code"] = new_code
        row["originalCode"] = str(original.get("originalCode") or old)
        row["codeReassignedFrom"] = old
        row["codeVerifiedFrom"] = "pc-and-drive"
        lyrics = original.get("lyrics")
        if lyrics and lyrics.get("path"):
            old_file = export.safe_media_path(root, lyrics["path"], "lyrics")
            doc = json.loads(old_file.read_text(encoding="utf-8-sig"))
            if not doc.get("lines"):
                raise CodeConflict("Lyrics เดิมไม่มีข้อมูลพร้อมเวลา · ไม่เปลี่ยนรหัส")
            stem = old_file.stem + ".assigned-" + new_code
            output = old_file.with_name(stem + ".json")
            if output.exists():
                # Reused remap from a prior interrupted run must be identical.
                current = json.loads(output.read_text(encoding="utf-8-sig"))
                if current.get("songCode") != new_code or current.get("lines") != doc["lines"]:
                    raise CodeConflict("พบ Lyrics ชื่อใหม่อยู่แล้วแต่ข้อมูลต่างกัน")
            else:
                doc["songCode"] = new_code
                export.atomic_json(output, doc)
            row["lyrics"] = {"path": output.relative_to(root).as_posix()}
            old_lrc = old_file.with_suffix(".lrc")
            new_lrc = output.with_suffix(".lrc")
            if old_lrc.is_file() and not new_lrc.exists():
                with old_lrc.open("rb") as source, new_lrc.open("xb") as target:
                    shutil.copyfileobj(source, target, length=1024*1024)
        export.append_journal(root, row)
        count += 1
    if count:
        # Publish *all* pending journal rows, including prior interrupted jobs.
        pending = export.journal_records(root)
        export.publish_batch(root, pending)
        export.clear_published_journal(root)
    return count
