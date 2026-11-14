"""Group and safely replace common intro/outro lyric lines in local X-Stage songs.

Only published LOCAL lyrics JSON and its synchronized .lrc are updated.
Original source songs, M4A, vocal files and Google Drive are never changed.
Each batch has a durable backup ZIP and a recoverable manifest in AppData.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
import unicodedata
import zipfile
from collections import defaultdict
from difflib import SequenceMatcher
from math import isfinite
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

POSITIONS = {
    "first": (0, "บรรทัดแรก"),
    "second": (1, "บรรทัดที่ 2"),
    "penultimate": (-2, "บรรทัดรองสุดท้าย"),
    "last": (-1, "บรรทัดสุดท้าย"),
}
TIMED = re.compile(r"^(\s*\[(?:\d{1,3}):(?:[0-5]\d)(?:[.:]\d{1,3})?\])(.*?)(\r?\n?)$")
ENHANCED = re.compile(r"<\d{1,3}:[0-5]\d(?:[.:]\d{1,3})?>")
MAX_TEXT = 400
MAX_ROWS = 400000


def _same(text):
    return unicodedata.normalize("NFC", str(text).strip())


def _group_id(position, text):
    return hashlib.sha256((position + "\0" + _same(text)).encode("utf-8")).hexdigest()[:24]


def _timestamped_rows(raw):
    chunks = raw.splitlines(keepends=True)
    found = []
    for index, part in enumerate(chunks):
        match = TIMED.match(part)
        if match:
            found.append((index, match))
        elif re.match(r"^\s*\[\d{1,3}:\d{2}", part):
            raise ValueError("พบ LRC แบบหลายเวลาในบรรทัดหรือรูปแบบเวลาไม่รองรับ")
    return chunks, found


def _load(root, row, export):
    lyric = row.get("lyrics") or {}
    rel = lyric.get("path")
    if not rel:
        return None
    if (root / rel).is_symlink():
        raise ValueError("ไม่แก้ไขไฟล์เนื้อร้องแบบลิงก์ เพราะอาจกระทบเพลงอื่น")
    path = export.safe_media_path(root, rel, "lyrics")
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    lines = doc.get("lines")
    if not isinstance(lines, list) or len(lines) < 4:
        return None
    if not all(isinstance(x, dict) and isinstance(x.get("text"), str) and
               isinstance(x.get("startTime"), (int, float)) and
               not isinstance(x.get("startTime"), bool) for x in lines):
        raise ValueError("Lyrics JSON ไม่มีบรรทัดและเวลาในรูปแบบที่รองรับ")
    # The companion LRC must be independently validated: a malicious
    # symlink inside lyrics/ must never redirect a bulk write outside songs/.
    lrc_rel = PurePosixPath(rel).with_suffix(".lrc").as_posix()
    if (root / lrc_rel).is_symlink():
        raise ValueError("ไม่แก้ไขไฟล์ LRC แบบลิงก์ เพราะอาจกระทบเพลงอื่น")
    lrc_path = export.safe_media_path(root, lrc_rel, "lyrics")
    raw = doc.get("rawLrc")
    file_raw = lrc_path.read_text(encoding="utf-8-sig") if lrc_path.is_file() else None
    if raw is None and file_raw is not None:
        raw = file_raw
    if raw is not None:
        if not isinstance(raw, str):
            raise ValueError("rawLrc ต้องเป็นข้อความ")
        if file_raw is not None and raw.replace("\r\n", "\n") != file_raw.replace("\r\n", "\n"):
            raise ValueError("ไฟล์ JSON และ LRC มีเนื้อหาต่างกัน กรุณาตรวจเพลงก่อนแก้ไข")
        chunks, found = _timestamped_rows(raw)
        if len(found) != len(lines):
            raise ValueError("จำนวนบรรทัด JSON และ LRC ไม่ตรงกัน")
        for (_, match), line in zip(found, lines):
            # Word-level cues are allowed for non-edited lines; after replacing
            # one lyric line they are removed from that line only.
            if _same(ENHANCED.sub("", match.group(2))) != _same(line["text"]):
                raise ValueError("ลำดับคำร้องใน JSON และ LRC ไม่ตรงกัน")
    return path, lrc_path if file_raw is not None else None, doc, raw


def _display_units(value):
    """Keep Thai vowel/tone combining marks attached to their displayed glyph."""
    units = []
    for char in value:
        category = unicodedata.category(char)
        if units and (category.startswith("M") or char in ("\u200d", "\ufe0f")):
            units[-1] += char
        else:
            units.append(char)
    return units


def _retime_visual_units(line, old_text, new_text):
    """Use verified original glyph timestamps as fixed anchors.

    For unequal lengths, align unchanged Unicode display units and interpolate
    ONLY unmatched spans between their fixed timing anchors. The algorithm
    never reads/modifies NCN source and never claims an inferred timestamp is
    an observed sung syllable. Preserve the original line time boundaries.
    """
    units = _display_units(new_text)
    if not units:
        raise ValueError("ไม่มีอักษรที่จะจัดเวลาไฮไลต์")
    old_units = _display_units(old_text)
    original = line.get("syllables") or []
    start = line.get("startTime")
    end = line.get("endTime")
    if (isinstance(start, bool) or isinstance(end, bool)
            or not isinstance(start, (int, float))
            or not isinstance(end, (int, float))
            or not isfinite(start) or not isfinite(end)
            or start < 0 or end <= start):
        raise ValueError("Lyrics JSON ไม่มีช่วงเวลาบรรทัดที่ถูกต้อง · ข้ามเพื่อรักษาต้นฉบับ")
    if not isinstance(original, list):
        raise ValueError("ข้อมูลไฮไลต์ Lyrics JSON เดิมไม่ถูกต้อง")
    start, end = float(start), float(end)
    valid = (
        len(original) == len(old_units) and len(original) > 0
        and all(isinstance(c, dict)
                and c.get("text") == old_units[i]
                and isinstance(c.get("start"), (int, float))
                and not isinstance(c.get("start"), bool)
                and isfinite(c["start"])
                and start - 0.001 <= c["start"] <= end + 0.001
                for i, c in enumerate(original))
    )
    source = [float(c["start"]) for c in original] if valid else []
    if source and any(a > b for a, b in zip(source, source[1:])):
        raise ValueError("เวลาไฮไลต์เดิมย้อนหลัง · ข้ามโดยไม่แก้เพลง")
    if source and len(old_units) == len(units):
        # Same number of visible characters: never move any timestamp.
        positions = source[:]
        method = "original-cue-positions"
    elif source:
        positions = [None] * len(units)
        matcher = SequenceMatcher(a=old_units, b=units, autojunk=False)
        for a, b, size in matcher.get_matching_blocks():
            for delta in range(size):
                positions[b + delta] = source[a + delta]
        # Every matching glyph is now a fixed anchor. Only the inserted or
        # substituted runs are assigned estimated positions.
        pos = 0
        while pos < len(positions):
            if positions[pos] is not None:
                pos += 1
                continue
            first = pos
            while pos < len(positions) and positions[pos] is None:
                pos += 1
            left_index, right_index = first - 1, pos
            left = positions[left_index] if left_index >= 0 else start
            right = positions[right_index] if right_index < len(positions) else end
            if right < left or (right == left and pos > first):
                # No measured time interval to insert extra character cues.
                # Never shift the existing anchors to hide the conflict.
                raise ValueError("ช่วงเวลาระหว่างอักษรเดิมไม่พอสำหรับข้อความใหม่ · ข้ามเพลง")
            count = pos - first
            for index in range(first, pos):
                fraction = (index - first + 1) / (count + (1 if right_index < len(positions) else 1))
                positions[index] = left + (right - left) * fraction
        method = "anchored-changed-spans"
    else:
        # A source that has only line timestamps can produce an explicitly
        # estimated display effect, never an allegedly verified CUR timing.
        positions = [start + (end - start) * i / max(1, len(units))
                     for i in range(len(units))]
        method = "estimated-line-only"
    if any(not isfinite(t) or t < start - .001 or t > end + .001
           for t in positions):
        raise ValueError("เวลาเนื้อร้องอยู่นอกช่วงเดิม · ข้ามเพลง")
    if any(a > b for a, b in zip(positions, positions[1:])):
        raise ValueError("เวลาไฮไลต์หลังแก้ย้อนหลัง · ข้ามเพลง")
    cues = []
    for i, glyph in enumerate(units):
        at = positions[i]
        following = positions[i + 1] if i + 1 < len(units) else end
        cues.append({"text": glyph, "start": round(at, 4),
                     "duration": round(max(0.0, following - at), 4)})
    line["syllables"] = cues
    line["timingEstimated"] = True  # Text was replaced, even if cue positions were reused.
    line["timingMethod"] = method
    return method != "original-cue-positions"


def _replacement(document, raw, position, new_text):
    lines = document["lines"]
    index = POSITIONS[position][0]
    changed = json.loads(json.dumps(document, ensure_ascii=False))
    changed_line = changed["lines"][index]
    old_text = changed_line["text"]
    estimated = _retime_visual_units(changed_line, old_text, new_text)
    changed_line["text"] = new_text
    updated_raw = None
    if raw is not None:
        chunks, entries = _timestamped_rows(raw)
        chunk_idx, match = entries[index]
        chunks[chunk_idx] = match.group(1) + new_text + match.group(3)
        updated_raw = "".join(chunks)
        changed["rawLrc"] = updated_raw
    return changed, updated_raw, estimated


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _atomic_bytes(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".xstage-bulk-",
                                         suffix=".tmp", delete=False) as out:
            name = Path(out.name)
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        if name:
            name.unlink(missing_ok=True)


def _record_bytes(root, row, export):
    loaded = _load(root, row, export)
    if loaded is None:
        return None
    path, lrc, doc, raw = loaded
    return path, lrc, doc, raw


def scan(root, export, *, cancelled=None, on_progress=None):
    root = Path(root).expanduser().resolve()
    if not (root / "current.json").is_file():
        raise ValueError("ยังไม่มีคลังเพลงที่สร้างแล้ว กรุณาสร้างเพลงให้มี songs/current.json ก่อน")
    pointer, _ = export._read_current(root)
    entries = export.existing_records(root)
    if len(entries) > MAX_ROWS:
        raise ValueError("จำนวนรายการเพลงเกินขนาดที่รุ่นนี้รองรับ")
    grouped = {name: defaultdict(list) for name in POSITIONS}
    included = excluded = missing = 0
    searchable = {}
    seen = set()
    for number, row in enumerate(entries, 1):
        if cancelled is not None and cancelled.is_set():
            raise RuntimeError("ยกเลิกการวิเคราะห์ข้อความ · ยังไม่ได้แก้ไขเพลง")
        if not isinstance(row, dict) or not row.get("webSongId"):
            excluded += 1
            continue
        song_id = row["webSongId"]
        if song_id in seen:
            continue
        seen.add(song_id)
        try:
            parsed = _record_bytes(root, row, export)
        except (OSError, ValueError, TypeError, KeyError, UnicodeError):
            excluded += 1
            continue
        if parsed is None:
            missing += 1
            continue
        _, _, doc, _ = parsed
        included += 1
        # Cache a normalized, case-insensitive searchable transcript once
        # per song rather than reopening 90k JSON documents per text query.
        searchable[song_id] = "\n".join(
            _same(line["text"]).casefold() for line in doc["lines"])
        for pos, (index, _) in POSITIONS.items():
            text = _same(doc["lines"][index]["text"])
            if not text:
                continue
            ident = _group_id(pos, text)
            grouped[pos][ident].append({
                "songId": song_id, "code": str(row.get("code") or ""),
                "title": str(row.get("title") or ""),
                "artist": str(row.get("artist") or ""),
                "text": text, "record": row,
            })
        if on_progress and number % 500 == 0:
            on_progress(f"อ่านเนื้อร้องแล้ว {number:,}/{len(entries):,} เพลง · ตรวจใช้ได้ {included:,}", number)
    group_lookup = {}
    for pos, groups in grouped.items():
        for ident, members in groups.items():
            group_lookup[ident] = {
                "id": ident, "position": pos, "label": POSITIONS[pos][1],
                "text": members[0]["text"], "count": len(members),
                "members": members
            }
    return {
        "root": str(root), "generation": pointer.get("generation"),
        "groups": group_lookup, "searchable": searchable, "songs": included,
        "skippedInvalid": excluded, "withoutLyrics": missing,
        "inspected": len(entries), "groupCount": len(group_lookup),
    }


def _searched_members(snapshot, group, search=""):
    query = _same(search).casefold()
    if len(query) > 200:
        raise ValueError("คำค้นหาเนื้อร้องยาวเกิน 200 ตัวอักษร")
    if not query:
        return list(group["members"])
    searchable = snapshot.get("searchable", {})
    return [item for item in group["members"]
            if query in searchable.get(item["songId"], "")]


def list_groups(snapshot, position, *, search="", offset=0, limit=40, repeats_only=True):
    if position not in POSITIONS:
        raise ValueError("ตำแหน่งบรรทัดไม่ถูกต้อง")
    groups = []
    for group in snapshot["groups"].values():
        if group["position"] != position:
            continue
        # "Repeated" refers to the full library, while a phrase filtered by
        # any lyric-body search can legitimately match only one of those songs.
        if repeats_only and group["count"] < 2 and not group.get("queuePending"):
            continue
        members = _searched_members(snapshot, group, search)
        if members:
            groups.append((group, len(members)))
    groups.sort(key=lambda entry: (-entry[1], -entry[0]["count"],
                                   entry[0]["text"].casefold()))
    page = groups[offset:offset+limit]
    return {
        "position": position, "label": POSITIONS[position][1],
        "total": len(groups), "offset": offset,
        "rows": [{"id": group["id"], "position": group["position"],
                  "text": group["text"], "count": count,
                  "libraryCount": group["count"]}
                 for group, count in page],
        "songs": snapshot["songs"], "inspected": snapshot["inspected"],
        "skippedInvalid": snapshot["skippedInvalid"],
        "withoutLyrics": snapshot["withoutLyrics"],
    }


def preview(snapshot, group_id, limit=12, search=""):
    group = snapshot["groups"].get(group_id)
    if not group:
        raise ValueError("ไม่พบกลุ่มข้อความ กรุณาวิเคราะห์คลังเพลงใหม่")
    matches = _searched_members(snapshot, group, search)
    if not matches:
        raise ValueError("กลุ่มข้อความนี้ไม่มีเพลงที่ตรงกับคำค้นหาปัจจุบัน")
    return {
        "id": group["id"], "text": group["text"], "position": group["position"],
        "label": group["label"], "count": len(matches),
        "libraryCount": group["count"],
        "examples": [{"code": item["code"], "title": item["title"],
                      "artist": item["artist"]} for item in matches[:limit]],
    }


def _new_text(value):
    if not isinstance(value, str):
        raise ValueError("กรุณาระบุข้อความแทนที่")
    value = unicodedata.normalize("NFC", value.strip())
    if (not value or len(value) > MAX_TEXT or
            "\r" in value or "\n" in value or "\0" in value):
        raise ValueError("ข้อความแทนที่ต้องเป็นบรรทัดเดียว ความยาวไม่เกิน 400 ตัวอักษร")
    return value


def _targets(snapshot, group_ids, search="", replacement=None):
    if (not isinstance(group_ids, list) or not 1 <= len(group_ids) <= 200 or
            any(not isinstance(x, str) for x in group_ids) or
            len(set(group_ids)) != len(group_ids)):
        raise ValueError("กรุณาเลือกกลุ่มข้อความไม่ซ้ำกัน 1–200 กลุ่ม")
    new = _new_text(replacement) if replacement is not None else None
    targets = {}
    chosen = []
    already = 0
    for group_id in group_ids:
        group = snapshot["groups"].get(group_id)
        if not group:
            raise ValueError("พบกลุ่มข้อความที่เปลี่ยนหลังวิเคราะห์ กรุณาตรวจรายการใหม่")
        matching = _searched_members(snapshot, group, search)
        if not matching:
            raise ValueError("มีกลุ่มที่ไม่ตรงกับคำค้นหา กรุณาตรวจรายการที่เลือกอีกครั้ง")
        if new is not None and _same(group["text"]) == new:
            already += len(matching)
            continue
        chosen.append((group, matching))
        for item in matching:
            targets.setdefault(item["songId"], {
                "record": item["record"], "songId": item["songId"],
                "edits": []
            })["edits"].append((group, item))
    return targets, chosen, already


def plan(snapshot, group_ids, *, search="", replacement=None):
    targets, chosen, already = _targets(snapshot, group_ids, search, replacement)
    return {
        "groups": len(chosen), "chosenGroups": len(group_ids),
        "changedSongs": len(targets),
        "changedLines": sum(len(item["edits"]) for item in targets.values()),
        "alreadyCorrect": already,
        "selected": [{
            "id": group["id"], "position": group["position"],
            "label": group["label"], "text": group["text"],
            "count": len(members),
            "examples": [{"code": row["code"], "title": row["title"]}
                         for row in members[:3]],
        } for group, members in chosen],
        "search": _same(search),
    }



def apply_many_smart(root, export, snapshot, group_ids, new_text, backup_root,
                     *, search="", expected_count, cancelled=None,
                     on_progress=None):
    """Scale safe local JSON/LRC replacement to large collections.

    Preflight EVERY selected song, skip only individual corrupt or changed
    local lyric records, spool replacements to disk, archive ALL originals
    before the first write, then commit atomically per file. An interruption
    rolls the whole successful subset back from the single durable backup.
    Source MID/LYR/CUR/media and Drive are never written.
    """
    import shutil

    root = Path(root).expanduser().resolve()
    if snapshot.get("root") != str(root):
        raise ValueError("กลุ่มข้อความไม่ตรงคลังเพลง กรุณาวิเคราะห์ใหม่")
    new_text = _new_text(new_text)
    targets, chosen, unchanged = _targets(snapshot, group_ids, search, new_text)
    expected_lines = sum(len(item["edits"]) for item in targets.values())
    if type(expected_count) is not int or expected_count != expected_lines:
        raise ValueError("จำนวนบรรทัดที่เลือกเปลี่ยน กรุณาตรวจรายการก่อนแก้ไข")
    if not expected_lines:
        raise ValueError("ไม่มีข้อความใหม่ที่จะเปลี่ยน")
    pointer, _ = export._read_current(root)
    if pointer.get("generation") != snapshot.get("generation"):
        raise ValueError("ฐานเพลงเปลี่ยนหลังวิเคราะห์ · ต้องสแกนใหม่")

    # This log intentionally contains only song IDs and bounded error messages,
    # never OAuth tokens or audio, and stays on the local PC.
    rejected = []
    committed = []
    spec_list = []
    seen_paths = set()
    operation = (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                 + "-" + secrets.token_hex(4))
    backup_root = Path(backup_root)
    backup_root.mkdir(parents=True, exist_ok=True)
    zip_path = backup_root / (operation + ".zip")
    manifest_path = backup_root / (operation + ".json")
    report_path = backup_root / (operation + ".skipped.json")
    changed_lines = 0
    estimated_lines = 0

    with tempfile.TemporaryDirectory(prefix=".xstage-batch-stage-", dir=backup_root) as temp:
        stage = Path(temp)
        try:
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=3, allowZip64=True) as archive:
                for number, item in enumerate(targets.values(), 1):
                    if cancelled is not None and cancelled.is_set():
                        raise RuntimeError("ยกเลิกระหว่างตรวจไฟล์ · ยังไม่แก้เพลง")
                    song_id = item["songId"]
                    try:
                        parsed = _record_bytes(root, item["record"], export)
                        if parsed is None:
                            raise ValueError("ไม่มี Lyrics JSON อย่างน้อย 4 บรรทัด")
                        path, lrc, doc, raw = parsed
                        if path.stat().st_size > 8 * 1024 * 1024:
                            raise ValueError("Lyrics JSON ใหญ่เกิน 8 MB")
                        if lrc and lrc.stat().st_size > 2 * 1024 * 1024:
                            raise ValueError("LRC ใหญ่เกิน 2 MB")
                        query = _same(search).casefold()
                        if query and query not in "\n".join(
                                _same(line["text"]).casefold() for line in doc["lines"]):
                            raise ValueError("คำค้นไม่ตรงกับเนื้อร้องล่าสุด")
                        revised_doc, revised_lrc = doc, raw
                        edits_here = []
                        estimated_here = 0
                        positions = set()
                        for group, entry in item["edits"]:
                            index = POSITIONS[group["position"]][0]
                            slot = index % len(doc["lines"])
                            if slot in positions:
                                raise ValueError("เลือกตำแหน่งข้อความซ้ำในเพลง")
                            positions.add(slot)
                            if _same(revised_doc["lines"][index]["text"]) != group["text"]:
                                raise ValueError("ข้อความเปลี่ยนหลังการสแกน")
                            revised_doc, revised_lrc, estimated = _replacement(
                                revised_doc, revised_lrc, group["position"], new_text)
                            estimated_here += int(estimated)
                            edits_here.append((group, entry))
                        json_bytes = (json.dumps(revised_doc, ensure_ascii=False,
                                                 separators=(",", ":")) + "\n").encode("utf-8")
                        file_data = [(path, path.read_bytes(), json_bytes)]
                        if lrc is not None:
                            if revised_lrc is None:
                                raise ValueError("ไม่สามารถปรับ LRC ให้ตรงกับ JSON")
                            file_data.append((lrc, lrc.read_bytes(),
                                              revised_lrc.encode("utf-8")))
                        paths = [p.relative_to(root).as_posix() for p, _, _ in file_data]
                        if any(p in seen_paths for p in paths):
                            raise ValueError("ไฟล์ Lyrics ถูกอ้างซ้ำในคลัง · ไม่แก้ทับ")
                    except (ValueError, OSError, TypeError, KeyError, IndexError,
                            UnicodeError, OverflowError) as exc:
                        rejected.append({"songId": str(song_id)[:180],
                                         "code": str(item["record"].get("code", ""))[:100],
                                         "reason": str(exc)[:400]})
                        if on_progress and number % 250 == 0:
                            on_progress(f"ตรวจ {number:,}/{len(targets):,} · ข้ามผิดปกติ {len(rejected):,}", number)
                        continue

                    # Operational write/disk failures are NOT skippable:
                    # archive and stage must both be durable before commit.
                    stage_files = []
                    for path, original, revised in file_data:
                        relative = path.relative_to(root).as_posix()
                        archive.writestr(relative, original)
                        name = str(len(spec_list)) + ".data"
                        (stage / name).write_bytes(revised)
                        before, after = _sha(original), _sha(revised)
                        spec_list.append({"path": relative, "before": before,
                                          "after": after})
                        stage_files.append((path, name, before))
                        seen_paths.add(relative)
                    committed.append({"songId": song_id, "edits": edits_here,
                                      "files": stage_files,
                                      "jsonPath": path if lrc is None else file_data[0][0]})
                    changed_lines += len(edits_here)
                    estimated_lines += estimated_here
                    if on_progress and number % 250 == 0:
                        on_progress(f"เตรียม {number:,}/{len(targets):,} · พร้อม {len(committed):,} · ข้าม {len(rejected):,}", number)

            if not committed:
                zip_path.unlink(missing_ok=True)
                _atomic_bytes(report_path, (json.dumps({
                    "operation": operation, "attemptedSongs": len(targets),
                    "skippedInvalid": len(rejected), "rows": rejected
                }, ensure_ascii=False) + "\n").encode("utf-8"))
                return {"message": f"ไม่มีไฟล์ที่แก้ได้ · ข้ามผิดปกติ {len(rejected):,} เพลง",
                        "changedSongs": 0, "changedLines": 0, "skippedInvalid": len(rejected),
                        "skippedExamples": rejected[:20], "skippedReport": str(report_path),
                        "backupId": None, "estimatedLines": 0,
                        "remainingGroups": snapshot["groupCount"]}

            if shutil.disk_usage(backup_root).free < 32 * 1024 * 1024:
                raise RuntimeError("พื้นที่เก็บข้อมูลเหลือน้อยก่อนบันทึก · ยังไม่แก้เพลง")
            # A committed ZIP backup must survive a sudden power loss before
            # its manifest permits any song writes.
            # Windows requires a writable CRT handle for os.fsync; Linux
            # also accepts r+b. Never change ZIP contents after verification.
            with zip_path.open("r+b") as stream:
                stream.flush()
                os.fsync(stream.fileno())
            if rejected:
                _atomic_bytes(report_path, (json.dumps({
                    "operation": operation, "attemptedSongs": len(targets),
                    "skippedInvalid": len(rejected), "rows": rejected
                }, ensure_ascii=False) + "\n").encode("utf-8"))
            first = chosen[0][0] if len(chosen) == 1 else None
            manifest = {
                "version": 3, "id": operation, "state": "prepared",
                "root": str(root), "position": first["position"] if first else "mixed",
                "oldText": first["text"] if first else f"{len(chosen)} กลุ่มข้อความ",
                "newText": new_text, "groups": list(group_ids), "search": _same(search),
                "songs": len(committed), "lines": changed_lines,
                "estimatedLines": estimated_lines,
                "skippedInvalid": len(rejected), "files": spec_list,
                "createdAt": datetime.now(timezone.utc).isoformat()
            }
            _atomic_bytes(manifest_path, (json.dumps(manifest, ensure_ascii=False)
                                          + "\n").encode("utf-8"))
            try:
                for number, change in enumerate(committed, 1):
                    if cancelled is not None and cancelled.is_set():
                        raise RuntimeError("ยกเลิกระหว่างเขียน · คืนค่าไฟล์จากชุดสำรอง")
                    for target, staged_name, before in change["files"]:
                        if _sha(target.read_bytes()) != before:
                            raise ValueError("ไฟล์เปลี่ยนระหว่างงาน · คืนค่าจากชุดสำรอง")
                        _atomic_bytes(target, (stage / staged_name).read_bytes())
                    if on_progress and number % 250 == 0:
                        on_progress(f"บันทึก {number:,}/{len(committed):,} เพลง · สำรองพร้อม Undo", number)
            except BaseException:
                try:
                    _restore_files(root, zip_path, spec_list, strict=False)
                    manifest["state"] = "rolled-back"
                except Exception:
                    manifest["state"] = "recovery-required"
                _atomic_bytes(manifest_path, (json.dumps(manifest, ensure_ascii=False)
                                              + "\n").encode("utf-8"))
                raise
            manifest["state"] = "committed"
            _atomic_bytes(manifest_path, (json.dumps(manifest, ensure_ascii=False)
                                          + "\n").encode("utf-8"))
        except BaseException:
            # No manifest = no file was edited. Orphans are cleaned, but never
            # discard backups after writes have begun or recovery is required.
            if not manifest_path.exists():
                zip_path.unlink(missing_ok=True)
                report_path.unlink(missing_ok=True)
            raise

    # Patch the cached group index only AFTER the durable commit. Invalid
    # files remain in their original groups for later diagnosis/re-scan.
    changed_ids = {row["songId"] for row in committed}
    for group, members in chosen:
        affected = {item["songId"] for item in members if item["songId"] in changed_ids}
        if not affected:
            continue
        was_repeated = group["count"] >= 2
        group["members"][:] = [item for item in group["members"]
                              if item["songId"] not in affected]
        group["count"] = len(group["members"])
        if was_repeated and group["count"]:
            group["queuePending"] = True
        if not group["members"]:
            snapshot["groups"].pop(group["id"], None)
    for change in committed:
        updated = json.loads(change["jsonPath"].read_text(encoding="utf-8"))
        song_id = change["songId"]
        snapshot["searchable"][song_id] = "\n".join(
            _same(line["text"]).casefold() for line in updated["lines"])
        for previous, item in change["edits"]:
            identity = _group_id(previous["position"], new_text)
            group = snapshot["groups"].setdefault(identity, {
                "id": identity, "position": previous["position"],
                "label": POSITIONS[previous["position"]][1],
                "text": new_text, "count": 0, "members": []})
            new_item = dict(item)
            new_item["text"] = new_text
            group["members"].append(new_item)
            group["count"] = len(group["members"])
    snapshot["groupCount"] = len(snapshot["groups"])
    return {
        "message": (f"แก้เนื้อร้อง {changed_lines:,} บรรทัดใน {len(committed):,} เพลง "
                    f"· ข้ามผิดปกติ {len(rejected):,} เพลง · สำรองพร้อมย้อนคืน"),
        "changedSongs": len(committed), "changedLines": changed_lines,
        "changedFiles": len(spec_list), "changedGroups": len(chosen),
        "estimatedLines": estimated_lines, "skippedInvalid": len(rejected),
        "skippedExamples": rejected[:20], "skippedReport": str(report_path) if rejected else "",
        "backupId": operation, "remainingGroups": snapshot["groupCount"],
        "alreadyCorrect": unchanged,
    }


def apply(root, export, snapshot, group_id, new_text, backup_root,
          *, expected_count, cancelled=None, on_progress=None):
    """Backward-compatible single-group edit using one atomic multi-group batch."""
    return apply_many(root, export, snapshot, [group_id], new_text, backup_root,
                      expected_count=expected_count, cancelled=cancelled,
                      on_progress=on_progress)


def apply_many(root, export, snapshot, group_ids, new_text, backup_root,
               *, search="", expected_count, cancelled=None, on_progress=None):
    """Edit only selected groups/songs (possibly at different positions).

    Each song is opened and saved ONCE even if two or more positions are
    selected. Backups are complete before the first write. The live group
    index is patched in memory after commit, keeping the unedited queue
    visible immediately without rescanning a large song library.
    """
    root = Path(root).expanduser().resolve()
    if snapshot["root"] != str(root):
        raise ValueError("กลุ่มข้อความไม่ตรงกับพื้นที่เก็บเพลง กรุณาวิเคราะห์ใหม่")
    new_text = _new_text(new_text)
    targets, chosen, unchanged = _targets(snapshot, group_ids, search, new_text)
    number_of_lines = sum(len(target["edits"]) for target in targets.values())
    if type(expected_count) is not int or expected_count != number_of_lines:
        raise ValueError("จำนวนเพลงหรือบรรทัดที่เลือกเปลี่ยนไป กรุณาตรวจรายการก่อนยืนยัน")
    if not number_of_lines:
        raise ValueError("ทุกกลุ่มที่เลือกมีข้อความใหม่นี้อยู่แล้ว ไม่ต้องแก้ไขซ้ำ")
    pointer, _ = export._read_current(root)
    if pointer.get("generation") != snapshot["generation"]:
        raise ValueError("ฐานเพลงมีการเปลี่ยนแปลงหลังวิเคราะห์ กรุณากดวิเคราะห์อีกครั้ง")

    # Full preflight. A selected song can match multiple groups at different
    # line positions, but must produce only one JSON and one LRC output.
    changes = []
    for number, target in enumerate(targets.values(), 1):
        if cancelled is not None and cancelled.is_set():
            raise RuntimeError("ยกเลิกก่อนแก้ไข · เพลงยังไม่เปลี่ยนแปลง")
        parsed = _record_bytes(root, target["record"], export)
        if parsed is None:
            raise ValueError("เนื้อร้องของเพลงที่เลือกไม่ครบ 4 บรรทัด")
        path, lrc, doc, raw = parsed
        # A cached search predicate is only advisory; re-check the complete
        # current lyric body before committing a filtered batch.
        query = _same(search).casefold()
        if query and query not in "\n".join(
                _same(line["text"]).casefold() for line in doc["lines"]):
            raise ValueError("เนื้อร้องเปลี่ยนหลังค้นหา กรุณาตรวจรายการใหม่ก่อนแทนที่")
        revised_doc, revised_lrc = doc, raw
        lost_tokens = 0
        chosen_positions = set()
        for group, item in target["edits"]:
            index = POSITIONS[group["position"]][0]
            if index % len(doc["lines"]) in chosen_positions:
                raise ValueError("พบตำแหน่งที่ถูกเลือกซ้ำในเพลงเดียวกัน")
            chosen_positions.add(index % len(doc["lines"]))
            if _same(doc["lines"][index]["text"]) != group["text"]:
                raise ValueError("ข้อความในเพลงมีการแก้ไขภายหลัง กรุณาวิเคราะห์ใหม่: " + item["code"])
            revised_doc, revised_lrc, removed = _replacement(
                revised_doc, revised_lrc, group["position"], new_text)
            lost_tokens += bool(removed)

        original_json = path.read_bytes()
        new_json = (json.dumps(revised_doc, ensure_ascii=False,
                               separators=(",", ":")) + "\n").encode("utf-8")
        original_files = [(path, original_json, new_json)]
        if lrc is not None:
            if revised_lrc is None:
                raise ValueError("ไม่สามารถสร้าง LRC ที่แก้ไขได้ครบถ้วน: " + target["songId"])
            original_files.append((lrc, lrc.read_bytes(), revised_lrc.encode("utf-8")))
        changes.append({"files": original_files, "songId": target["songId"],
                        "lostTokens": lost_tokens, "updated": revised_doc,
                        "edits": target["edits"]})
        if on_progress and number % 300 == 0:
            on_progress(f"ตรวจและเตรียมสำรอง {number:,}/{len(targets):,} เพลง", number)

    backup_root = Path(backup_root)
    backup_root.mkdir(parents=True, exist_ok=True)
    import shutil
    needed = sum(len(before) for item in changes for _, before, _ in item["files"])
    if shutil.disk_usage(backup_root).free < needed + 32 * 1024 * 1024:
        raise RuntimeError("พื้นที่สำรองเนื้อร้องไม่พอ · ยังไม่ได้แก้ไฟล์ใด")
    operation = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + secrets.token_hex(4)
    zip_path = backup_root / (operation + ".zip")
    manifest_path = backup_root / (operation + ".json")
    specs = []
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=3) as bundle:
        for item in changes:
            for path, original, revised in item["files"]:
                rel = path.relative_to(root).as_posix()
                bundle.writestr(rel, original)
                specs.append({"path": rel, "before": _sha(original),
                              "after": _sha(revised)})
    first = chosen[0][0] if len(chosen) == 1 else None
    manifest = {
        "version": 2, "id": operation, "state": "prepared",
        "root": str(root),
        "position": first["position"] if first else "mixed",
        "oldText": first["text"] if first else f"{len(chosen)} กลุ่มข้อความ",
        "newText": new_text, "groups": list(group_ids),
        "search": _same(search), "songs": len(changes),
        "lines": number_of_lines, "files": specs,
        "createdAt": datetime.now(timezone.utc).isoformat()
    }
    _atomic_bytes(manifest_path,
                  (json.dumps(manifest, ensure_ascii=False) + "\n").encode("utf-8"))
    try:
        for number, item in enumerate(changes, 1):
            if cancelled is not None and cancelled.is_set():
                raise RuntimeError("ผู้ใช้ยกเลิกระหว่างแทนที่ · กำลังคืนค่าเดิม")
            for path, before, revised in item["files"]:
                if _sha(path.read_bytes()) != _sha(before):
                    raise ValueError("ไฟล์เปลี่ยนระหว่างแก้ไข · กำลังคืนค่าเดิม: " + path.name)
                _atomic_bytes(path, revised)
            if on_progress and number % 100 == 0:
                on_progress(f"แทนที่แล้ว {number:,}/{len(changes):,} เพลง", number)
    except BaseException:
        try:
            _restore_files(root, zip_path, specs, strict=False)
            manifest["state"] = "rolled-back"
        except Exception:
            manifest["state"] = "recovery-required"
        _atomic_bytes(manifest_path,
                      (json.dumps(manifest, ensure_ascii=False) + "\n").encode("utf-8"))
        raise

    manifest["state"] = "committed"
    _atomic_bytes(manifest_path,
                  (json.dumps(manifest, ensure_ascii=False) + "\n").encode("utf-8"))
    # Patch only the edited members of the in-memory search/group index. This
    # preserves all other rows, counts and pagination in the operator's queue.
    for group, members in chosen:
        removed = {item["songId"] for item in members}
        was_repeated = group["count"] >= 2
        group["members"][:] = [
            item for item in group["members"] if item["songId"] not in removed]
        group["count"] = len(group["members"])
        # If a searched batch edited only some songs of a repeated group,
        # the one-song remainder must stay visible in the work queue.
        if was_repeated and group["count"] > 0:
            group["queuePending"] = True
        if not group["members"]:
            snapshot["groups"].pop(group["id"], None)
    for item in changes:
        doc = item["updated"]
        snapshot["searchable"][item["songId"]] = "\n".join(
            _same(line["text"]).casefold() for line in doc["lines"])
        for old_group, old_item in item["edits"]:
            position = old_group["position"]
            identity = _group_id(position, new_text)
            group = snapshot["groups"].setdefault(identity, {
                "id": identity, "position": position,
                "label": POSITIONS[position][1],
                "text": new_text, "count": 0, "members": []
            })
            member = dict(old_item)
            member["text"] = new_text
            group["members"].append(member)
            group["count"] = len(group["members"])
    snapshot["groupCount"] = len(snapshot["groups"])
    return {
        "message": (
            f"แก้ข้อความ {len(chosen)} กลุ่ม · {number_of_lines:,} บรรทัด "
            f"ใน {len(changes):,} เพลงเรียบร้อย · รายการที่ยังไม่แก้คงอยู่"
        ),
        "changedSongs": len(changes), "changedLines": number_of_lines,
        "changedGroups": len(chosen),
        "alreadyCorrect": unchanged, "changedFiles": len(specs),
        "removedSyllableCues": sum(item["lostTokens"] for item in changes),
        "backupId": operation,
        "remainingGroups": snapshot["groupCount"],
    }


def _restore_files(root, archive, file_specs, *, strict=True):
    with zipfile.ZipFile(archive) as bundle:
        # Always validate hashes before ANY writes during user-requested undo.
        if strict:
            for spec in file_specs:
                path = (root / spec["path"]).resolve()
                if not path.is_relative_to(root):
                    raise ValueError("พาธไฟล์สำรองไม่ปลอดภัย")
                if not path.is_file() or _sha(path.read_bytes()) != spec["after"]:
                    raise ValueError("ไฟล์มีการแก้ไขภายหลัง ไม่สามารถย้อนคืนทั้งชุดโดยไม่ทับข้อมูลใหม่")
        for spec in file_specs:
            path = (root / spec["path"]).resolve()
            if not path.is_relative_to(root):
                raise ValueError("พาธไฟล์สำรองไม่ปลอดภัย")
            original = bundle.read(spec["path"])
            if _sha(original) != spec["before"]:
                raise ValueError("ไฟล์สำรองไม่ครบหรือถูกเปลี่ยนแปลง")
            if strict or path.is_file() and _sha(path.read_bytes()) == spec["after"]:
                _atomic_bytes(path, original)


def latest_backup(backup_root, root):
    backup_root = Path(backup_root)
    if not backup_root.is_dir():
        return None
    for path in sorted(backup_root.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("root") == str(Path(root).expanduser().resolve()) and data.get("state") in ("committed", "prepared", "recovery-required"):
                return {k: data[k] for k in ("id", "position", "oldText", "newText", "songs", "createdAt", "state")}
        except (ValueError, KeyError, OSError):
            continue
    return None


def undo(backup_root, root, operation):
    root = Path(root).expanduser().resolve()
    if not isinstance(operation, str) or not re.fullmatch(r"\d{8}T\d{12}Z-[0-9a-f]{8}", operation):
        raise ValueError("รหัสชุดสำรองไม่ถูกต้อง")
    base = Path(backup_root)
    manifest_path = base / (operation + ".json")
    backup_zip = base / (operation + ".zip")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    state = data.get("state")
    if data.get("root") != str(root) or state not in ("committed", "prepared", "recovery-required"):
        raise ValueError("ชุดสำรองไม่ตรงกับคลังปัจจุบันหรือย้อนคืนไปแล้ว")
    if state == "committed":
        _restore_files(root, backup_zip, data["files"], strict=True)
    else:
        # Recover a crash/interruption between two atomic file writes:
        # every file must still be either the original or this operation's
        # replacement. Abort if another program changed anything meanwhile.
        for item in data["files"]:
            target = (root / item["path"]).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                raise ValueError("มีไฟล์สูญหายระหว่างการกู้คืน กรุณาตรวจชุดสำรอง")
            checksum = _sha(target.read_bytes())
            if checksum not in (item["before"], item["after"]):
                raise ValueError("มีไฟล์แก้ไขโดยงานอื่นแล้ว ไม่สามารถกู้คืนอย่างปลอดภัย")
        _restore_files(root, backup_zip, data["files"], strict=False)
    data["state"] = "undone"
    _atomic_bytes(manifest_path, (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8"))
    return {"message": f"ย้อนคืนข้อความ {data['songs']:,} เพลงสำเร็จ · ไฟล์เสียงไม่เปลี่ยน",
            "restoredSongs": data["songs"], "backupId": operation}


# Raw-folder mode: edit timed .lrc lyric text in place (without requiring StageWeb).
# Never touch MIDI/audio files. The existing grouping, planning, backup and
# undo contracts also apply to this folder mode.
def _decode_lrc_bytes(payload):
    """Return a round-trippable encoding, BOM and the decoded LRC text."""
    if payload.startswith(b"\xef\xbb\xbf"):
        bom, codec, data = b"\xef\xbb\xbf", "utf-8", payload[3:]
    elif payload.startswith(b"\xff\xfe"):
        bom, codec, data = b"\xff\xfe", "utf-16-le", payload[2:]
    elif payload.startswith(b"\xfe\xff"):
        bom, codec, data = b"\xfe\xff", "utf-16-be", payload[2:]
    else:
        bom, data = b"", payload
        try:
            return data.decode("utf-8"), "utf-8", bom
        except UnicodeDecodeError:
            # Many legacy Thai lyric collections use the Windows-874 charset.
            # Encode edits back to the SAME charset; never silently transcode.
            codec = "cp874"
    text = data.decode(codec, errors="strict")
    if bom + text.encode(codec) != payload:
        raise ValueError("รหัสอักขระเนื้อร้องไม่สามารถเก็บกลับได้โดยไม่เปลี่ยนข้อมูล")
    return text, codec, bom


def _parse_raw_lrc(payload):
    if len(payload) > 1024 * 1024:
        raise ValueError("ข้าม LRC ขนาดเกิน 1 MB")
    raw, codec, bom = _decode_lrc_bytes(payload)
    chunks, found = _timestamped_rows(raw)
    if len(found) < 4:
        raise ValueError("ต้องมีเนื้อร้องแบบมีเวลาอย่างน้อย 4 บรรทัด")
    texts = []
    for _, matched in found:
        tail = matched.group(2)
        # A line with multiple timestamps requires distinct semantics;
        # refuse to bulk-edit it until manually normalized.
        if re.search(r"\[\d{1,3}:[0-5]\d(?:[.:]\d{1,3})?\]", tail):
            raise ValueError("ไม่รองรับ LRC หลายเวลาในบรรทัดเดียว")
        texts.append(_same(ENHANCED.sub("", tail)))
    return chunks, found, texts, codec, bom


def _source_file(root, relative):
    """Allow only real .lrc files strictly within the chosen local folder."""
    if not isinstance(relative, str) or not relative.lower().endswith(".lrc"):
        raise ValueError("ไฟล์เนื้อร้องต้นทางไม่ถูกต้อง")
    name = PurePosixPath(relative)
    if name.is_absolute() or not name.parts or any(part in (".", "..", "") for part in name.parts):
        raise ValueError("พาธเนื้อร้องอยู่นอกโฟลเดอร์ที่เลือก")
    candidate = root.joinpath(*name.parts)
    if candidate.is_symlink() or any(p.is_symlink() for p in (candidate, *candidate.parents) if p != root):
        raise ValueError("ไม่อนุญาตไฟล์หรือโฟลเดอร์ต้นทางแบบลิงก์")
    path = candidate.resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("ไม่พบไฟล์ LRC ภายในโฟลเดอร์ที่เลือก")
    return path


def scan_lrc_folder(root, *, cancelled=None, on_progress=None):
    """Recursively index only timed LRC in an explicitly selected directory."""
    root = Path(root).expanduser().resolve(strict=True)
    grouped = {name: defaultdict(list) for name in POSITIONS}
    searchable, seen, included = {}, set(), 0
    skipped = 0
    inspected = 0
    for directory, folders, files in os.walk(root, topdown=True, followlinks=False):
        if cancelled is not None and cancelled.is_set():
            raise RuntimeError("ยกเลิกการวิเคราะห์แล้ว · ยังไม่ได้แก้ไขไฟล์")
        folders[:] = sorted(f for f in folders if not f.startswith(".") and
                            not (Path(directory) / f).is_symlink())
        for filename in sorted(files):
            if Path(filename).suffix.lower() != ".lrc":
                continue
            inspected += 1
            if inspected > MAX_ROWS:
                raise ValueError("จำนวนไฟล์ LRC เกินขนาดที่รองรับ · เลือกโฟลเดอร์ย่อย")
            path = Path(directory) / filename
            try:
                if path.is_symlink() or not path.is_file():
                    raise ValueError("ไฟล์แบบลิงก์ไม่รองรับ")
                relative = path.relative_to(root).as_posix()
                resolved = _source_file(root, relative)
                original = resolved.read_bytes()
                _, _, texts, _, _ = _parse_raw_lrc(original)
            except (OSError, ValueError, UnicodeError, TypeError):
                skipped += 1
                continue
            song_id = relative
            if song_id in seen:
                continue
            seen.add(song_id)
            included += 1
            record = {"path": relative, "digest": _sha(original)}
            searchable[song_id] = "\n".join(line.casefold() for line in texts)
            for pos, (index, _) in POSITIONS.items():
                phrase = texts[index]
                if not phrase:
                    continue
                ident = _group_id(pos, phrase)
                grouped[pos][ident].append({
                    "songId": song_id, "code": path.stem[:80],
                    "title": path.stem[:140], "artist": "",
                    "text": phrase, "record": record
                })
            if on_progress and inspected % 400 == 0:
                on_progress(f"อ่าน LRC {inspected:,} ไฟล์ · ตรวจใช้ได้ {included:,}", inspected)
    if not inspected:
        raise ValueError(
            "โฟลเดอร์นี้ไม่พบไฟล์ .lrc · เลือกโฟลเดอร์เพลงที่มี LRC หรือคลัง StageWeb "
            "· ไฟล์ MIDI/KAR/NCN ที่ไม่มี LRC ยังไม่รองรับการแทนที่ข้อความโดยตรง")
    if not included:
        raise ValueError(
            f"พบ LRC {inspected:,} ไฟล์ แต่ไม่มีไฟล์ที่ตรวจใช้ได้ · "
            "ต้องมีเนื้อร้องพร้อมเวลาอย่างน้อย 4 บรรทัดและเป็น UTF-8/UTF-16/Windows-874")
    groups = {}
    for pos, mapping in grouped.items():
        for ident, members in mapping.items():
            groups[ident] = {
                "id": ident, "position": pos, "label": POSITIONS[pos][1],
                "text": members[0]["text"], "count": len(members),
                "members": members
            }
    return {
        "root": str(root), "mode": "lrc-folder", "generation": None,
        "groups": groups, "searchable": searchable, "songs": included,
        "inspected": inspected, "skippedInvalid": skipped,
        "withoutLyrics": 0, "groupCount": len(groups)
    }


def apply_many_lrc_folder(root, snapshot, group_ids, new_text, backup_root,
                          *, search="", expected_count, cancelled=None,
                          on_progress=None):
    """Safely replace LRC text; preflight hashes, backup all, write atomically."""
    root = Path(root).expanduser().resolve()
    if snapshot.get("mode") != "lrc-folder" or snapshot["root"] != str(root):
        raise ValueError("โฟลเดอร์หรือผลวิเคราะห์ไม่ตรงกัน กรุณาวิเคราะห์ใหม่")
    new_text = _new_text(new_text)
    targets, chosen, unchanged = _targets(snapshot, group_ids, search, new_text)
    changed_lines = sum(len(target["edits"]) for target in targets.values())
    if type(expected_count) is not int or expected_count != changed_lines:
        raise ValueError("จำนวนบรรทัดที่จะเปลี่ยนไม่ตรง กรุณาตรวจรายการใหม่")
    if not changed_lines:
        raise ValueError("ข้อความเดิมตรงกับข้อความใหม่แล้ว")

    changes = []
    for number, target in enumerate(targets.values(), 1):
        if cancelled is not None and cancelled.is_set():
            raise RuntimeError("ยกเลิกก่อนแก้ไข · ยังไม่ได้เขียนไฟล์")
        record = target["record"]
        path = _source_file(root, record["path"])
        original = path.read_bytes()
        if _sha(original) != record["digest"]:
            raise ValueError("ไฟล์ LRC เปลี่ยนจากตอนวิเคราะห์ กรุณาสแกนใหม่: " + path.name)
        chunks, timed, texts, codec, bom = _parse_raw_lrc(original)
        query = _same(search).casefold()
        if query and query not in "\n".join(line.casefold() for line in texts):
            raise ValueError("เนื้อร้องเปลี่ยนภายหลัง กรุณาวิเคราะห์ใหม่")
        positions = set()
        for group, item in target["edits"]:
            index = POSITIONS[group["position"]][0] % len(timed)
            if index in positions:
                raise ValueError("ตำแหน่งข้อความซ้ำในไฟล์เดียวกัน")
            positions.add(index)
            if texts[index] != group["text"]:
                raise ValueError("ข้อความใน LRC เปลี่ยนหลังวิเคราะห์: " + path.name)
            line_index, match = timed[index]
            # Only replace words. Timestamp, metadata, line endings remain.
            chunks[line_index] = match.group(1) + new_text + match.group(3)
            texts[index] = new_text
        try:
            revised = bom + "".join(chunks).encode(codec, errors="strict")
        except UnicodeEncodeError as exc:
            raise ValueError("ข้อความใหม่ไม่รองรับรหัสอักขระของ LRC: " + path.name +
                             " · กรุณาแปลงเป็น UTF-8 ก่อน") from exc
        changes.append({"path": path, "before": original, "after": revised,
                        "songId": target["songId"],
                        "record": record, "texts": texts,
                        "edits": target["edits"]})
        if on_progress and number % 300 == 0:
            on_progress(f"ตรวจ LRC และเตรียมสำรอง {number:,}/{len(targets):,}", number)

    import shutil
    backup_root = Path(backup_root)
    backup_root.mkdir(parents=True, exist_ok=True)
    needed = sum(len(item["before"]) for item in changes)
    if shutil.disk_usage(backup_root).free < needed + 32 * 1024 * 1024:
        raise RuntimeError("พื้นที่ไม่พอสำหรับสำรอง LRC · ยังไม่มีไฟล์ถูกแก้")
    operation = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + secrets.token_hex(4)
    zip_path = backup_root / (operation + ".zip")
    manifest_path = backup_root / (operation + ".json")
    specs = []
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=3) as bundle:
        for item in changes:
            rel = item["path"].relative_to(root).as_posix()
            bundle.writestr(rel, item["before"])
            specs.append({"path": rel, "before": _sha(item["before"]),
                          "after": _sha(item["after"])})
    first = chosen[0][0] if len(chosen) == 1 else None
    manifest = {
        "version": 2, "id": operation, "state": "prepared", "root": str(root),
        "mode": "lrc-folder",
        "position": first["position"] if first else "mixed",
        "oldText": first["text"] if first else f"{len(chosen)} กลุ่มข้อความ",
        "newText": new_text, "groups": list(group_ids), "search": _same(search),
        "songs": len(changes), "lines": changed_lines, "files": specs,
        "createdAt": datetime.now(timezone.utc).isoformat()
    }
    _atomic_bytes(manifest_path, (json.dumps(manifest, ensure_ascii=False) + "\n").encode("utf-8"))
    try:
        for number, item in enumerate(changes, 1):
            if cancelled is not None and cancelled.is_set():
                raise RuntimeError("ยกเลิกระหว่างแทนที่ · กำลังคืนค่าเดิม")
            path = _source_file(root, item["record"]["path"])
            if _sha(path.read_bytes()) != _sha(item["before"]):
                raise ValueError("ไฟล์ LRC เปลี่ยนขณะทำงาน: " + path.name)
            _atomic_bytes(path, item["after"])
            if on_progress and number % 100 == 0:
                on_progress(f"แทนที่ LRC แล้ว {number:,}/{len(changes):,}", number)
    except BaseException:
        try:
            _restore_files(root, zip_path, specs, strict=False)
            manifest["state"] = "rolled-back"
        except Exception:
            manifest["state"] = "recovery-required"
        _atomic_bytes(manifest_path, (json.dumps(manifest, ensure_ascii=False) + "\n").encode("utf-8"))
        raise
    manifest["state"] = "committed"
    _atomic_bytes(manifest_path, (json.dumps(manifest, ensure_ascii=False) + "\n").encode("utf-8"))
    for group, members in chosen:
        removed = {item["songId"] for item in members}
        was_repeated = group["count"] >= 2
        group["members"][:] = [m for m in group["members"] if m["songId"] not in removed]
        group["count"] = len(group["members"])
        if was_repeated and group["count"] > 0:
            group["queuePending"] = True
        if not group["members"]:
            snapshot["groups"].pop(group["id"], None)
    for item in changes:
        item["record"]["digest"] = _sha(item["after"])
        snapshot["searchable"][item["songId"]] = "\n".join(line.casefold() for line in item["texts"])
        for old_group, old_item in item["edits"]:
            position = old_group["position"]
            ident = _group_id(position, new_text)
            group = snapshot["groups"].setdefault(ident, {
                "id": ident, "position": position,
                "label": POSITIONS[position][1],
                "text": new_text, "count": 0, "members": []
            })
            member = dict(old_item)
            member["text"] = new_text
            group["members"].append(member)
            group["count"] = len(group["members"])
    snapshot["groupCount"] = len(snapshot["groups"])
    return {
        "message": f"แก้ LRC {len(changes):,} ไฟล์ · {changed_lines:,} บรรทัดสำเร็จ · สำรองก่อนแก้แล้ว",
        "changedSongs": len(changes), "changedLines": changed_lines,
        "changedGroups": len(chosen), "alreadyCorrect": unchanged,
        "changedFiles": len(specs), "removedSyllableCues": 0,
        "backupId": operation, "remainingGroups": snapshot["groupCount"]
    }
