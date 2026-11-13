"""Private, bounded, crash-safe editing and preference history.

No Google tokens, OAuth client contents, passwords, or audio bytes are written
into this journal. All state stays under the Windows user's local AppData.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SAFE_PREFS = {"source", "workspace", "download", "soundfont", "midi_preset", "mode"}
MAX_EVENTS = 50
MAX_TEXT = 100_000


def safe_preferences(prefs):
    return {key: str(prefs[key])[:2048] for key in SAFE_PREFS
            if key in prefs and isinstance(prefs[key], str)}


def safe_song(value):
    return {key: str(value.get(key, ""))[:MAX_TEXT]
            for key in ("title", "artist", "lyrics")}


def read(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("events"), list):
            return {"schemaVersion": 1, "events": [
                x for x in data["events"][-MAX_EVENTS:] if isinstance(x, dict)]}
    except (OSError, ValueError, TypeError):
        pass
    return {"schemaVersion": 1, "events": []}


def append(path, kind, target, before, after):
    if before == after:
        return None
    if kind not in ("settings", "song"):
        raise ValueError("Unsupported history entry")
    if kind == "settings":
        before, after = safe_preferences(before), safe_preferences(after)
    else:
        before, after = safe_song(before), safe_song(after)
    if before == after:
        return None
    import secrets
    event = {"id": secrets.token_hex(12), "kind": kind,
             "target": str(target)[:1024],
             "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "before": before, "after": after}
    doc = read(path)
    doc["events"].append(event)
    doc["events"] = doc["events"][-MAX_EVENTS:]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return event


def list_events(path):
    doc = read(path)
    # The UI never needs full lyric texts or local paths from song snapshots.
    return [{"id": event.get("id"), "kind": event.get("kind"),
             "createdAt": event.get("createdAt"),
             "target": (Path(event.get("target", "")).name
                        if event.get("kind") == "song" else "การตั้งค่า"),
             "summary": ("แก้ไขข้อมูลเพลง" if event.get("kind") == "song"
                         else "เปลี่ยนการตั้งค่า")}
            for event in reversed(doc["events"])]


def get_event(path, ident):
    if not isinstance(ident, str):
        raise ValueError("History ID is invalid")
    for event in read(path)["events"]:
        if event.get("id") == ident:
            return event
    raise ValueError("ไม่พบรายการประวัติที่เลือก")
