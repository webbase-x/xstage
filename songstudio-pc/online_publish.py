"""Publish Song Studio M4A + timed JSON directly into X-Stage Karaoke Online.

Online layout (NOT the local Song Studio pointer format):
    XStageWeb/current.json: {schemaVersion, generation, catalogFileId,
                            deltaFileIds, songCount}
    XStageWeb/catalog-base-<generation>.json: {schemaVersion, songs: [...]}
    XStageWeb/catalog-delta-<generation>.json: {schemaVersion, upserts, removes}
    XStageWeb/AUDIO/{MP3,M4A}/{Songs,Lyrics}/[0-9A-Z]/...
    XStageWeb/VIDEO/{AVI,MPG,VCD,WMV}/...
    XStageWeb/MIDI/NCN/{Songs,Lyrics,Cursor}/[0-9A-Z]/...
    XStageWeb/MIDI/E-MK/[0-9A-Z]/...
    XStageWeb/DB/ (reserved; root current.json stays for web compatibility)
    Existing catalog paths retain their private Drive file IDs.

Never publish a new pointer until media and immutable catalog are uploaded and
MD5 checked. Existing online songs are merged; this is NOT a whole-library
replacement and never deletes or overwrites an existing song.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import tempfile
from pathlib import Path, PurePosixPath

ONLINE_ROOT = "XStageWeb"
FOLDER_MIME = "application/vnd.google-apps.folder"
MAX_CATALOG_BYTES = 128 * 1024 * 1024
MAX_DELTAS = 32

# XStageWeb V2 is the only Drive layout. Local build paths are not Drive paths.
MEDIA_ROOTS = (
    ("AUDIO", "MP3", "Songs"), ("AUDIO", "MP3", "Lyrics"),
    ("AUDIO", "M4A", "Songs"), ("AUDIO", "M4A", "Lyrics"),
    ("VIDEO", "AVI"), ("VIDEO", "MPG"), ("VIDEO", "VCD"), ("VIDEO", "WMV"),
    ("MIDI", "NCN", "Songs"), ("MIDI", "NCN", "Lyrics"),
    ("MIDI", "NCN", "Cursor"), ("MIDI", "E-MK"), ("DB",),
)


def _bucket(code):
    """One directory per ASCII numeral or Latin letter, stable per song code."""
    key = str(code or "").strip().upper()
    if key and key[0] in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        return key[0]
    # Legacy Thai/non-ASCII codes remain representable without extra folders.
    # Use a stable hex hash instead of guessing a letter from the filename.
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[0].upper()


def cloud_media_path(local_relative, source_format="", role="audio", code=""):
    """Return the new Drive path; does not move files or synthesize MIDI."""
    if not isinstance(local_relative, str) or not local_relative:
        raise PublishError("พาธสื่อไม่ถูกต้อง")
    if "\\" in local_relative or ":" in local_relative:
        raise PublishError("พาธสื่อไม่ปลอดภัย")
    path = PurePosixPath(local_relative)
    if (path.is_absolute() or any(p in ("", ".", "..") for p in local_relative.split("/"))
            or any(p in ("", ".", "..") for p in path.parts)):
        raise PublishError("พาธสื่อไม่ปลอดภัย")
    ext = path.suffix.lower()
    bucket = _bucket(code or path.stem)
    typ = "MP3" if ext == ".mp3" else "M4A" if ext == ".m4a" else ""
    if typ:
        leaf = "Lyrics" if role in ("lyrics", "lrc") else "Songs"
        return PurePosixPath("AUDIO", typ, leaf, bucket, path.name)
    if role == "native-timed" and ext == ".json":
        if str(source_format).upper() == "NCN":
            return PurePosixPath("MIDI", "NCN", "Lyrics", bucket, path.name)
        return PurePosixPath("MIDI", "E-MK", bucket, path.name)
    if role in ("lyrics", "lrc") and ext in (".json", ".lrc"):
        # A currently rendered M4A needs its own timed lyrics, even when
        # the sourceFormat says NCN. Native NCN .LYR/.CUR are separate files.
        fmt = "MP3" if str(source_format).upper() == "MP3" else "M4A"
        return PurePosixPath("AUDIO", fmt, "Lyrics", bucket, path.name)
    kind = str(source_format or "").upper()
    if kind == "NCN" and ext in (".mid", ".midi", ".lyr", ".cur"):
        section = ("Songs" if ext in (".mid", ".midi") else
                   "Lyrics" if ext == ".lyr" else "Cursor")
        return PurePosixPath("MIDI", "NCN", section, bucket, path.name)
    if ext in (".mid", ".midi", ".kar", ".emk") or kind in ("E-MK", "EMK"):
        return PurePosixPath("MIDI", "E-MK", bucket, path.name)
    if ext in (".avi", ".mpg", ".mpeg", ".dat", ".wmv"):
        video_kind = {".avi": "AVI", ".mpg": "MPG", ".mpeg": "MPG",
                      ".dat": "VCD", ".wmv": "WMV"}[ext]
        return PurePosixPath("VIDEO", video_kind, path.name)
    raise PublishError("ชนิดไฟล์ที่กำหนดไม่รองรับในโครงสร้าง XStageWeb: " + ext)


class PublishError(RuntimeError):
    pass


def _md5(path):
    checksum = hashlib.md5()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def _local_path(root, path, prefix):
    if not isinstance(path, str) or not path.startswith(prefix + "/"):
        raise PublishError("พาธไฟล์ประกอบไม่ถูกต้อง: " + repr(path))
    item = PurePosixPath(path)
    if item.is_absolute() or any(part in ("", ".", "..") for part in item.parts):
        raise PublishError("พาธไฟล์ประกอบไม่ปลอดภัย: " + path)
    file = (root / Path(*item.parts)).resolve()
    if not file.is_relative_to(root.resolve()) or not file.is_file() or file.is_symlink():
        raise PublishError("ไฟล์เพลง/เนื้อร้องไม่ครบ: " + path)
    return file


def _valid_row(root, row):
    if not isinstance(row, dict) or not row.get("webSongId") or not row.get("code"):
        raise PublishError("ข้อมูลเพลงในฐานท้องถิ่นไม่สมบูรณ์")
    media = row.get("audio") or {}
    lyrics = row.get("lyrics") or {}
    if not lyrics or not lyrics.get("path"):
        return False
    sound = _local_path(root, media.get("path"), "audio")
    lyric = _local_path(root, lyrics["path"], "lyrics")
    if sound.stat().st_size < 1000:
        raise PublishError("M4A ว่างหรือไม่สมบูรณ์: " + sound.name)
    try:
        doc = json.loads(lyric.read_text(encoding="utf-8-sig"))
        assert doc.get("schemaVersion") == 1
        assert isinstance(doc.get("lines"), list) and doc["lines"]
        assert all(isinstance(entry, dict) and isinstance(entry.get("text"), str)
                   and entry["text"].strip()
                   and isinstance(entry.get("startTime"), (int, float))
                   and not isinstance(entry["startTime"], bool)
                   and 0 <= float(entry["startTime"]) < 86400
                   for entry in doc["lines"])
        assert all(doc["lines"][i]["startTime"] <= doc["lines"][i+1]["startTime"]
                   for i in range(len(doc["lines"])-1))
    except (OSError, ValueError, TypeError, AttributeError, AssertionError) as exc:
        raise PublishError("Lyrics JSON ไม่พร้อมเล่นบน X-Stage: " + lyric.name) from exc
    return True


class OnlinePublisher:
    """Private XStageWeb V2 publisher for complete local M4A+timed JSON songs.

    Missing XStageWeb/DB is a new library, not a V1 migration error.
    The only mutable Drive object is DB/current.json. Never publish songs
    directly under the root or store OAuth tokens inside a catalog.
    """
    def __init__(self, drive):
        self.drive = drive

    def _json(self, file_id):
        import urllib.error
        import urllib.parse
        import urllib.request
        url = ("https://www.googleapis.com/drive/v3/files/" +
               urllib.parse.quote(str(file_id), safe="") + "?alt=media")
        request = urllib.request.Request(
            url, headers={"Authorization": "Bearer " + self.drive.token()})
        try:
            with urllib.request.urlopen(request, timeout=120) as stream:
                raw = stream.read(MAX_CATALOG_BYTES + 1)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            raise PublishError("อ่านฐานเพลง V2 จาก Google Drive ไม่ได้") from exc
        if len(raw) > MAX_CATALOG_BYTES:
            raise PublishError("ชิ้นส่วนฐานเพลง V2 ใหญ่เกินขีดจำกัด")
        try:
            obj = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise PublishError("ฐานเพลง V2 ไม่ใช่ JSON ที่ถูกต้อง") from exc
        if not isinstance(obj, dict):
            raise PublishError("ฐานเพลง V2 มีรูปแบบไม่ถูกต้อง")
        return obj

    def _existing_root(self):
        found = [x for x in self.drive.list_children("root")
                 if x.get("name") == ONLINE_ROOT and x.get("mimeType") == FOLDER_MIME]
        if len(found) > 1:
            raise PublishError("พบ XStageWeb ซ้ำใน Google Drive · เลือกคลังไม่ได้อย่างปลอดภัย")
        return found[0]["id"] if found else None

    def _read_v2(self):
        """Read-only snapshot; no Drive folder is created by this call."""
        from v2_native_publish import read_published_v2
        root = self._existing_root()
        if root is None:
            return None, None, None, {}
        folders = [x for x in self.drive.list_children(root)
                   if x.get("name") == "DB" and x.get("mimeType") == FOLDER_MIME]
        if len(folders) > 1:
            raise PublishError("XStageWeb/DB มีโฟลเดอร์ซ้ำ")
        if not folders:
            return root, None, None, {}
        db = folders[0]["id"]
        pointers = [x for x in self.drive.list_children(db)
                    if x.get("name") == "current.json" and x.get("mimeType") != FOLDER_MIME]
        if len(pointers) > 1:
            raise PublishError("พบ DB/current.json ซ้ำ")
        if not pointers:
            return root, db, None, {}
        pointer = self._json(pointers[0]["id"])
        try:
            songs = read_published_v2(self._json, pointer)
        except (ValueError, KeyError, TypeError) as exc:
            raise PublishError("ฐานเพลง V2 เดิมไม่สมบูรณ์ · หยุดก่อนอัปโหลด") from exc
        return root, db, (pointers[0], pointer), songs

    @staticmethod
    def _registry_song(song):
        """Existing local code allocator uses the older *local* audio key."""
        result = dict(song)
        media = song.get("media") or {}
        result["audio"] = media.get("m4a") or media.get("mp3") or {}
        return result

    def read_code_registry(self, *, allow_missing_root=False):
        """An empty accessible Drive is a verified empty V2 code namespace."""
        root, db, active, songs = self._read_v2()
        return {"songs": [self._registry_song(x) for x in songs.values()],
                "generation": active[1]["generation"] if active else "",
                "visible": True, "rootExists": bool(root),
                "catalogExists": bool(active), "schemaVersion": 2}

    def publish(self, local_songs, selected_records, *, create_new_library=False,
                cancelled=None, on_progress=None, on_batch=None, on_row=None,
                batch_size=100):
        from v2_native_publish import write_published_v2, validate_unique_song_codes
        from unified_catalog_v2 import validate_catalog, CATALOG_FORMAT
        local_songs = Path(local_songs).resolve()
        if not (local_songs / "current.json").is_file():
            raise PublishError("กรุณาสร้างฐานเพลงในเครื่องก่อนอัปโหลด")
        if type(batch_size) is not int or not 1 <= batch_size <= 1000:
            raise PublishError("ขนาดชุดเพลงไม่ถูกต้อง")
        ready, not_ready = [], 0
        for row in selected_records:
            if _valid_row(local_songs, row):
                ready.append(row)
            else:
                not_ready += 1
        if not ready:
            raise PublishError("ไม่มีเพลงที่มี M4A และ Lyrics JSON พร้อมเวลาให้เผยแพร่")
        if len({row["webSongId"] for row in ready}) != len(ready):
            raise PublishError("รายการเพลงที่เลือกมี ID ซ้ำ")
        if len({str(row["code"]).casefold() for row in ready}) != len(ready):
            raise PublishError("รายการเพลงมีรหัสเพลงซ้ำ")
        # Preflight all local files and checksums BEFORE creating Drive folders.
        staged = []
        for row in ready:
            sound = _local_path(local_songs, row["audio"]["path"], "audio")
            lyrics = _local_path(local_songs, row["lyrics"]["path"], "lyrics")
            staged.append((row, sound, lyrics, _md5(sound), _md5(lyrics)))
        root, db, active, existing = self._read_v2()
        validate_unique_song_codes(existing)
        by_code = {str(x["code"]).casefold(): x for x in existing.values()}
        by_pair = {}
        for x in existing.values():
            media = (x.get("media") or {}).get("m4a") or {}
            lyric = x.get("lyrics") or {}
            if media.get("md5Checksum") and lyric.get("md5Checksum"):
                by_pair[(media["md5Checksum"].lower(), lyric["md5Checksum"].lower())] = x
        counts = {"newSongs": 0, "updatedSongs": 0, "duplicates": 0,
                  "conflicts": 0, "notReady": not_ready, "filesUploaded": 0,
                  "batches": 0, "published": False}
        # Only create XStageWeb if at least one vetted file is ready to upload.
        if not root:
            root = self.drive.folder("root", ONLINE_ROOT)
        if not db:
            db = self.drive.folder(root, "DB")
        old_pointer = active[1] if active else None
        old_pointer_id = active[0]["id"] if active else None
        folders = {}
        parent_lists = {}
        def folder(parts):
            parent = root
            for index, part in enumerate(parts):
                key = tuple(parts[:index+1])
                if key not in folders:
                    folders[key] = self.drive.folder(parent, part)
                parent = folders[key]
            return parent
        def upload(path, role, code, md5):
            rel = cloud_media_path(path.relative_to(local_songs).as_posix(),
                                   "M4A", role=role, code=code)
            parent = folder(rel.parts[:-1])
            name = rel.stem + "-" + md5[:16] + rel.suffix
            if parent not in parent_lists:
                cache = {}
                for x in self.drive.list_children(parent):
                    cache.setdefault(x.get("name"), []).append(x)
                parent_lists[parent] = cache
            status, meta = self.drive.upload_file(
                parent, path, name, cancelled=cancelled, existing_items=parent_lists[parent])
            if not isinstance(meta.get("id"), str) or meta.get("md5Checksum","").lower() != md5:
                raise PublishError("Google Drive ไม่ยืนยันไฟล์อัปโหลดให้ตรงกับ MD5")
            if status != "skipped":
                counts["filesUploaded"] += 1
            parent_lists[parent].setdefault(name, []).append(meta)
            return {"fileId": meta["id"], "path": str(rel.parent / name),
                    "md5Checksum": md5, "size": path.stat().st_size}
        result = dict(existing)
        revisions = []
        completed_bytes = 0
        total_bytes = sum(x[1].stat().st_size + x[2].stat().st_size for x in staged)
        for index, (row, sound, lyric, sound_md5, lyric_md5) in enumerate(staged, 1):
            if cancelled is not None and cancelled.is_set():
                raise PublishError("ยกเลิกการซิงค์ก่อนเผยแพร่ฐาน V2")
            sid = str(row["webSongId"])
            code = str(row["code"])
            prior = result.get(sid) or by_code.get(code.casefold())
            # Same file contents already known to Drive under any code:
            # skip rather than create another catalog entry.
            if (sound_md5, lyric_md5) in by_pair and not prior:
                counts["duplicates"] += 1
                if on_row: on_row(index, len(staged), not_ready)
                continue
            if prior and (prior["id"] != sid or prior["code"].casefold() != code.casefold()):
                counts["conflicts"] += 1
                if on_row: on_row(index, len(staged), not_ready)
                continue
            previous_audio = ((prior or {}).get("media") or {}).get("m4a") or {}
            if prior and previous_audio.get("md5Checksum","").lower() != sound_md5:
                counts["conflicts"] += 1
                if on_row: on_row(index, len(staged), not_ready)
                continue
            previous_lyrics = (prior or {}).get("lyrics") or {}
            if prior and previous_lyrics.get("md5Checksum","").lower() == lyric_md5:
                counts["duplicates"] += 1
                if on_row: on_row(index, len(staged), not_ready)
                continue
            audio = previous_audio if prior else upload(sound, "audio", code, sound_md5)
            timed = upload(lyric, "lyrics", code, lyric_md5)
            published = {"id": sid, "webSongId": sid, "code": code,
                         "title": str(row.get("title") or code),
                         "artist": str(row.get("artist") or ""),
                         "media": {**((prior or {}).get("media") or {}), "m4a": audio},
                         "lyrics": timed}
            result[sid] = published
            revisions.append(published)
            by_code[code.casefold()] = published
            by_pair[(sound_md5, lyric_md5)] = published
            counts["updatedSongs" if prior else "newSongs"] += 1
            if on_row: on_row(index, len(staged), not_ready)
            completed_bytes += sound.stat().st_size + lyric.stat().st_size
            if on_progress: on_progress(completed_bytes, total_bytes)
        if revisions:
            validate_unique_song_codes(result)
            validate_catalog({"schemaVersion":2, "format":CATALOG_FORMAT,
                              "songs":list(result.values())}, cloud=True)
            def precommit():
                if old_pointer_id:
                    current = self._json(old_pointer_id)
                    if current.get("generation") != old_pointer["generation"]:
                        raise PublishError("ฐาน V2 เปลี่ยนระหว่างอัปโหลด · ไม่เผยแพร่ทับ")
                elif any(x.get("name") == "current.json" for x in self.drive.list_children(db)):
                    raise PublishError("มีฐาน V2 ที่สร้างระหว่างอัปโหลด · โปรดลองใหม่")
            pointer = write_published_v2(self.drive, db, result, previous=old_pointer,
                                         revisions=revisions, cancelled=cancelled,
                                         precommit=precommit)
            counts.update(published=True, batches=1, generation=pointer["generation"])
            if on_batch:
                on_batch(1, len(result), counts["newSongs"], counts["updatedSongs"])
        counts["totalSongs"] = len(result)
        return counts
