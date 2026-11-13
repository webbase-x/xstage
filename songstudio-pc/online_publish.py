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

ONLINE_ROOT = "StageWeb"
LEGACY_ONLINE_ROOT = "XStageWeb"
STAGING_MARKER = ".xstage-songstudio-staging.json"
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
        # Existing XStageWeb databases keep their original Google Drive ID.
        # Never generate a second StageWeb tree when the legacy library is
        # already visible; code and MD5 duplicate checks must cover both.
        found = [x for x in self.drive.list_children("root") if
                 x.get("name") in (ONLINE_ROOT, LEGACY_ONLINE_ROOT) and
                 x.get("mimeType") == FOLDER_MIME]
        if len(found) > 1:
            raise PublishError(
                "พบคลัง StageWeb และ XStageWeb มากกว่าหนึ่งรายการ · "
                "หยุดก่อนอัปโหลดเพื่อไม่ให้แยกฐานเพลงซ้ำ "
                "กรุณาตรวจเลือกคลังเดิมให้ชัดเจน")
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
                markers = [x for x in children if x.get("name") == STAGING_MARKER
                           and x.get("mimeType") != FOLDER_MIME]
                expected = {STAGING_MARKER, "songs", "audio", "lyrics"}
                if (len(markers) == 1 and all(x.get("name") in expected for x in children)
                        and self._json(markers[0]["id"]).get("format") ==
                        "xstage-songstudio-upload-staging-v1"):
                    # Previous first-time upload stopped before its first
                    # published pointer. Resume only our own verified staging
                    # work, never a foreign, unindexed XStageWeb library.
                    return None, {}, {x["name"]: x for x in children}
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

    def read_code_registry(self, *, allow_missing_root=False):
        """Return a verified code snapshot from the ACTUAL private XStageWeb DB.

        An invisible existing library is never interpreted as an empty catalog.
        This is read-only; no staging markers, Drive folders or music are made.
        """
        root = self._existing_root()
        if root is None:
            if allow_missing_root:
                return {"songs": [], "generation": "", "visible": False}
            raise PublishError(
                "ไม่พบคลัง XStageWeb/StageWeb เดิมที่ Google OAuth ของ Song Studio เข้าถึงได้ "
                "· ห้ามอ้างว่าไม่มีรหัสซ้ำจนกว่าจะเชื่อมต่อคลังเดิม")
        active, songs, _ = self._read_online(root)
        if active is None:
            if allow_missing_root:
                return {"songs": [], "generation": "", "visible": False}
            raise PublishError("คลัง XStageWeb ยังไม่มี current.json ที่ตรวจยืนยันได้ "
                               "· ไม่สามารถกำหนดรหัสจากสองแหล่ง")
        _, pointer = active
        return {"songs": list(songs.values()), "generation": pointer["generation"],
                "visible": True}

    def publish(self, local_songs, selected_records, *, create_new_library=False,
                cancelled=None, on_progress=None, on_batch=None, on_row=None,
                batch_size=100):
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
        if type(batch_size) is not int or not 1 <= batch_size <= 1000:
            raise PublishError("ขนาดชุดเผยแพร่ต้องอยู่ระหว่าง 1–1000 เพลง")
        root = self._existing_root()
        # drive.file is app-scoped. If the existing Karaoke Online library was
        # created by a different OAuth application, it may be invisible here.
        # Never silently make a second XStageWeb and strand the old songs.
        if root is None and not create_new_library:
            raise PublishError(
                "ไม่พบ XStageWeb/StageWeb ที่บัญชี/แอปนี้เข้าถึงได้ · "
                "หากมีเพลงเดิม ห้ามสร้างคลังใหม่จนกว่าจะอนุญาตให้ Song Studio "
                "เข้าถึงคลังเดิมผ่าน Google OAuth/Picker · "
                "ถ้าเป็น Google Drive ว่างจริง ให้เลือก 'สร้างคลังใหม่' โดยชัดเจน")
        if root is None:
            root = self.drive.folder("root", ONLINE_ROOT)
        active, remote, root_files = self._read_online(root)
        if active is None and STAGING_MARKER not in root_files:
            # Durable evidence for safe first-run recovery. This marker is
            # published BEFORE the first media file, so an interrupted upload
            # cannot be mistaken for an unrelated old library.
            with tempfile.TemporaryDirectory(prefix="xstage-online-marker-") as temp:
                marker_file = Path(temp) / STAGING_MARKER
                marker_file.write_text(json.dumps({
                    "format": "xstage-songstudio-upload-staging-v1",
                    "schemaVersion": 1,
                    "note": "Private staged upload. No playable DB is published yet."
                }), encoding="utf-8")
                self.drive.upload_file(root, marker_file, STAGING_MARKER,
                                       cancelled=cancelled)
        pointer_file, old_pointer = active if active else (None, None)
        by_code = {}
        by_pair = {}
        for item in remote.values():
            by_code.setdefault(str(item.get("code") or "").casefold(), []).append(item)
            audio_hash = (item.get("audio") or {}).get("md5Checksum")
            lyric_hash = (item.get("lyrics") or {}).get("md5Checksum")
            if (isinstance(audio_hash, str) and len(audio_hash) == 32
                    and isinstance(lyric_hash, str) and len(lyric_hash) == 32):
                by_pair.setdefault((audio_hash.lower(), lyric_hash.lower()), item)
        # Compute duplicate evidence only for same-code candidates. Never skip
        # or overwrite on title match alone. Older clients may use an unrelated
        # OAuth app; in that case a metadata 403 must stop safely.
        revisions = []
        counts = {"newSongs": 0, "updatedSongs": 0, "duplicates": 0,
                  "conflicts": 0, "notReady": not_ready, "filesUploaded": 0}
        root_id = root
        folder_cache = {}
        file_lists = {}  # one files.list per parent, not per song
        metadata_cache = {}
        def matches_md5(media, expected):
            if not isinstance(media, dict) or not media.get("fileId"):
                return False
            ident = media["fileId"]
            checksum = media.get("md5Checksum")
            if not isinstance(checksum, str) or len(checksum) != 32:
                if ident not in metadata_cache:
                    metadata_cache[ident] = self._metadata(ident)["md5Checksum"]
                checksum = metadata_cache[ident]
            return checksum.lower() == expected
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
            parent = folder(tuple(path.parts[:-1]))
            if parent not in file_lists:
                # Build the folder index ONCE per parent, rather than a
                # linear search through every previous song on every upload.
                lookup = {}
                for item in self.drive.list_children(parent):
                    lookup.setdefault(item.get("name"), []).append(item)
                file_lists[parent] = lookup
            result, meta = self.drive.upload_file(
                parent, local_file, name, cancelled=cancelled,
                on_progress=on_progress, existing_items=file_lists[parent])
            if result == "created":
                counts["filesUploaded"] += 1
                file_lists[parent].setdefault(name, []).append(meta)
            return {"fileId": meta["id"], "path":
                    str(path.parent).replace("\\", "/") + "/" + name,
                    "md5Checksum": checksum,
                    "size": local_file.stat().st_size}
        counts["published"] = False
        counts["batches"] = 0
        def flush():
            nonlocal old_pointer, pointer_file
            if not revisions:
                return
            if cancelled and cancelled.is_set():
                raise PublishError(
                    "ยกเลิกก่อนเผยแพร่รอบปัจจุบัน · รอบก่อนหน้าที่เผยแพร่แล้วยังใช้งานได้")
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
                        "schemaVersion": 1, "upserts": list(revisions), "removes": []})
                    catalog_id = old_pointer["catalogFileId"]
                    delta_ids = [*old_pointer.get("deltaFileIds", []), delta_id]
                else:
                    # Compact immutable base only after 32 online deltas,
                    # never rewrite the main DB for every single song.
                    catalog_id = push_json("catalog-base-" + generation + ".json", {
                        "schemaVersion": 1, "songs": list(remote.values())})
                    delta_ids = []
                next_pointer = {
                    "schemaVersion": 1, "generation": generation,
                    "catalogFileId": catalog_id, "deltaFileIds": delta_ids,
                    "songCount": len(remote)
                }
                if pointer_file:
                    current = self._json(pointer_file["id"])
                    if current.get("generation") != old_pointer.get("generation"):
                        raise PublishError(
                            "ฐาน Drive มีผู้อื่นอัปเดตระหว่างซิงค์ · "
                            "หยุดก่อนเผยแพร่รอบใหม่เพื่อป้องกันข้อมูลสูญหาย")
                pointer_path = Path(temp) / "current.json"
                pointer_path.write_text(json.dumps(next_pointer, ensure_ascii=False,
                                                   separators=(",", ":")), encoding="utf-8")
                _, pointer_file = self.drive.upload_file(
                    ensure_root(), pointer_path, "current.json",
                    replace_pointer=True, cancelled=cancelled)
            old_pointer = next_pointer
            revisions.clear()
            counts["published"] = True
            counts["batches"] += 1
            counts["generation"] = generation
            counts["totalSongs"] = len(remote)
            if on_batch:
                on_batch(counts["batches"], len(remote),
                         counts["newSongs"], counts["updatedSongs"])
        for i, row in enumerate(ready, 1):
            # Report completed rows, not merely bytes in one current upload.
            # This also advances progress through verified duplicates.
            if on_row:
                on_row(i - 1, len(ready), not_ready)
            if cancelled and cancelled.is_set():
                raise PublishError("ยกเลิกซิงค์ Google Drive · ชุดเพลงที่เผยแพร่ก่อนหน้ายังคงใช้งานได้")
            code = str(row["code"]).casefold()
            sound = _local_path(local_songs, row["audio"]["path"], "audio")
            lyric = _local_path(local_songs, row["lyrics"]["path"], "lyrics")
            s_hash, l_hash = _md5(sound), _md5(lyric)
            # Exact M4A+Lyrics bytes are the same song even if the local
            # filename or catalog code was changed. Never infer equivalence
            # from title alone.
            pair = (s_hash, l_hash)
            if pair in by_pair:
                counts["duplicates"] += 1
                continue
            candidates = list(by_code.get(code, []))
            exact_id = remote.get(str(row["webSongId"]))
            if exact_id and str(exact_id.get("code") or "").casefold() != code:
                # A PC catalog can use a filename-derived webSongId that
                # already exists remotely for an entirely different track.
                # Never overwrite that remote song's identity or its code.
                if matches_md5(exact_id.get("audio"), s_hash):
                    counts["conflicts"] += 1
                    continue
            elif exact_id and exact_id not in candidates:
                candidates.append(exact_id)
            same_audio, same_both = None, None
            for candidate in candidates:
                if str(candidate.get("code") or "").casefold() != code:
                    continue
                a_id = (candidate.get("audio") or {}).get("fileId")
                l_id = (candidate.get("lyrics") or {}).get("fileId")
                if not a_id or not l_id:
                    continue
                if matches_md5(candidate.get("audio"), s_hash):
                    same_audio = candidate
                    if matches_md5(candidate.get("lyrics"), l_hash):
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
            lrc_media = None
            if (local_songs / lrc_path).is_file():
                lrc_media = upload(_local_path(local_songs, lrc_path, "lyrics"), lrc_path)
            vocals = None
            if row.get("vocals") and row["vocals"].get("path"):
                src = _local_path(local_songs, row["vocals"]["path"], "audio")
                vocals = upload(src, row["vocals"]["path"])
            ident = (str(same_audio["webSongId"]) if same_audio else str(row["webSongId"]))
            if not same_audio and ident in remote:
                # Keep the old Drive entry immutable. A new online ID is
                # derived from the assigned code and actual M4A checksum;
                # only the metadata identity changes, not the user's files.
                ident = ident + "-assigned-" + str(row["code"]) + "-" + s_hash[:16]
                if ident in remote:
                    counts["conflicts"] += 1
                    continue
            item = {"webSongId": ident, "code": str(row["code"]),
                    "title": str(row.get("title") or row["code"]),
                    "artist": str(row.get("artist") or ""),
                    "sourceFormat": str(row.get("sourceFormat") or ""),
                    "audio": audio, "lyrics": lyrics}
            if row.get("originalCode"):
                item["originalCode"] = str(row["originalCode"])
            if lrc_media:
                item["lrc"] = lrc_media
            if vocals:
                item["vocals"] = vocals
            elif same_audio and same_audio.get("vocals"):
                item["vocals"] = same_audio["vocals"]
            remote[ident] = item
            revisions.append(item)
            by_code.setdefault(code, []).append(item)
            by_pair[pair] = item
            counts["updatedSongs" if same_audio else "newSongs"] += 1
            if len(revisions) >= batch_size:
                flush()
        flush()
        if on_row:
            on_row(len(ready), len(ready), not_ready)
        counts["totalSongs"] = len(remote)
        return counts
