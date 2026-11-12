"""Fast, crash-safe local song publishing for X-Stage Song Studio PC.

Works entirely on the user's PC. Immutable per-digit JSON catalogs are switched
through songs/current.json only when all required media for a batch exists.
This is a *local path index*. It does not fabricate Google Drive file IDs;
Drive publication must upload files and then publish a Drive-specific pointer.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path

CATALOG_SCHEMA = 1
JOURNAL_NAME = ".build-journal.jsonl"

def canonical_source_path(path: str | Path) -> str:
    """Stable identity across restarts on Windows (including case-only changes)."""
    return str(Path(path).expanduser().resolve()).replace("\\", "/").casefold()


def source_sha256(path: str | Path) -> str:
    """Full-file fingerprint catches copied/renamed originals; streamed, bounded RAM."""
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def source_marker(path: str | Path, sha256: str) -> dict:
    file = Path(path)
    return {
        "canonicalPath": canonical_source_path(file),
        "sha256": sha256,
        "bytes": file.stat().st_size,
    }

CATALOG_FORMAT = "xstage-local-catalog"
CURRENT_FORMAT = "xstage-local-current"
TIMESTAMP_RE = re.compile(r"\[(\d{1,3}):(\d\d)(?:[.:](\d{1,3}))?\]")
OFFSET_RE = re.compile(r"^\[offset:([+-]?\d+)\]$", re.I)


def source_bucket(source_filename: str) -> str:
    """First ASCII digit in the ORIGINAL source filename; '_' for none."""
    for char in Path(source_filename).stem:
        if "0" <= char <= "9":
            return char
    return "_"


def safe_filename(value: str) -> str:
    result = "".join("_" if char in '<>:"/\\|?*\0' or ord(char) < 32 else char
                     for char in str(value)).strip(" .")[:140]
    return result or "song"


def songs_root(workspace: str | Path) -> Path:
    path = Path(workspace).expanduser()
    return path if path.name.lower() == "songs" else path / "songs"


def next_target(root: Path, source_filename: str) -> Path:
    """Reserve a *name*, not a file; use one writer job at a time."""
    bucket = source_bucket(source_filename)
    folder = root / "audio" / bucket
    folder.mkdir(parents=True, exist_ok=True)
    base = safe_filename(Path(source_filename).stem)
    for counter in range(1, 100001):
        suffix = f" ({counter})" if counter > 1 else ""
        target = folder / (base + suffix + ".m4a")
        lyric = root / "lyrics" / bucket / (base + suffix + ".json")
        if not target.exists() and not lyric.exists():
            return target
    raise RuntimeError("มีไฟล์ชื่อเดียวกันเกินขีดจำกัด 100,000 รายการ")


def temporary_audio(target: Path) -> Path:
    """Same-directory staging; FFmpeg still sees .m4a as output extension."""
    return target.parent / (".xstage-" + secrets.token_hex(12) + ".m4a")


def commit_audio(staged: Path, target: Path) -> None:
    """No silent overwrites; finalize only complete audio files."""
    if not staged.is_file() or staged.stat().st_size < 1000:
        raise RuntimeError("ไฟล์เสียง M4A ที่สร้างไม่สมบูรณ์")
    if target.exists():
        raise FileExistsError(f"ไฟล์เพลงมีอยู่แล้ว: {target}")
    try:
        # Atomic hardlink creation prevents overwrites on local NTFS.
        os.link(staged, target)
    except FileExistsError:
        raise
    except OSError:
        # Fallback for filesystems without hardlinks (e.g. exFAT/SMB).
        # O_EXCL keeps the no-overwrite contract, and indexing happens later.
        import shutil
        with open(staged, "rb") as source, target.open("xb") as output:
            try:
                shutil.copyfileobj(source, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
            except BaseException:
                output.close()
                target.unlink(missing_ok=True)
                raise
    staged.unlink(missing_ok=True)


def lyric_paths(root: Path, audio_file: Path) -> tuple[Path, Path]:
    folder = root / "lyrics" / audio_file.parent.name
    return folder / (audio_file.stem + ".json"), folder / (audio_file.stem + ".lrc")


WORD_TIMESTAMP_RE = re.compile(r"<(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?>")

def _lrc_seconds(match):
    second = int(match.group(2))
    if second >= 60:
        return None
    frac = match.group(3) or "0"
    return round(int(match.group(1)) * 60 + second +
                 int(frac) / (10 ** len(frac)), 4)


def lrc_to_json(text: str, code: str) -> dict:
    """Keep original LRC; preserve genuine enhanced-LRC syllable cue times.

    Plain LRC has line starts only: it MUST NOT invent per-word timestamps.
    Enhanced LRC <mm:ss.xx> has real token starts, converted to the
    X-Stage Karaoke PC/Web 'syllables' JSON schema for karaoke highlighting.
    """
    lines = []
    offset_ms = 0
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        value = raw.strip()
        if not value:
            continue
        match = OFFSET_RE.match(value)
        if match:
            offset_ms = int(match.group(1))
            continue
        stamps = list(TIMESTAMP_RE.finditer(value))
        if not stamps:
            continue
        caption = TIMESTAMP_RE.sub("", value)
        cues = list(WORD_TIMESTAMP_RE.finditer(caption))
        lyric = WORD_TIMESTAMP_RE.sub("", caption).strip()
        if not lyric:
            continue
        base_seconds = _lrc_seconds(stamps[0])
        if base_seconds is None:
            continue
        tokens = []
        if cues:
            lead = caption[:cues[0].start()]
            if lead:
                tokens.append((base_seconds, lead))
            for i, cue in enumerate(cues):
                begin = _lrc_seconds(cue)
                if begin is None:
                    continue
                stop = cues[i+1].start() if i+1 < len(cues) else len(caption)
                part = caption[cue.end():stop]
                if part:
                    tokens.append((begin, part))
        for stamp in stamps:
            when = _lrc_seconds(stamp)
            if when is None:
                continue
            row = {"startTime": when, "text": lyric}
            if tokens:
                # Multiple [timestamp] tags repeat a line; word events move
                # by the exact same delta rather than staying at the first.
                shift = when - base_seconds
                row["_tokens"] = [(round(t + shift, 4), segment)
                                  for t, segment in tokens]
            lines.append(row)
    lines.sort(key=lambda item: item["startTime"])
    for i, line in enumerate(lines):
        next_time = lines[i+1]["startTime"] if i+1 < len(lines) else line["startTime"] + 4
        line["endTime"] = round(max(line["startTime"] + .05, next_time), 3)
        tokens = line.pop("_tokens", None)
        if tokens:
            syllables = []
            for j, (cue, segment) in enumerate(tokens):
                finish = min(line["endTime"], tokens[j+1][0]) \
                    if j+1 < len(tokens) else line["endTime"]
                syllables.append({
                    "text": segment, "start": cue,
                    "duration": round(max(0., finish-cue), 4)
                })
            line["syllables"] = syllables
    return {
        "schemaVersion": 1,
        "songCode": code,
        "audioOffsetMs": offset_ms,
        "lines": lines,
        "rawLrc": text,
    }


def atomic_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Do not write an incomplete JSON file under the final name.
    handle = tempfile.NamedTemporaryFile("w", dir=path.parent, suffix=".tmp",
                                         prefix=".xstage-", encoding="utf-8",
                                         newline="\n", delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(document, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def save_lyrics(root: Path, audio: Path, text: str, code: str,
                *, document: dict | None = None, repair: bool = False) -> Path:
    """Save lyrics only when real timestamps are present; no empty fake JSON.

    NCN/KAR parsers can provide source-accurate timed JSON via document.
    A repair preserves the prior generated JSON/LRC in a sibling backup.
    Original MIDI, LYR and CUR files are never modified.
    """
    json_file, lrc_file = lyric_paths(root, audio)
    parsed = document if document is not None else lrc_to_json(text, code)
    if not isinstance(parsed, dict) or not parsed.get("lines"):
        raise ValueError("ไม่มีเนื้อร้องพร้อมเวลาจริง · ไม่สร้าง Lyrics JSON ว่าง")
    if not isinstance(parsed["lines"], list):
        raise ValueError("รูปแบบเนื้อร้องไม่ถูกต้อง")
    if not repair and (json_file.exists() or lrc_file.exists()):
        raise FileExistsError(f"ไฟล์เนื้อร้องมีอยู่แล้ว: {json_file}")
    json_file.parent.mkdir(parents=True, exist_ok=True)
    if repair:
        # Back up generated output once per repair attempt. Manual corrections
        # must not be silently destroyed by a reimport.
        import shutil
        suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        for old in (json_file, lrc_file):
            if old.is_file():
                backup = old.with_name(old.name + ".before-repair-" + suffix + ".bak")
                shutil.copy2(old, backup)
    raw_lrc = str(parsed.get("rawLrc") or text)
    atomic_json(json_file, parsed)
    if raw_lrc.strip():
        temporary = lrc_file.with_name("." + lrc_file.name + "." + secrets.token_hex(6) + ".tmp")
        try:
            temporary.write_text(raw_lrc, encoding="utf-8")
            os.replace(temporary, lrc_file)
        finally:
            temporary.unlink(missing_ok=True)
    return json_file


def make_record(root: Path, row: dict, audio: Path, lyrics: Path | None,
                vocals: Path | None, mode: str) -> dict:
    source = Path(row["path"])
    bucket = source_bucket(source.name)
    if audio.parent.name != bucket:
        raise ValueError("ตำแหน่งเพลงไม่ตรงกับเลขแรกของชื่อไฟล์ต้นฉบับ")
    rel = lambda p: p.relative_to(root).as_posix() if p is not None else None
    code = str(row.get("code") or source.stem)
    return {
        "webSongId": audio.relative_to(root).with_suffix("").as_posix(),
        "code": code,
        "title": str(row.get("title") or source.stem),
        "artist": str(row.get("artist") or ""),
        "sourceFormat": str(row.get("source_format") or source.suffix.lstrip(".").upper()),
        "audio": {"path": rel(audio), "size": audio.stat().st_size},
        "lyrics": {"path": rel(lyrics)} if lyrics else None,
        "vocals": {"path": rel(vocals)} if vocals else None,
        "mode": mode, "bucket": bucket,
    }


def _read_current(root: Path) -> tuple[dict, dict[str, dict]]:
    pointer_path = root / "current.json"
    if not pointer_path.is_file():
        return {}, {}
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ValueError("current.json เดิมเสียหาย: ไม่เขียนทับฐานข้อมูล") from exc
    if pointer.get("schemaVersion") != CATALOG_SCHEMA or pointer.get("format") != CURRENT_FORMAT:
        raise ValueError("current.json เป็นรูปแบบอื่น: ไม่เขียนทับฐานข้อมูลเดิม")
    current = {}
    files = pointer.get("catalogFiles")
    if not isinstance(files, list) or len(files) > 11:
        raise ValueError("current.json มีรายการ catalog ไม่ถูกต้อง")
    for meta in files:
        if not isinstance(meta, dict):
            raise ValueError("catalog metadata ไม่ถูกต้อง")
        bucket, relative = meta.get("bucket"), meta.get("path")
        if bucket not in set("0123456789_") or bucket in current:
            raise ValueError("ชื่อกลุ่ม catalog ไม่ถูกต้องหรือซ้ำ")
        expected_prefix = f"catalogs/database-{bucket}-"
        if not isinstance(relative, str) or not relative.startswith(expected_prefix) or not relative.endswith(".json"):
            raise ValueError("พาธ catalog ไม่ถูกต้อง")
        p = root / relative
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"อ่าน catalog เดิมไม่สำเร็จ: {p}") from exc
        if (data.get("schemaVersion") != CATALOG_SCHEMA or data.get("bucket") != bucket
                or not isinstance(data.get("songs"), list)):
            raise ValueError(f"catalog เดิมไม่ถูกต้อง: {p}")
        current[bucket] = data
    if sum(len(data["songs"]) for data in current.values()) != pointer.get("songCount"):
        raise ValueError("จำนวนเพลงใน current.json ไม่ตรงกับ catalog")
    return pointer, current



def safe_media_path(root: Path, rel: str, kind: str) -> Path:
    """Prevent catalog and journal paths from pointing outside the songs root."""
    if not isinstance(rel, str) or "\\\\" in rel or "\\0" in rel:
        raise ValueError("พาธไฟล์เพลงไม่ถูกต้อง")
    path = (root / rel).resolve()
    if not path.is_relative_to(root.resolve()) or not rel.startswith(kind + "/"):
        raise ValueError("พาธ catalog อ้างถึงไฟล์นอกคลังเพลง")
    return path


def record_is_complete(root: Path, record: dict) -> bool:
    """Only a fully published audio/lyrics/vocals set can block rebuilding."""
    try:
        audio = safe_media_path(root, record["audio"]["path"], "audio")
        if not audio.is_file() or audio.stat().st_size < 1000:
            return False
        lyric = record.get("lyrics")
        if lyric:
            companion = safe_media_path(root, lyric["path"], "lyrics")
            if not companion.is_file():
                return False
            # Ensure the lyrics document is complete and readable.
            parsed = json.loads(companion.read_text(encoding="utf-8-sig"))
            if (not isinstance(parsed, dict)
                    or not isinstance(parsed.get("lines"), list)
                    or not parsed["lines"]):
                return False
        if record.get("mode") == "instrumental" and not record.get("vocals"):
            return False
        vocal = record.get("vocals")
        if vocal:
            vocal_file = safe_media_path(root, vocal["path"], "audio")
            if not vocal_file.is_file() or vocal_file.stat().st_size < 1000:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def journal_records(root: Path) -> list[dict]:
    """Recover completed work from a crashed/stopped run before catalog switch."""
    path = root / JOURNAL_NAME
    if not path.exists():
        return []
    entries = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                # Power loss can leave an incomplete trailing line. Retain the
                # file for diagnostics; do not delete earlier complete entries.
                continue
            if isinstance(record, dict) and record.get("webSongId") and record_is_complete(root, record):
                entries.append(record)
    return entries


def append_journal(root: Path, record: dict) -> None:
    """Durably checkpoint one completed song before handling the next song."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / JOURNAL_NAME
    needs_newline = False
    if path.is_file() and path.stat().st_size:
        with path.open("rb") as previous:
            previous.seek(-1, 2)
            needs_newline = previous.read(1) != b"\n"
    with path.open("a", encoding="utf-8") as stream:
        if needs_newline:
            stream.write("\n")
        stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def existing_records(root: Path) -> list[dict]:
    """Read durable pointer + crash journal; no dependence on process memory."""
    _, buckets = _read_current(root)
    by_id = {row["webSongId"]: row for bucket in buckets.values()
             for row in bucket["songs"] if isinstance(row, dict) and row.get("webSongId")}
    for row in journal_records(root):
        by_id[row["webSongId"]] = row
    return list(by_id.values())


