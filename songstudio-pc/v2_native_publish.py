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
from unified_catalog_v2 import (CATALOG_FORMAT, CatalogValidationError,
    validate_catalog, validate_pointer, validate_song, migrate_v1_catalog)

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



SHARD_SONGS = 2500
MAX_V2_DELTAS = 32
MAX_V2_DELTA_UPSERTS = 200


def read_published_v2(reader, pointer):
    """Verify immutable base shards and deltas before exposing any new songs."""
    validate_pointer(pointer)
    records={}
    parts=(pointer["catalogFiles"] if "catalogFiles" in pointer else
           [{"fileId":pointer["catalogFileId"],"songCount":None}])
    for part in parts:
        doc=reader(part["fileId"])
        validate_catalog(doc,cloud=True,expected_count=part["songCount"])
        for song in doc["songs"]:
            if song["id"] in records:
                raise CatalogValidationError("Duplicate song ID across V2 shards")
            records[song["id"]]=song
    for delta_id in pointer.get("deltaFileIds",[]):
        delta=reader(delta_id)
        if (not isinstance(delta,dict) or delta.get("schemaVersion")!=2
                or delta.get("format",CATALOG_FORMAT)!=CATALOG_FORMAT
                or not isinstance(delta.get("upserts"),list)
                or not isinstance(delta.get("removes"),list)
                or len(delta["upserts"])>MAX_SONGS):
            raise CatalogValidationError("Corrupt immutable V2 delta")
        for song_id in delta["removes"]:
            if not isinstance(song_id,str):
                raise CatalogValidationError("Invalid removed song ID")
            records.pop(song_id,None)
        for song in delta["upserts"]:
            validate_song(song,cloud=True)
            records[song["id"]]=song
    validate_catalog({"schemaVersion":2,"format":CATALOG_FORMAT,
                      "songs":list(records.values())},cloud=True,
                      expected_count=pointer["songCount"])
    return records


