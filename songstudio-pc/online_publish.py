"""Publish Song Studio M4A + timed JSON directly into X-Stage Karaoke Online.

Online layout (NOT the local Song Studio pointer format):
    XStageWeb/current.json: {schemaVersion, generation, catalogFileId,
                            deltaFileIds, songCount}
    XStageWeb/catalog-base-<generation>.json: {schemaVersion, songs: [...]}
    XStageWeb/catalog-delta-<generation>.json: {schemaVersion, upserts, removes}
    XStageWeb/songs/{audio,lyrics,vocals}/...  (private Drive files)

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
        assert isinstance(doc.get("lines"), list) and doc["lines"]
        assert all(isinstance(entry, dict) and isinstance(entry.get("text"), str)
                   and isinstance(entry.get("startTime"), (int, float))
                   for entry in doc["lines"])
    except (OSError, ValueError, TypeError, AttributeError, AssertionError) as exc:
        raise PublishError("Lyrics JSON ไม่พร้อมเล่นบน X-Stage: " + lyric.name) from exc
    return True


class OnlinePublisher:
    def __init__(self, drive):
        self.drive = drive

    def _json(self, file_id):
        """Read large immutable catalogs without the small OAuth API JSON limit."""
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
            raise PublishError("อ่านฐานเพลงเดิมใน Google Drive ไม่ได้ · ตรวจสิทธิ์ drive.file") from exc
        if len(raw) > MAX_CATALOG_BYTES:
            raise PublishError("ฐานเพลง Google Drive ใหญ่เกินขอบเขตความปลอดภัย")
        try:
            obj = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise PublishError("อ่านฐานเพลง Google Drive ไม่สำเร็จ") from exc
        if not isinstance(obj, dict):
            raise PublishError("โครงสร้างฐานเพลงบน Drive ไม่ถูกต้อง")
        return obj

    def _metadata(self, file_id):
        result = self.drive.api("/files/" + str(file_id),
                                {"fields": "id,name,mimeType,size,md5Checksum"})
        if not result.get("md5Checksum"):
            raise PublishError("Google Drive ไม่ให้ค่า MD5 เพื่อตรวจเพลงซ้ำ: " + str(file_id))
        return result

    def _existing_root(self):
        found = [x for x in self.drive.list_children("root") if
                 x.get("name") == ONLINE_ROOT and x.get("mimeType") == FOLDER_MIME]
        if len(found) > 1:
            raise PublishError("พบโฟลเดอร์ XStageWeb ซ้ำหลายรายการ: กรุณาเลือกคลังที่ถูกต้องก่อน")
        return found[0]["id"] if found else None

    def _read_online(self, root):
        if not root:
            return None, {}, {}
        children = self.drive.list_children(root)
        pointers = [x for x in children if x.get("name") == "current.json"
                    and x.get("mimeType") != FOLDER_MIME]
        if len(pointers) > 1:
            raise PublishError("พบ XStageWeb/current.json ซ้ำบน Drive · หยุดเพื่อป้องกันฐานเสีย")
        if not pointers:
            if children:
                raise PublishError("XStageWeb มีไฟล์เดิมแต่ไม่มี current.json · ไม่สร้างฐานใหม่ทับ")
            return None, {}, {}
        pointer_file = pointers[0]
        pointer = self._json(pointer_file["id"])
        ids = pointer.get("deltaFileIds", [])
        if (pointer.get("schemaVersion") != 1
                or not isinstance(pointer.get("catalogFileId"), str)
                or not pointer["catalogFileId"]
                or not isinstance(ids, list) or len(ids) > MAX_DELTAS
                or any(not isinstance(i, str) for i in ids)
                or len(set(ids)) != len(ids)):
            raise PublishError("ฐาน XStageWeb/current.json ไม่เข้ากับ X-Stage Online")
        base = self._json(pointer["catalogFileId"])
        if base.get("schemaVersion") != 1 or not isinstance(base.get("songs"), list):
            raise PublishError("ฐานเพลงหลักของ XStageWeb ไม่ถูกต้อง")
        songs = {}
        for item in base["songs"]:
            if not isinstance(item, dict) or not isinstance(item.get("webSongId"), str):
                raise PublishError("ข้อมูลเพลงเดิมบน Drive ไม่ถูกต้อง")
            songs[item["webSongId"]] = item
        for ident in ids:
            delta = self._json(ident)
            if (delta.get("schemaVersion") != 1 or not isinstance(delta.get("upserts"), list)
                    or not isinstance(delta.get("removes"), list)):
                raise PublishError("ฐานเพลงส่วนอัปเดตบน Drive ไม่สมบูรณ์")
            for ident in delta["removes"]:
                if not isinstance(ident, str):
                    raise PublishError("รายการลบเพลงในฐาน Drive ไม่ถูกต้อง")
                songs.pop(ident, None)
            for item in delta["upserts"]:
                if not isinstance(item, dict) or not isinstance(item.get("webSongId"), str):
                    raise PublishError("เพลงในฐานอัปเดตไม่ถูกต้อง")
                songs[item["webSongId"]] = item
        if pointer.get("songCount") != len(songs):
            raise PublishError("จำนวนเพลงบน Drive ไม่ตรงกับฐาน XStageWeb · ไม่เผยแพร่ทับ")
        return (pointer_file, pointer), songs, {x["name"]: x for x in children}

    def publish(self, local_songs, selected_records, *, cancelled=None, on_progress=None):
        local_songs = Path(local_songs)
        if not (local_songs / "current.json").is_file():
            raise PublishError("กรุณาสร้างฐานเพลงในเครื่องก่อนอัปโหลด")
        ready = []
        not_ready = 0
        for row in selected_records:
            if _valid_row(local_songs, row):
                ready.append(row)
            else:
                not_ready += 1
        if not ready:
            raise PublishError("ยังไม่มีเพลงพร้อมใช้ X-Stage Online: ต้องมี M4A และ Lyrics JSON พร้อมเวลาจริง")
        root = self._existing_root()
        active, remote, root_files = self._read_online(root)
        pointer_file, old_pointer = active if active else (None, None)
        by_code = {}
        for item in remote.values():
            by_code.setdefault(str(item.get("code") or "").casefold(), []).append(item)
        # Compute duplicate evidence only for same-code candidates. Never skip
        # or overwrite on title match alone. Older clients may use an unrelated
        # OAuth app; in that case a metadata 403 must stop safely.
        revisions = []
        counts = {"newSongs": 0, "updatedSongs": 0, "duplicates": 0,
                  "conflicts": 0, "notReady": not_ready, "filesUploaded": 0}
        root_id = root
        folder_cache = {}
        def ensure_root():
            nonlocal root_id
            if not root_id:
                root_id = self.drive.folder("root", ONLINE_ROOT)
            return root_id
        def folder(parts):
            parent = ensure_root()
            key = ""
            for name in parts:
                key += "/" + name
                if key not in folder_cache:
                    folder_cache[key] = self.drive.folder(parent, name)
                parent = folder_cache[key]
            return parent
        def upload(local_file, rel):
            checksum = _md5(local_file)
            path = PurePosixPath(rel)
            # Immutable, content-named media avoids overwriting an older song
            # with the same basename and prevents blind filename deduplication.
            name = path.stem + "-" + checksum[:16] + path.suffix
            parent = folder(("songs", *path.parts[:-1]))
            result, meta = self.drive.upload_file(
                parent, local_file, name, cancelled=cancelled,
                on_progress=on_progress)
            if result == "created":
                counts["filesUploaded"] += 1
            return {"fileId": meta["id"], "path": "songs/" +
                    str(path.parent).replace("\\", "/") + "/" + name,
                    "size": local_file.stat().st_size}
        for i, row in enumerate(ready, 1):
            if cancelled and cancelled.is_set():
                raise PublishError("ยกเลิกซิงค์ Google Drive · ฐานที่ใช้อยู่ยังไม่เปลี่ยน")
            code = str(row["code"]).casefold()
            sound = _local_path(local_songs, row["audio"]["path"], "audio")
            lyric = _local_path(local_songs, row["lyrics"]["path"], "lyrics")
            s_hash, l_hash = _md5(sound), _md5(lyric)
            candidates = list(by_code.get(code, []))
            exact_id = remote.get(str(row["webSongId"]))
            if exact_id and exact_id not in candidates:
                candidates.append(exact_id)
            same_audio, same_both = None, None
            for candidate in candidates:
                if str(candidate.get("code") or "").casefold() != code:
                    continue
                a_id = (candidate.get("audio") or {}).get("fileId")
                l_id = (candidate.get("lyrics") or {}).get("fileId")
                if not a_id or not l_id:
                    continue
                if self._metadata(a_id)["md5Checksum"].lower() == s_hash:
                    same_audio = candidate
                    if self._metadata(l_id)["md5Checksum"].lower() == l_hash:
                        same_both = candidate
                        break
            if same_both:
                counts["duplicates"] += 1
                continue
            if candidates and not same_audio:
                # A matching code with DIFFERENT audio is ambiguous even when
                # title/artist happen to match. Keep old song and flag conflict.
                counts["conflicts"] += 1
                continue
            audio = (dict(same_audio["audio"]) if same_audio else
                     upload(sound, row["audio"]["path"]))
            lyrics = upload(lyric, row["lyrics"]["path"])
            lrc_path = str(Path(row["lyrics"]["path"]).with_suffix(".lrc")).replace("\\", "/")
            if (local_songs / lrc_path).is_file():
                upload(_local_path(local_songs, lrc_path, "lyrics"), lrc_path)
            vocals = None
            if row.get("vocals") and row["vocals"].get("path"):
                src = _local_path(local_songs, row["vocals"]["path"], "audio")
                vocals = upload(src, row["vocals"]["path"])
            ident = (str(same_audio["webSongId"]) if same_audio else str(row["webSongId"]))
            item = {"webSongId": ident, "code": str(row["code"]),
                    "title": str(row.get("title") or row["code"]),
                    "artist": str(row.get("artist") or ""),
                    "sourceFormat": str(row.get("sourceFormat") or ""),
                    "audio": audio, "lyrics": lyrics}
            if vocals:
                item["vocals"] = vocals
            elif same_audio and same_audio.get("vocals"):
                item["vocals"] = same_audio["vocals"]
            remote[ident] = item
            revisions.append(item)
            by_code.setdefault(code, []).append(item)
            counts["updatedSongs" if same_audio else "newSongs"] += 1
        if not revisions:
            counts["published"] = False
            counts["totalSongs"] = len(remote)
            return counts
        if cancelled and cancelled.is_set():
            raise PublishError("ยกเลิกก่อนเผยแพร่ฐานเพลง · ฐานเดิมยังใช้ได้")
        generation = secrets.token_hex(12)
        with tempfile.TemporaryDirectory(prefix="xstage-online-publish-") as temp:
            def push_json(name, document):
                path = Path(temp) / name
                path.write_text(json.dumps(document, ensure_ascii=False,
                                           separators=(",", ":")), encoding="utf-8")
                _, metadata = self.drive.upload_file(
                    ensure_root(), path, name, cancelled=cancelled)
                return metadata["id"]
            if old_pointer and len(old_pointer.get("deltaFileIds", [])) < MAX_DELTAS:
                delta_id = push_json("catalog-delta-" + generation + ".json", {
                    "schemaVersion": 1, "upserts": revisions, "removes": []})
                catalog_id = old_pointer["catalogFileId"]
                delta_ids = [*old_pointer.get("deltaFileIds", []), delta_id]
            else:
                catalog_id = push_json("catalog-base-" + generation + ".json", {
                    "schemaVersion": 1, "songs": list(remote.values())})
                delta_ids = []
            next_pointer = {
                "schemaVersion": 1, "generation": generation,
                "catalogFileId": catalog_id, "deltaFileIds": delta_ids,
                "songCount": len(remote)
            }
            # Detect a new external publication before switching current.json.
            # Only one publisher should write to a shared XStageWeb library.
            if pointer_file:
                current = self._json(pointer_file["id"])
                if current.get("generation") != old_pointer.get("generation"):
                    raise PublishError("ฐาน Drive มีผู้อื่นอัปเดตระหว่างซิงค์ · กรุณาซิงค์ใหม่")
            push_path = Path(temp) / "current.json"
            push_path.write_text(json.dumps(next_pointer, ensure_ascii=False,
                                            separators=(",", ":")), encoding="utf-8")
            self.drive.upload_file(ensure_root(), push_path, "current.json",
                                   replace_pointer=True, cancelled=cancelled)
        counts["published"] = True
        counts["totalSongs"] = len(remote)
        counts["generation"] = generation
        return counts
