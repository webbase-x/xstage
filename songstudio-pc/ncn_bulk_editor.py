"""Safe native NCN head/tail lyric editor for Song Studio PC.

NCN has Song/*.MID, Lyrics/*.LYR (CP874) and Cursor/*.CUR (uint16-le).
One CUR item precedes every nonblank lyric line, followed by one item per
original CP874 byte. An edit must change both LYR and CUR together, with
a verified preflight, ZIP backup and conservative crash recovery.

New glyphs reuse *existing timestamps of that same line* (no synthetic
interpolated beats); other lyric lines, their CUR timing and MIDI are unchanged.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import struct
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

PARTS = ("song", "lyrics", "cursor")
MIDI_TYPES = {".mid", ".midi"}
OLD_CREDIT = re.compile(r"^(?:nick[\s_-]*karaoke(?:\s+professional)?|นิค[\s_-]*คาราโอเกะ)$", re.I)


def locate(selected):
    """Identify a real NCN tree from NCN, Song, MIDI or their parent folder."""
    selected = Path(selected).expanduser().resolve()
    candidates = [selected]
    if selected.name.casefold() in PARTS:
        candidates.append(selected.parent)
    if selected.name.casefold() != "ncn":
        candidates.extend((selected / "NCN", selected / "MIDI" / "NCN"))
    for candidate in candidates:
        if not candidate.is_dir() or candidate.is_symlink():
            continue
        try:
            entries = {child.name.casefold(): child for child in candidate.iterdir()
                       if child.is_dir() and not child.is_symlink()}
        except OSError:
            continue
        if all(part in entries for part in PARTS):
            return candidate.resolve()
    # Standalone Lyrics directories can be analyzed even without Song/Cursor.
    # Replacement still requires a complete NCN triplet for every selected song.
    if selected.is_dir() and not selected.is_symlink():
        if selected.name.casefold() == "lyrics":
            return selected
        try:
            if any(p.is_file() and not p.is_symlink() and p.suffix.lower() == ".lyr"
                   for p in selected.iterdir()):
                return selected
        except OSError:
            pass
    return None


def _component(root, name, rel):
    """Validate every component before read/write; never follow symlinks."""
    if not isinstance(rel, str) or "\x00" in rel:
        raise ValueError("พาธ NCN ไม่ถูกต้อง")
    logical = PurePosixPath(rel)
    if (logical.is_absolute() or not logical.parts or
            any(part in (".", "..", "") for part in logical.parts)):
        raise ValueError("พาธ NCN อยู่นอกต้นทาง")
    if name not in PARTS:
        raise ValueError("ประเภทไฟล์ NCN ไม่ถูกต้อง")
    candidates = {item.name.casefold(): item for item in root.iterdir()
                  if item.is_dir() and not item.is_symlink()}
    if name not in candidates:
        raise ValueError("ไม่พบโฟลเดอร์ NCN/" + name)
    path = candidates[name]
    for part in logical.parts:
        # Case is preserved by relative names taken from resolve_companions.
        path = path / part
        if path.is_symlink():
            raise ValueError("ไม่อนุญาตไฟล์ NCN แบบลิงก์")
    path = path.resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("ไฟล์ NCN อยู่นอกคลังหรือไม่พบไฟล์")
    if path.suffix.lower() not in (
            MIDI_TYPES if name == "song" else {".lyr"} if name == "lyrics" else {".cur"}):
        raise ValueError("นามสกุลไฟล์ NCN ไม่ตรงประเภท")
    return path


def _lines(data):
    # Ctrl-Z after final lyric line is a DOS EOF marker; retain it byte-for-byte.
    marker = data.find(b"\x1a")
    head = data if marker < 0 else data[:marker]
    tail = b"" if marker < 0 else data[marker:]
    return head.splitlines(keepends=True), tail


def _body(row):
    return row.rstrip(b"\r\n")


def _parse(lyr_bytes, cur_bytes, bulk):
    if len(lyr_bytes) > 1024 * 1024 or len(cur_bytes) > 2 * 1024 * 1024:
        raise ValueError("NCN .LYR/.CUR ใหญ่เกินขนาดที่รองรับ")
    rows, tail = _lines(lyr_bytes)
    if len(rows) < 5:
        raise ValueError("ไฟล์ NCN .LYR ขาดข้อมูล 4 บรรทัดแรก")
    if len(cur_bytes) % 2 and cur_bytes[-1:] != b"\xff":
        raise ValueError("NCN .CUR มีไบต์ข้อมูลไม่ครบ")
    even = cur_bytes[:len(cur_bytes) - len(cur_bytes) % 2]
    values = list(struct.unpack("<" + "H" * (len(even)//2), even))
    if not values:
        raise ValueError("NCN .CUR ไม่มีเวลา")
    offsets, lines = [], []
    cursor = 0
    for index in range(4, len(rows)):
        original = _body(rows[index])
        if not original.strip():
            continue
        needed = len(original) + 1
        if cursor + needed > len(values):
            # Some Nick Karaoke libraries append an *untimed* vendor credit
            # to LYR. It is not part of the on-stage timed lyric text.
            try:
                candidate = original.decode("cp874", errors="strict").strip()
            except UnicodeError:
                candidate = ""
            if index == len(rows) - 1 and OLD_CREDIT.fullmatch(candidate):
                break
            raise ValueError("NCN CUR ไม่ครบสำหรับเนื้อร้อง · ข้ามเพื่อความปลอดภัย")
        segment = values[cursor:cursor+needed]
        if 65535 in segment or any(b < a for a, b in zip(segment, segment[1:])):
            raise ValueError("NCN CUR มีเวลาไม่สมบูรณ์หรือย้อนหลัง")
        try:
            raw_text = original.decode("cp874", errors="strict")
        except UnicodeError as exc:
            raise ValueError("NCN LYR ไม่ใช่ CP874 ที่รองรับ") from exc
        if not raw_text.strip() or "\x00" in raw_text:
            raise ValueError("NCN LYR มีข้อความที่ไม่ปลอดภัย")
        normalized = bulk._same(raw_text)
        offsets.append({"row": index, "cursor": cursor, "count": needed,
                        "raw": original, "text": normalized,
                        "times": segment})
        lines.append(normalized)
        cursor += needed
    if len(lines) < 4:
        raise ValueError("ไฟล์ NCN ไม่มีบรรทัดร้องพร้อม CUR อย่างน้อย 4 บรรทัด")
    try:
        title = _body(rows[0]).decode("cp874", errors="strict").strip()
        artist = _body(rows[1]).decode("cp874", errors="strict").strip()
    except UnicodeError as exc:
        raise ValueError("อ่านข้อมูลหัว NCN ไม่สำเร็จ") from exc
    return {"rows": rows, "tail": tail, "values": values,
            "cursorTail": cur_bytes[len(even):],
            "lines": lines, "entries": offsets, "title": title, "artist": artist}


def _matched_parts(root, midi, ncn):
    """Resolve matching MID/LYR/CUR by bucket and stem via existing NCN code."""
    companions = ncn.resolve_companions(midi)
    if not companions or companions.get("missing"):
        raise ValueError("ไฟล์ NCN ไม่ครบชุด MID + LYR + CUR")
    result = {}
    for kind, key in (("song", "midi"), ("lyrics", "lyrics"), ("cursor", "cursor")):
        path = Path(companions[key])
        # Walk each actual parent to detect any symlinked intermediate folder.
        subdir = next((child for child in root.iterdir() if child.name.casefold() == kind
                       and child.is_dir() and not child.is_symlink()), None)
        if subdir is None:
            raise ValueError("โครงสร้าง NCN ไม่ครบ")
        rel = path.relative_to(subdir).as_posix()
        validated = _component(root, kind, rel)
        result[kind] = rel
        if not validated.is_file():
            raise ValueError("ไฟล์ NCN ไม่ครบ")
    return result


def _source_files(root, record):
    return (_component(root, "song", record["song"]),
            _component(root, "lyrics", record["lyrics"]),
            _component(root, "cursor", record["cursor"]))


def _parse_lyrics_only(raw, bulk):
    """Read ONLY .LYR; no MIDI/CUR I/O, cursor interpretation or timing claims."""
    if len(raw) > 1024 * 1024:
        raise ValueError("NCN LYR ใหญ่เกิน 1 MB")
    rows, tail = _lines(raw)
    if len(rows) < 5:
        raise ValueError("NCN LYR ไม่มีข้อมูลหัวเพลงหรือเนื้อร้อง")
    try:
        title = _body(rows[0]).decode("cp874", errors="strict").strip()
        artist = _body(rows[1]).decode("cp874", errors="strict").strip()
        body = []
        for row in rows[4:]:
            value = _body(row)
            if not value.strip():
                continue
            if b"\x00" in value:
                raise ValueError("NCN LYR มีอักขระไม่รองรับ")
            body.append(bulk._same(value.decode("cp874", errors="strict")))
    except UnicodeError as exc:
        raise ValueError("NCN LYR ไม่ใช่รหัส CP874 ที่รองรับ") from exc
    # The known Nick_Karaoke Professional end marker is commonly an
    # untimed advertisement. Until CUR is checked we cannot prove its timing;
    # exclude it conservatively, including from the "last" target selector.
    if body and OLD_CREDIT.fullmatch(body[-1]):
        body.pop()
    if len(body) < 4:
        raise ValueError("NCN LYR ต้องมีข้อความอย่างน้อย 4 บรรทัด")
    return {"lines": body, "title": title, "artist": artist}


def _lyrics_folder(root):
    """Find the Lyrics component only; allow a standalone selected folder."""
    if root.name.casefold() == "lyrics" and not any(
            item.name.casefold() == "song" for item in root.iterdir() if item.is_dir()):
        return root
    for item in root.iterdir():
        if item.name.casefold() == "lyrics" and item.is_dir() and not item.is_symlink():
            return item
    # Another explicitly selected folder containing loose .LYR is read-only
    # until it is moved alongside a valid NCN Song and Cursor pair.
    return root


def scan(root, ncn, bulk, *, cancelled=None, on_progress=None):
    """Index ONLY .LYR in Lyrics and its subdirectories.

    Do not open or hash MID or CUR while scanning. Complete mirrored
    MID/LYR/CUR checks and CP874 cursor remapping occur ONLY on apply.
    """
    root = locate(root)
    if root is None:
        raise ValueError("เลือกโฟลเดอร์ Lyrics หรือคลัง NCN ที่มีไฟล์ .LYR")
    folder = _lyrics_folder(root)
    grouped = {name: defaultdict(list) for name in bulk.POSITIONS}
    searchable, counted, skipped = {}, 0, 0
    files_to_read = []
    for dirpath, subdirs, files in os.walk(folder, topdown=True, followlinks=False):
        if cancelled is not None and cancelled.is_set():
            raise RuntimeError("ยกเลิกการวิเคราะห์ LYR · ยังไม่แก้ไฟล์")
        subdirs[:] = sorted(d for d in subdirs if not (Path(dirpath) / d).is_symlink())
        for name in files:
            if Path(name).suffix.lower() == ".lyr":
                files_to_read.append(Path(dirpath) / name)
                if len(files_to_read) > bulk.MAX_ROWS:
                    raise ValueError("ไฟล์ LYR มากเกินขีดจำกัด กรุณาเลือกโฟลเดอร์ย่อย")
                if on_progress and len(files_to_read) % 2000 == 0:
                    on_progress(f"กำลังนับ LYR จาก Lyrics · พบ {len(files_to_read):,} ไฟล์", 0, None)
    total = len(files_to_read)
    if not total:
        raise ValueError("ไม่พบไฟล์ .LYR ใน Lyrics หรือโฟลเดอร์ที่เลือก")
    if on_progress:
        on_progress(f"พบ LYR {total:,} ไฟล์ · กำลังอ่านข้อความอย่างเดียว", 0, total)
    # A second pass over file content avoids per-song companion lookup, CUR
    # parsing and MIDI reads, which dominated analysis in Build 329.
    for number, path in enumerate(files_to_read, 1):
        if cancelled is not None and cancelled.is_set():
            raise RuntimeError("ยกเลิกการวิเคราะห์ LYR · ยังไม่ได้แก้เพลง")
        if on_progress and (number % 100 == 0 or number == total):
            on_progress(
                f"วิเคราะห์ LYR {number:,}/{total:,} · อ่านได้ {counted:,} · ข้าม {skipped:,}",
                number, total)
        try:
            if path.is_symlink() or not path.is_file():
                raise ValueError("LYR เป็นลิงก์")
            relative = path.relative_to(folder).as_posix()
            raw = path.read_bytes()
            parsed = _parse_lyrics_only(raw, bulk)
        except (OSError, ValueError, UnicodeError, TypeError):
            skipped += 1
            continue
        song_id = relative
        record = {
            "lyrics": relative,
            "digestLyrics": bulk._sha(raw),
            "source": "lyr-only"
        }
        counted += 1
        searchable[song_id] = "\n".join(item.casefold() for item in parsed["lines"])
        for pos, (idx, _) in bulk.POSITIONS.items():
            phrase = parsed["lines"][idx]
            if not phrase:
                continue
            gid = bulk._group_id(pos, phrase)
            grouped[pos][gid].append({
                "songId": song_id, "code": path.stem[:80],
                "title": parsed["title"] or path.stem,
                "artist": parsed["artist"], "text": phrase,
                "record": record
            })
    if not counted:
        raise ValueError(f"พบ LYR {total:,} ไฟล์ แต่ไม่พบเนื้อร้อง CP874 ที่มีอย่างน้อย 4 บรรทัด")
    groups = {}
    for pos, mapping in grouped.items():
        for gid, members in mapping.items():
            groups[gid] = {
                "id": gid, "position": pos, "label": bulk.POSITIONS[pos][1],
                "text": members[0]["text"], "count": len(members),
                "members": members
            }
    return {
        "root": str(root), "mode": "ncn-folder", "scanMode": "lyr-only",
        "generation": None, "groups": groups, "searchable": searchable,
        "songs": counted, "inspected": total, "skippedInvalid": skipped,
        "withoutLyrics": 0, "groupCount": len(groups)
    }


def _selected_triplet(root, record, ncn, bulk):
    """Resolve MID/CUR only for selected LYR after explicit confirmation."""
    lyrics_base = _lyrics_folder(root)
    rel = record.get("lyrics")
    if not isinstance(rel, str):
        raise ValueError("รายการ LYR ไม่ถูกต้อง · กรุณาวิเคราะห์ใหม่")
    if lyrics_base == root:
        # Standalone Lyrics is read-only for analysis; no safe CUR edits
        # without a canonical NCN root and matching MID.
        raise ValueError("วิเคราะห์ LYR ได้ แต่จะแทนที่ต้องมี NCN/Song และ NCN/Cursor "
                         "ครบชุดก่อน เพื่อไม่ทำให้จังหวะเนื้อร้องเสีย")
    lyr = _component(root, "lyrics", rel)
    raw = lyr.read_bytes()
    if bulk._sha(raw) != record["digestLyrics"]:
        raise ValueError("LYR เปลี่ยนหลังวิเคราะห์ กรุณาวิเคราะห์ใหม่: " + lyr.name)
    # Enumerate only ONE mirrored Song bucket for the selected LYR. Never
    # scan the entire MIDI library, never choose an ambiguous MIDI silently.
    part = PurePosixPath(rel)
    song_base = next((p for p in root.iterdir() if p.name.casefold() == "song"
                      and p.is_dir() and not p.is_symlink()), None)
    if song_base is None:
        raise ValueError("ไม่พบโฟลเดอร์ NCN/Song สำหรับเพลงที่เลือก")
    song_dir = song_base
    for piece in part.parts[:-1]:
        matches = [p for p in song_dir.iterdir() if p.name.casefold() == piece.casefold()
                   and p.is_dir() and not p.is_symlink()]
        if len(matches) != 1:
            raise ValueError("ไม่พบโฟลเดอร์ย่อย NCN/Song รหัสตรงกับ LYR")
        song_dir = matches[0]
    midi_files = [p for p in song_dir.iterdir() if p.is_file() and not p.is_symlink()
                  and p.stem.casefold() == part.stem.casefold()
                  and p.suffix.lower() in MIDI_TYPES]
    if len(midi_files) != 1:
        raise ValueError("เพลงที่เลือกไม่มี MID รหัสตรงกับ LYR หรือพบรหัสซ้ำ")
    record_parts = _matched_parts(root, midi_files[0], ncn)
    mid, matched_lyr, cur = _source_files(root, record_parts)
    if lyr != matched_lyr:
        raise ValueError("MID/LYR/CUR ไม่ตรงรหัสหรือโฟลเดอร์ย่อย")
    with mid.open("rb") as midi_check:
        if midi_check.read(4) != b"MThd":
            raise ValueError("ไฟล์ MID ของเพลงที่เลือกไม่ถูกต้อง")
    return record_parts, mid, lyr, cur, raw



def _remap_times(old, length):
    """Reuse original CUR values, never invent fractional/approximate beats."""
    if not old or length < 1:
        raise ValueError("NCN ไม่มีเวลาสำหรับข้อความ")
    return [old[min(len(old)-1, (i * len(old)) // length)]
            for i in range(length)]


def apply(root, ncn, bulk, snapshot, group_ids, replacement, backup_root,
          *, search="", expected_count, cancelled=None, on_progress=None):
    root = locate(root)
    if root is None or snapshot.get("mode") != "ncn-folder" or snapshot["root"] != str(root):
        raise ValueError("โฟลเดอร์ NCN เปลี่ยนหลังสแกน กรุณาวิเคราะห์ใหม่")
    new_text = bulk._new_text(replacement)
    try:
        encoded = new_text.encode("cp874", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError("ข้อความใหม่มีอักขระที่ NCN CP874 ไม่รองรับ (เช่น อีโมจิ)") from exc
    if not encoded or b"\x00" in encoded or b"\r" in encoded or b"\n" in encoded:
        raise ValueError("ข้อความแทนที่ NCN ต้องเป็นบรรทัดเดียว")
    targets, chosen, unchanged = bulk._targets(snapshot, group_ids, search, new_text)
    count = sum(len(item["edits"]) for item in targets.values())
    if type(expected_count) is not int or expected_count != count:
        raise ValueError("จำนวนข้อความเปลี่ยนหลังยืนยัน · กรุณาตรวจใหม่")
    if not count:
        raise ValueError("ไม่มีข้อความ NCN ที่ต้องเปลี่ยน")
    edits = []
    for number, target in enumerate(targets.values(), 1):
        if cancelled is not None and cancelled.is_set():
            raise RuntimeError("ยกเลิกก่อนแก้ NCN")
        record = target["record"]
        triplet, mid, lyr, cur, original_lyr = _selected_triplet(
            root, record, ncn, bulk)
        original_cur = cur.read_bytes()
        parsed = _parse(original_lyr, original_cur, bulk)
        lyric_index = _parse_lyrics_only(original_lyr, bulk)
        if parsed["lines"] != lyric_index["lines"]:
            raise ValueError("LYR/CUR มีบรรทัดไม่ตรงกัน กรุณาตรวจไฟล์เวลาของเพลงที่เลือก: " + lyr.name)
        record["song"] = triplet["song"]
        record["cursor"] = triplet["cursor"]
        query = bulk._same(search).casefold()
        if query and query not in "\n".join(x.casefold() for x in parsed["lines"]):
            raise ValueError("คำค้นหาไม่ตรงกับเพลง NCN อีกต่อไป")
        changes = {}
        for group, item in target["edits"]:
            index = bulk.POSITIONS[group["position"]][0] % len(parsed["entries"])
            if index in changes:
                raise ValueError("เลือกบรรทัด NCN ซ้ำ")
            if parsed["lines"][index] != group["text"]:
                raise ValueError("ข้อความ NCN เปลี่ยนหลังสแกน: " + mid.name)
            changes[index] = encoded
        lyric_rows = list(parsed["rows"])
        cursor_values = list(parsed["values"])
        for index in sorted(changes.keys(), reverse=True):
            line = parsed["entries"][index]
            old_content = line["raw"]
            newline = lyric_rows[line["row"]][len(old_content):]
            lyric_rows[line["row"]] = changes[index] + newline
            start = line["cursor"]
            length = line["count"]
            segment = line["times"]
            # Keep the original line-marker time; distribute replacement
            # bytes across existing original positions, preserving start/end.
            cursor_values[start:start+length] = [segment[0]] + _remap_times(
                segment[1:], len(changes[index]))
        updated_lyr = b"".join(lyric_rows) + parsed["tail"]
        updated_cur = struct.pack("<" + "H" * len(cursor_values),
                                  *cursor_values) + parsed["cursorTail"]
        verified = _parse(updated_lyr, updated_cur, bulk)
        for i, text in enumerate(parsed["lines"]):
            expected = new_text if i in changes else text
            if verified["lines"][i] != expected:
                raise ValueError("ตรวจ NCN หลังแก้แล้วเนื้อร้องไม่ตรง")
        if len(verified["entries"]) != len(parsed["entries"]):
            raise ValueError("จำนวนบรรทัด NCN เปลี่ยนโดยไม่ตั้งใจ")
        edits.append({"songId": target["songId"], "record": record,
                      "files": [(lyr, original_lyr, updated_lyr),
                                (cur, original_cur, updated_cur)],
                      "lines": verified["lines"], "edits": target["edits"]})
        if on_progress and number % 300 == 0:
            on_progress(f"ตรวจ LYR/CUR {number:,}/{len(targets):,} เพลง", number)

    backup_root = Path(backup_root)
    backup_root.mkdir(parents=True, exist_ok=True)
    needed = sum(len(before) for item in edits for _, before, _ in item["files"])
    if shutil.disk_usage(backup_root).free < needed + 32 * 1024 * 1024:
        raise RuntimeError("พื้นที่สำหรับสำรองชุด NCN ไม่เพียงพอ")
    import secrets
    op = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + secrets.token_hex(4)
    bundle = backup_root / (op + ".zip")
    manifest_path = backup_root / (op + ".json")
    specs = []
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=3) as archive:
        for item in edits:
            for path, before, after in item["files"]:
                rel = path.relative_to(root).as_posix()
                archive.writestr(rel, before)
                specs.append({"path": rel, "before": bulk._sha(before),
                              "after": bulk._sha(after)})
    first = chosen[0][0] if len(chosen) == 1 else None
    manifest = {
        "version": 2, "id": op, "state": "prepared", "root": str(root),
        "mode": "ncn-folder",
        "position": first["position"] if first else "mixed",
        "oldText": first["text"] if first else f"{len(chosen)} กลุ่มข้อความ",
        "newText": new_text, "groups": list(group_ids), "search": bulk._same(search),
        "songs": len(edits), "lines": count, "files": specs,
        "createdAt": datetime.now(timezone.utc).isoformat()
    }
    bulk._atomic_bytes(manifest_path, (json.dumps(manifest, ensure_ascii=False)+"\n").encode("utf-8"))
    try:
        for item in edits:
            if cancelled is not None and cancelled.is_set():
                raise RuntimeError("ยกเลิกขณะแก้ NCN · กำลังย้อนคืน")
            for path, before, after in item["files"]:
                if path.suffix.lower() == ".lyr":
                    clean = _component(root, "lyrics", item["record"]["lyrics"])
                else:
                    clean = _component(root, "cursor", item["record"]["cursor"])
                if clean != path or bulk._sha(clean.read_bytes()) != bulk._sha(before):
                    raise ValueError("NCN ถูกแก้ไขระหว่างทำงาน · กำลังย้อนคืน: " + path.name)
                bulk._atomic_bytes(clean, after)
    except BaseException:
        try:
            bulk._restore_files(root, bundle, specs, strict=False)
            manifest["state"] = "rolled-back"
        except Exception:
            manifest["state"] = "recovery-required"
        bulk._atomic_bytes(manifest_path, (json.dumps(manifest, ensure_ascii=False)+"\n").encode("utf-8"))
        raise
    manifest["state"] = "committed"
    bulk._atomic_bytes(manifest_path, (json.dumps(manifest, ensure_ascii=False)+"\n").encode("utf-8"))
    for group, members in chosen:
        removed = {item["songId"] for item in members}
        was_repeated = group["count"] >= 2
        group["members"][:] = [x for x in group["members"] if x["songId"] not in removed]
        group["count"] = len(group["members"])
        if was_repeated and group["count"]:
            group["queuePending"] = True
        if not group["members"]:
            snapshot["groups"].pop(group["id"], None)
    for item in edits:
        item["record"]["digestLyrics"] = bulk._sha(item["files"][0][2])
        item["record"]["digestCursor"] = bulk._sha(item["files"][1][2])
        snapshot["searchable"][item["songId"]] = "\n".join(
            x.casefold() for x in item["lines"])
        for old_group, old_item in item["edits"]:
            pos = old_group["position"]
            gid = bulk._group_id(pos, new_text)
            group = snapshot["groups"].setdefault(gid, {
                "id": gid, "position": pos, "label": bulk.POSITIONS[pos][1],
                "text": new_text, "count": 0, "members": []
            })
            member = dict(old_item)
            member["text"] = new_text
            group["members"].append(member)
            group["count"] = len(group["members"])
    snapshot["groupCount"] = len(snapshot["groups"])
    return {
        "message": (f"แก้ NCN {len(edits):,} เพลง · {count:,} บรรทัดสำเร็จ "
                    "· สำรอง LYR/CUR และคง MIDI เดิม"),
        "changedSongs": len(edits), "changedLines": count,
        "changedGroups": len(chosen), "alreadyCorrect": unchanged,
        "changedFiles": len(specs), "removedSyllableCues": 0,
        "backupId": op, "remainingGroups": snapshot["groupCount"]
    }