def write_published_v2(drive,db,records,*,previous=None,revisions=None,
                       cancelled=None,precommit=None):
    """Publish immutable data first; update DB/current.json only after success.

    Small incremental batches append one verified delta; 32 deltas trigger
    compaction. Large libraries are bucketed into immutable <=2500-song shards.
    """
    generation=secrets.token_hex(12)
    with tempfile.TemporaryDirectory(prefix="xstage-v2-catalog-") as tmp:
        temp=Path(tmp)
        def upload(folder, name, data):
            if cancelled is not None and cancelled.is_set():
                raise PublishError("ยกเลิกก่อนเผยแพร่ฐาน V2")
            file=temp/name
            file.write_text(json.dumps(data,ensure_ascii=False,
                        separators=(",",":")),encoding="utf-8")
            _,meta=drive.upload_file(folder,file,name,
                replace_pointer=(name=="current.json"),cancelled=cancelled)
            if not isinstance(meta.get("id"),str) or not meta["id"]:
                raise PublishError("Google Drive ไม่คืนรหัสไฟล์ฐานข้อมูล")
            return meta["id"]
        update_mode=(previous is not None and revisions and
                     len(revisions)<=MAX_V2_DELTA_UPSERTS and
                     len(previous.get("deltaFileIds",[]))<MAX_V2_DELTAS)
        pointer={"schemaVersion":2,"format":CATALOG_FORMAT,
                 "generation":generation,"songCount":len(records)}
        if update_mode:
            delta_folder=drive.folder(db,"deltas")
            delta_id=upload(delta_folder,"catalog-delta-v2-"+generation+".json",
                            {"schemaVersion":2,"format":CATALOG_FORMAT,
                             "upserts":list(revisions),"removes":[]})
            for name in ("catalogFileId","catalogFiles"):
                if name in previous:pointer[name]=previous[name]
            pointer["deltaFileIds"]=[*previous.get("deltaFileIds",[]),delta_id]
        elif len(records)<=SHARD_SONGS:
            pointer["catalogFileId"]=upload(db,"catalog-base-v2-"+generation+".json",
                        {"schemaVersion":2,"format":CATALOG_FORMAT,
                         "songs":list(records.values())})
        else:
            catalog_folder=drive.folder(db,"catalogs")
            buckets={}
            for song in records.values():
                first=song["code"][0].upper()
                bucket=first if first in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ" else "_"
                buckets.setdefault(bucket,[]).append(song)
            shards=[]
            for bucket,items in sorted(buckets.items()):
                items.sort(key=lambda song:song["id"])
                for offset in range(0,len(items),SHARD_SONGS):
                    part=items[offset:offset+SHARD_SONGS]
                    name="catalog-v2-"+bucket+"-"+str(offset//SHARD_SONGS)+"-"+generation+".json"
                    file_id=upload(catalog_folder,name,{
                        "schemaVersion":2,"format":CATALOG_FORMAT,"songs":part})
                    shards.append({"bucket":bucket,"fileId":file_id,"songCount":len(part)})
            if len(shards)>1024:
                raise PublishError("ฐานเพลงมีจำนวน Shards เกินขีดจำกัด")
            pointer["catalogFiles"]=shards
        validate_pointer(pointer)
        if precommit is not None:
            precommit()
        upload(db,"current.json",pointer)
    return pointer

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
        for song in songs:
            kinds=set(song["media"])
            if len(kinds.intersection({"avi","mpg","vcd","wmv"}))>1:
                raise PublishError("เพลงหนึ่งรายการต้องระบุ VIDEO หลักได้เพียงประเภทเดียว")
            if "ncn" in kinds and "emk" in kinds:
                raise PublishError("เพลงหนึ่งรายการต้องระบุ MIDI ต้นฉบับหลักเพียงชนิดเดียว")
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
            try:
                validate_pointer(previous)
                catalog = self.reader._json(previous["catalogFileId"])
                validate_catalog(catalog, cloud=True, expected_count=previous["songCount"])
            except (CatalogValidationError, KeyError, TypeError) as exc:
                raise PublishError("ฐาน V2 เดิมไม่สมบูรณ์ · หยุดก่อนเขียนทับ") from exc
            existing = {s["id"]: s for s in catalog["songs"]}
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
        # Preflight conflicts BEFORE uploading bytes. Linear-time lookups
        # support libraries containing hundreds of thousands of songs.
        code_owners={}
        for ident,row in existing.items():
            code=row["code"].casefold()
            if code in code_owners and code_owners[code]!=ident:
                raise PublishError("รหัสเพลงซ้ำในฐาน V2 เดิม: "+row["code"])
            code_owners[code]=ident
        for item in songs:
            code=item["code"].casefold()
            prior_id=code_owners.get(code)
            if prior_id is not None and prior_id!=item["id"]:
                raise PublishError("รหัสเพลงชนกับฐานเดิม: "+item["code"])
            prior=existing.get(item["id"])
            if prior and prior["code"].casefold()!=code:
                raise PublishError("ID เพลงเดิมมีรหัสไม่ตรงกัน: "+item["id"])
            code_owners[code]=item["id"]
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
            lyric_format = "MP3" if "mp3" in item["media"] and "m4a" not in item["media"] else "M4A"
            lyrics = upload(item["lyrics"], lyric_format, "lyrics", item["code"]) if item["lyrics"] else None
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
                                              "cursor":trio["cursor"],"code":item["code"]})
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
            published = {
                "id": item["id"], "webSongId": item["id"], "code": item["code"],
                "title": item["title"], "artist": item["artist"],
                "media": media, "lyrics": lyrics
            }
            # Updating one format must not drop other previously published
            # formats (e.g. native MP3 added after M4A conversion).
            existing_record = result.get(item["id"])
            if existing_record:
                published["media"]={**existing_record["media"],**media}
                if lyrics is None:
                    published["lyrics"]=existing_record.get("lyrics")
            result[item["id"]] = published
            if on_progress: on_progress(index, len(songs))
        # All files may have uploaded; still NEVER publish an invalid catalog.
        try:
            validate_catalog({"schemaVersion":2,"format":CATALOG_FORMAT,
                              "songs":list(result.values())}, cloud=True)
        except CatalogValidationError as exc:
            raise PublishError("ตรวจฐาน V2 ก่อนเผยแพร่ไม่ผ่าน: "+str(exc)) from exc
        if current:
            fresh = self.reader._json(current[0]["id"])
            if fresh.get("generation") != previous.get("generation"):
                raise PublishError("ฐาน V2 ถูกอัปเดตระหว่างอัปโหลด")
        generation = secrets.token_hex(12)
        with tempfile.TemporaryDirectory(prefix="xstage-db-v2-") as temp:
            target = Path(temp)
            catalog_file = target / "catalog.json"
            catalog_file.write_text(json.dumps({"schemaVersion":2,"format":CATALOG_FORMAT,"songs":list(result.values())},
                                               ensure_ascii=False,separators=(",",":")),encoding="utf-8")
            _, catalog_meta = self.drive.upload_file(db,catalog_file,
                                     "catalog-base-v2-"+generation+".json",cancelled=cancelled)
            pointer_file = target / "current.json"
            pointer_file.write_text(json.dumps({"schemaVersion":2,"format":CATALOG_FORMAT,"generation":generation,
                                "catalogFileId":catalog_meta["id"],
                                "songCount":len(result)},separators=(",",":")),encoding="utf-8")
            self.drive.upload_file(db,pointer_file,"current.json",replace_pointer=True,cancelled=cancelled)
        return {"generation":generation,"newSongs":len(songs),"totalSongs":len(result)}

    def migrate_legacy_v1(self, *, dry_run=True, confirm=False, cancelled=None):
        """Convert private Drive V1 metadata to V2 without reuploading media.

        Dry run is the default and makes ZERO changes to Drive. A commit
        creates an immutable V2 catalog, then publishes DB/current.json.
        The original XStageWeb/current.json and media are NEVER deleted.
        """
        folders=[x for x in self.drive.list_children("root")
                 if x.get("name")=="XStageWeb" and
                 x.get("mimeType")=="application/vnd.google-apps.folder"]
        if len(folders)!=1:
            raise PublishError("ต้องพบคลัง XStageWeb เดียวที่เข้าถึงได้")
        root=folders[0]["id"]
        active, legacy, _ = self.reader._read_online(root)
        if not active:
            raise PublishError("ไม่พบ XStageWeb/current.json Schema V1")
        v1file, v1pointer = active
        try:
            migrated=migrate_v1_catalog(list(legacy.values()))
        except CatalogValidationError as exc:
            raise PublishError("แปลงฐาน V1 ไม่สำเร็จ · คงฐานเดิมไว้") from exc
        candidate={song["id"]:song for song in migrated["songs"]}
        existing_dbs=[x for x in self.drive.list_children(root)
                      if x.get("name")=="DB" and
                      x.get("mimeType")=="application/vnd.google-apps.folder"]
        if len(existing_dbs)>1:
            raise PublishError("พบ XStageWeb/DB ซ้ำ")
        db=existing_dbs[0]["id"] if existing_dbs else None
        old_ptr_file,old_ptr=None,None
        if db:
            pointers=[x for x in self.drive.list_children(db)
                      if x.get("name")=="current.json" and
                      x.get("mimeType")!="application/vnd.google-apps.folder"]
            if len(pointers)>1:
                raise PublishError("พบ DB/current.json ซ้ำ")
            if pointers:
                old_ptr_file=pointers[0]
                try:
                    old_ptr=validate_pointer(self.reader._json(old_ptr_file["id"]))
                    old_catalog=validate_catalog(
                        self.reader._json(old_ptr["catalogFileId"]),
                        cloud=True, expected_count=old_ptr["songCount"])
                except (CatalogValidationError,KeyError,TypeError) as exc:
                    raise PublishError("ฐาน V2 เดิมไม่สมบูรณ์ · ไม่เขียนทับ") from exc
                # Existing V2 records always win: migration can only fill
                # records absent from V2; it cannot downgrade a native track.
                candidate.update({song["id"]:song for song in old_catalog["songs"]})
        validate_catalog({"schemaVersion":2,"format":CATALOG_FORMAT,
                          "songs":list(candidate.values())},cloud=True)
        report={"schemaVersion":2,"dryRun":bool(dry_run),
                "v1Songs":len(legacy),"v2Songs":len(candidate),
                "preservedNative":old_ptr["songCount"] if old_ptr else 0,
                "sourceGeneration":v1pointer["generation"]}
        if dry_run:
            return report
        if not confirm:
            raise PublishError("การย้ายฐานต้องยืนยัน confirm=True; ค่าเริ่มต้นเป็น Dry Run")
        if cancelled is not None and cancelled.is_set():
            raise PublishError("ยกเลิกก่อนย้ายฐาน")
        current_v1=self.reader._json(v1file["id"])
        if current_v1.get("generation")!=v1pointer["generation"]:
            raise PublishError("ฐาน V1 ถูกอัปเดตระหว่างตรวจ · กรุณาลองใหม่")
        if db and old_ptr_file:
            current_v2=self.reader._json(old_ptr_file["id"])
            if current_v2.get("generation")!=old_ptr["generation"]:
                raise PublishError("ฐาน V2 ถูกอัปเดตระหว่างตรวจ · กรุณาลองใหม่")
        if not db:
            db=self.drive.folder(root,"DB")
        generation=secrets.token_hex(12)
        with tempfile.TemporaryDirectory(prefix="xstage-v1-to-v2-") as tmp:
            catalog_file=Path(tmp)/"catalog.json"
            catalog_file.write_text(json.dumps({
                "schemaVersion":2,"format":CATALOG_FORMAT,
                "songs":list(candidate.values())
            },ensure_ascii=False,separators=(",",":")),encoding="utf-8")
            _,metadata=self.drive.upload_file(db,catalog_file,
               "catalog-base-v2-migration-"+generation+".json",cancelled=cancelled)
            if cancelled is not None and cancelled.is_set():
                raise PublishError("ยกเลิกก่อนเปลี่ยนตัวชี้ฐาน")
            pointer=Path(tmp)/"current.json"
            pointer.write_text(json.dumps({
                "schemaVersion":2,"format":CATALOG_FORMAT,
                "generation":generation,"catalogFileId":metadata["id"],
                "songCount":len(candidate)
            },ensure_ascii=False,separators=(",",":")),encoding="utf-8")
            validate_pointer(json.loads(pointer.read_text(encoding="utf-8")))
            # Final pointer is the only mutable DB V2 file. Any failure above
            # leaves the previous active pointer readable.
            self.drive.upload_file(db,pointer,"current.json",
                                   replace_pointer=True,cancelled=cancelled)
        return {**report,"dryRun":False,"generation":generation}
