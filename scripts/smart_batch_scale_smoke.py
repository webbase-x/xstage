"""Ten-thousand-song Smart Batch integration and bounded-RAM smoke.

Run only in CI stress job, not during a normal PC startup. Uses a disposable
temporary local catalog; no Drive, real music, credentials or source NCN.
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bulk = load("xstage_stress_bulk", "songstudio-pc/lyric_text_groups.py")
export = load("xstage_stress_export", "songstudio-pc/song_export.py")
COUNT = 10000

with tempfile.TemporaryDirectory(prefix="xstage-bulk-10k-") as work:
    root = Path(work) / "songs"
    output = root / "audio" / "0"
    lyrics = root / "lyrics" / "0"
    output.mkdir(parents=True)
    lyrics.mkdir(parents=True)
    records = []
    start = time.monotonic()
    doc = {
        "schemaVersion": 1, "lines": [
            {"text": "HELLO", "startTime": 1.0, "endTime": 3.0,
             "syllables": [{"text": char, "start": 1.0 + i*.2, "duration": .2}
                           for i, char in enumerate("HELLO")]},
            {"text": "middle 1", "startTime": 3.0, "endTime": 5.0},
            {"text": "middle 2", "startTime": 5.0, "endTime": 7.0},
            {"text": "LAST", "startTime": 7.0, "endTime": 9.0},
        ]
    }
    bytes_json = (json.dumps(doc, ensure_ascii=False) + "\n").encode("utf-8")
    for i in range(COUNT):
        code = f"{i:05d}"
        (output / (code + ".m4a")).write_bytes(b"x" * 1200)
        (lyrics / (code + ".json")).write_bytes(bytes_json)
        records.append({
            "webSongId": "audio/0/" + code, "code": code, "bucket": "0",
            "title": "Test " + code, "artist": "Tester", "mode": "original",
            "sourceFormat": "MP3", "vocals": None,
            "audio": {"path": f"audio/0/{code}.m4a", "size": 1200},
            "lyrics": {"path": f"lyrics/0/{code}.json"},
        })
    export.publish_batch(root, records)
    print(f"PREP: {COUNT:,} synthetic songs in {time.monotonic()-start:.2f}s", flush=True)

    snapshot = bulk.scan(root, export)
    assert snapshot["songs"] == COUNT, snapshot["songs"]
    first = bulk.list_groups(snapshot, "first")["rows"]
    assert len(first) == 1 and first[0]["count"] == COUNT, first

    tick = time.monotonic()
    result = bulk.apply_many_smart(
        root, export, snapshot, [first[0]["id"]], "HELLO (NEW)",
        Path(work) / "backups", expected_count=COUNT)
    assert result["changedSongs"] == COUNT, result
    assert result["changedLines"] == COUNT, result
    assert result["skippedInvalid"] == 0, result
    assert result["estimatedLines"] == COUNT, result
    changed_seconds = time.monotonic() - tick
    for idx in range(0, COUNT, 127):
        file = lyrics / f"{idx:05d}.json"
        revised = json.loads(file.read_text(encoding="utf-8"))
        assert revised["lines"][0]["text"] == "HELLO (NEW)"
        starts = [x["start"] for x in revised["lines"][0]["syllables"]]
        assert all(a <= b for a, b in zip(starts, starts[1:]))
        assert starts[0] == 1.0
    print(f"PASS: {COUNT:,} Smart Batch changes, one backup, no skips; "
          f"edit {changed_seconds:.2f}s", flush=True)

    tick = time.monotonic()
    undone = bulk.undo(Path(work) / "backups", root, result["backupId"])
    assert undone["restoredSongs"] == COUNT
    for idx in range(0, COUNT, 127):
        assert (lyrics / f"{idx:05d}.json").read_bytes() == bytes_json
        assert (output / f"{idx:05d}.m4a").read_bytes() == b"x" * 1200
    print(f"PASS: {COUNT:,} songs Undo after {time.monotonic()-tick:.2f}s; "
          f"total {time.monotonic()-start:.2f}s", flush=True)
