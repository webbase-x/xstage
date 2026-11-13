"""XStageWeb V2 native media publisher, separate from the M4A-only V1 pipeline.

No deletion or mutation of V1 pointers. A V2 catalog is committed in
XStageWeb/DB/current.json only after each immutable media upload succeeds.
"""
from __future__ import annotations
import hashlib
import json
import secrets
import tempfile
from pathlib import Path, PurePosixPath

from online_publish import cloud_media_path, PublishError, OnlinePublisher
from ncn_lyrics import ncn_document, kar_document

MAX_MANIFEST_SONGS = 1000000
MAX_MEDIA_BYTES = 2 * 1024 * 1024 * 1024
ALLOWED = {
    "mp3": {".mp3"},
    "m4a": {".m4a"},
    "ncn": {".mid", ".midi"},
    "emk": {".mid", ".midi", ".kar", ".emk"},
    "avi": {".avi"},
    "mpg": {".mpg", ".mpeg"},
    "vcd": {".dat"},
    "wmv": {".wmv"},
}


def secure_file(root: Path, name: str, extensions: set[str]) -> Path:
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise PublishError("ไม่อนุญาตพาธไฟล์ที่ไม่ปลอดภัย")
    rel = PurePosixPath(name)
    if rel.is_absolute() or any(p in ("", ".", "..") for p in name.split("/")):
        raise PublishError("พาธไฟล์ไม่ปลอดภัย")
    if rel.suffix.lower() not in extensions:
        raise PublishError("นามสกุลไฟล์ไม่ตรงกับประเภท")
    resolved = (root / Path(*rel.parts)).resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file() or resolved.is_symlink():
        raise PublishError("ไม่พบไฟล์ต้นฉบับหรือเป็น symlink")
    size = resolved.stat().st_size
    if not 0 < size <= MAX_MEDIA_BYTES:
        raise PublishError("ไฟล์มีขนาดไม่ถูกต้องหรือใหญ่เกินเกณฑ์")
    return resolved


def digest(path):
    m = hashlib.md5()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            m.update(block)
    return m.hexdigest()


def _read_song(root, item):
    if not isinstance(item, dict):
        raise PublishError("รายการเพลงไม่ใช่ object")
    code = str(item.get("code") or "").strip()
    ident = str(item.get("id") or code).strip()
    if not ident or not code or "/" in code or "\\" in code or len(code) > 64:
        raise PublishError("รหัสเพลงไม่ถูกต้อง")
    if not isinstance(item.get("sources"), dict) or not item["sources"]:
        raise PublishError("ต้องมีเพลงต้นฉบับอย่างน้อยหนึ่งชนิด")
    media = {}
    for kind, val in item["sources"].items():
        kind = str(kind).lower()
        if kind not in ALLOWED or kind in media:
            raise PublishError("ประเภทสื่อไม่ถูกต้อง: " + kind)
        if kind == "ncn":
            if not isinstance(val, dict) or not all(isinstance(val.get(k), str) for k in ("song", "lyrics", "cursor")):
                raise PublishError("NCN ต้องมี MID, LYR, CUR")
            files = {
                "song": secure_file(root, val["song"], ALLOWED["ncn"]),
                "lyrics": secure_file(root, val["lyrics"], {".lyr"}),
                "cursor": secure_file(root, val["cursor"], {".cur"}),
            }
            if len({x.stem.casefold() for x in files.values()}) != 1:
                raise PublishError("ชื่อรหัส NCN ทั้งสามไฟล์ไม่ตรงกัน")
            media[kind] = files
        else:
            file = secure_file(root, val, ALLOWED[kind])
            media[kind] = {"song": file}
    lyrics = None
    if item.get("timedLyrics") is not None:
        file = secure_file(root, item["timedLyrics"], {".json"})
        try:
            doc = json.loads(file.read_text(encoding="utf-8-sig"))
            if (doc.get("schemaVersion") != 1 or not isinstance(doc.get("lines"), list)
                    or not doc["lines"] or any(not isinstance(x.get("text"), str)
                    or not isinstance(x.get("startTime"), (int, float))
                    for x in doc["lines"])):
                raise ValueError("invalid lyrics")
        except (ValueError, TypeError, AttributeError, UnicodeError) as ex:
            raise PublishError("Lyrics JSON ไม่ถูกต้อง") from ex
        lyrics = file
    return {"id": ident, "code": code, "title": str(item.get("title") or code),
            "artist": str(item.get("artist") or ""), "media": media, "lyrics": lyrics}