def find_duplicate(root: Path, records: list[dict],
                   source_path: str | Path, sha256: str | None = None) -> dict | None:
    """Path prevents repeat-run duplicates; SHA also catches moved/renamed copies.

    Incomplete catalog entries are intentionally NOT considered duplicates:
    callers may repair them with the original output path rather than produce
    a second filename.
    """
    canonical = canonical_source_path(source_path)
    for row in records:
        marker = row.get("sourceIdentity") or {}
        if marker.get("canonicalPath") == canonical and record_is_complete(root, row):
            return row
    if sha256:
        for row in records:
            marker = row.get("sourceIdentity") or {}
            if marker.get("sha256") == sha256 and record_is_complete(root, row):
                return row
    return None


def find_incomplete(root: Path, records: list[dict], source_path: str | Path) -> dict | None:
    canonical = canonical_source_path(source_path)
    for row in records:
        if (row.get("sourceIdentity") or {}).get("canonicalPath") == canonical and not record_is_complete(root, row):
            return row
    return None


def clear_published_journal(root: Path) -> None:
    """Only clear after current.json atomically points at published records."""
    (root / JOURNAL_NAME).unlink(missing_ok=True)

def publish_batch(root: Path, records: list[dict]) -> dict:
    """One atomic pointer switch for an entire batch; no O(n²) per-song rewrites.

    Untouched buckets continue pointing to their previous immutable catalog.
    Catalog files are never overwritten. If interrupted before switching the
    pointer, the previous song library remains valid.
    """
    root = Path(root)
    if not records:
        pointer, _ = _read_current(root)
        return pointer
    previous, old_buckets = _read_current(root)
    staged_by_bucket: dict[str, dict[str, dict]] = {}
    for row in records:
        bucket = row["bucket"]
        if bucket not in set("0123456789_"):
            raise ValueError("catalog bucket ไม่ถูกต้อง")
        if not (root / row["audio"]["path"]).is_file():
            raise FileNotFoundError("ไม่พบไฟล์เสียงสำหรับ catalog: " + row["audio"]["path"])
        if row.get("lyrics") and not (root / row["lyrics"]["path"]).is_file():
            raise FileNotFoundError("ไม่พบเนื้อร้องสำหรับ catalog")
        if row.get("vocals") and not (root / row["vocals"]["path"]).is_file():
            raise FileNotFoundError("ไม่พบไฟล์เสียงร้องสำหรับ catalog")
        staged_by_bucket.setdefault(bucket, {})[row["webSongId"]] = row

    generation = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + secrets.token_hex(4)
    catalog_refs = []
    song_count = 0
    for bucket in sorted(set(old_buckets) | set(staged_by_bucket)):
        if bucket not in staged_by_bucket:
            # Keep old immutable catalog exactly; avoid a slow rewrite.
            old_path = next(x["path"] for x in previous["catalogFiles"] if x["bucket"] == bucket)
            count = len(old_buckets[bucket]["songs"])
            catalog_refs.append({"bucket": bucket, "path": old_path, "songCount": count})
            song_count += count
            continue
        combined = {record["webSongId"]: record for record in
                    old_buckets.get(bucket, {}).get("songs", [])
                    if isinstance(record, dict) and "webSongId" in record}
        combined.update(staged_by_bucket[bucket])
        songs = sorted(combined.values(), key=lambda item: item["webSongId"])
        path = root / "catalogs" / f"database-{bucket}-{generation}.json"
        atomic_json(path, {
            "schemaVersion": CATALOG_SCHEMA, "format": CATALOG_FORMAT,
            "bucket": bucket, "generation": generation, "songs": songs
        })
        catalog_refs.append({
            "bucket": bucket, "path": path.relative_to(root).as_posix(),
            "songCount": len(songs)
        })
        song_count += len(songs)
    pointer = {
        "schemaVersion": CATALOG_SCHEMA, "format": CURRENT_FORMAT,
        "generation": generation, "songCount": song_count,
        "catalogFiles": catalog_refs,
        "publishedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "Local relative paths only; Google Drive file IDs must be assigned after verified upload."
    }
    atomic_json(root / "current.json", pointer)
    return pointer