class V2NativePublisher:
    def __init__(self, drive):
        self.drive = drive
        self.reader = OnlinePublisher(drive)

    def publish(self, root_path: Path, manifest: dict, *, create_new_library=False,
                cancelled=None, on_progress=None):
        root_path = Path(root_path).resolve()
        items = manifest.get("songs") if isinstance(manifest, dict) and manifest.get("schemaVersion") == 2 else None
        if not isinstance(items, list) or not 0 < len(items) <= MAX_MANIFEST_SONGS:
            raise PublishError("Manifest V2 ไม่ถูกต้อง")
        songs = [_read_song(root_path, x) for x in items]
        if len({x["id"] for x in songs}) != len(songs):
            raise PublishError("พบ ID เพลงซ้ำในรายการอัปโหลด")
        if len({x["code"].casefold() for x in songs}) != len(songs):
            raise PublishError("พบรหัสเพลงซ้ำในรายการอัปโหลด")
        roots = [x for x in self.drive.list_children("root")
                 if x.get("name") == "XStageWeb" and
                 x.get("mimeType") == "application/vnd.google-apps.folder"]
        if len(roots) > 1:
            raise PublishError("พบ XStageWeb ซ้ำหลายโฟลเดอร์")
        if not roots and not create_new_library:
            raise PublishError("ไม่พบ XStageWeb ที่แอปเข้าถึงได้ · ต้องยืนยันการสร้างคลังใหม่")
        root = roots[0]["id"] if roots else self.drive.folder("root", "XStageWeb")
        db = self.drive.folder(root, "DB")
        current = [x for x in self.drive.list_children(db)
                   if x.get("name") == "current.json" and
                   x.get("mimeType") != "application/vnd.google-apps.folder"]
        if len(current) > 1:
            raise PublishError("DB/current.json ซ้ำ")
        # Re-read the active V2 pointer, merge by ID, and preserve other entries.
        previous, existing = None, {}
        if current:
            previous = self.reader._json(current[0]["id"])
            if previous.get("schemaVersion") != 2:
                raise PublishError("DB/current.json ไม่ใช่ Schema V2")
            catalog = self.reader._json(previous["catalogFileId"])
            if catalog.get("schemaVersion") != 2:
                raise PublishError("ฐานเพลง V2 ไม่ถูกต้อง")
            existing = {s["id"]: s for s in catalog.get("songs", [])}
        directory_cache = {}
        def folder(parts):
            parent = root
            prefix = ""
            for part in parts:
                prefix += "/" + part
                if prefix not in directory_cache:
                    directory_cache[prefix] = self.drive.folder(parent, part)
                parent = directory_cache[prefix]
            return parent
        def upload(path, media_type, role, code):
            rel = cloud_media_path(path.name, source_format=media_type, role=role, code=code)
            parent = folder(rel.parts[:-1])
            md5 = digest(path)
            file_name = rel.stem + "-" + md5[:16] + rel.suffix
            status, meta = self.drive.upload_file(parent, path, file_name,
                                                   cancelled=cancelled)
            remote_md5 = meta.get("md5Checksum")
            if remote_md5 and remote_md5.lower() != md5.lower():
                raise PublishError("Google Drive checksum ไม่ตรงกัน")
            return {"fileId": meta["id"], "path": str(rel.parent / file_name),
                    "md5Checksum": md5, "size": path.stat().st_size}
        result = dict(existing)
        for index, item in enumerate(songs, 1):
            if cancelled is not None and cancelled.is_set():
                raise PublishError("ยกเลิกก่อนเผยแพร่ฐาน V2")
            media = {}
            for kind, group in item["media"].items():
                src_kind = "NCN" if kind == "ncn" else "E-MK" if kind == "emk" else ""
                payload = {}
                for role, path in group.items():
                    route_role = {"song": "audio", "lyrics": "ncn-lyrics",
                                  "cursor": "ncn-cursor"}[role]
                    payload[role] = upload(path, src_kind or kind, route_role, item["code"])
                if kind in ("mp3", "m4a", "avi", "mpg", "vcd", "wmv", "emk"):
                    media[kind if kind not in ("avi", "mpg", "vcd", "wmv") else "video"] = (
                        {"type":kind, **payload["song"]})
                else:
                    media["midi"] = {"type":"ncn", **payload["song"],
                                     "lyr":payload["lyrics"], "cur":payload["cursor"]}
            lyrics = upload(item["lyrics"], "M4A", "lyrics", item["code"]) if item["lyrics"] else None
            # Derive verified timing from original CUR/LYR or embedded KAR events;
            # never guess lyric timing from MIDI notes. Publish lyrics JSON
            # together with the native track so the stage can stream it.
            if lyrics is None and ("ncn" in item["media"] or
                    ("emk" in item["media"] and item["media"]["emk"]["song"].suffix.lower()==".kar")):
                with tempfile.TemporaryDirectory(prefix="xstage-midi-timing-") as tmpdir:
                    try:
                        if "ncn" in item["media"]:
                            trio=item["media"]["ncn"]
                            doc=ncn_document({"midi":trio["song"],"lyrics":trio["lyrics"],
                                              "cursor":trio["cursor"]})
                            native_type="NCN"
                        else:
                            doc=kar_document(item["media"]["emk"]["song"],item["code"])
                            native_type="E-MK"
                        if not doc.get("lines"):
                            raise ValueError("missing timed lyric lines")
                    except (OSError, ValueError, TypeError) as ex:
                        raise PublishError("ซิงค์ MIDI/NCN Lyrics ไม่สำเร็จ: "+str(ex)) from ex
                    tmp=Path(tmpdir)/(item["code"]+".json")
                    tmp.write_text(json.dumps(doc,ensure_ascii=False),encoding="utf-8")
                    lyrics=upload(tmp,native_type,"native-timed",item["code"])
            result[item["id"]] = {
                "id": item["id"], "webSongId": item["id"], "code": item["code"],
                "title": item["title"], "artist": item["artist"],
                "media": media, "lyrics": lyrics
            }
            if on_progress: on_progress(index, len(songs))
        if current:
            fresh = self.reader._json(current[0]["id"])
            if fresh.get("generation") != previous.get("generation"):
                raise PublishError("ฐาน V2 ถูกอัปเดตระหว่างอัปโหลด")
        generation = secrets.token_hex(12)
        with tempfile.TemporaryDirectory(prefix="xstage-db-v2-") as temp:
            target = Path(temp)
            catalog_file = target / "catalog.json"
            catalog_file.write_text(json.dumps({"schemaVersion":2,"songs":list(result.values())},
                                               ensure_ascii=False,separators=(",",":")),encoding="utf-8")
            _, catalog_meta = self.drive.upload_file(db,catalog_file,
                                     "catalog-base-v2-"+generation+".json",cancelled=cancelled)
            pointer_file = target / "current.json"
            pointer_file.write_text(json.dumps({"schemaVersion":2,"generation":generation,
                                "catalogFileId":catalog_meta["id"],
                                "songCount":len(result)},separators=(",",":")),encoding="utf-8")
            self.drive.upload_file(db,pointer_file,"current.json",replace_pointer=True,cancelled=cancelled)
        return {"generation":generation,"newSongs":len(songs),"totalSongs":len(result)}
