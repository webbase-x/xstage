"""Cloud-only legacy catalog migration: Google Drive REST + disk SQLite.

This CLI is a staging tool, not a publisher. It reads the canonical legacy
DB and authenticated Drive file metadata, never downloads the XMID library,
never writes to Drive. The resulting snapshot is validated before being
copied to a user-selected output path. OAuth token must already be available
in the local environment; do not paste credentials into chat or arguments.
"""
from __future__ import annotations
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import sqlite3
import tempfile
import urllib.parse
import urllib.request

FOLDER = "application/vnd.google-apps.folder"
SHORTCUT = "application/vnd.google-apps.shortcut"
RETIRED = "1RYekUHCC3qs661cUrbxkNauUz_SuqZvy"
FIELDS = "id,name,parents,mimeType,trashed,size,md5Checksum,version"
VALID_ID = re.compile(r"[A-Za-z0-9_-]{5,256}")


def _safe_id(value):
    if not isinstance(value,str) or not VALID_ID.fullmatch(value) or value==RETIRED:
        raise ValueError("รหัส Drive ไม่ถูกต้องหรือเป็นคลังที่เลิกใช้แล้ว")
    return value


def _safe_name(value):
    return isinstance(value,str) and value not in ("",".","..") and not any(x in value for x in "/\\:\x00")


def _verified_child(item, parent):
    if item.get("trashed") or item.get("parents") != [parent]:
        raise ValueError("ไฟล์ Drive อยู่นอกโฟลเดอร์ที่เลือก")
    _safe_id(item.get("id"))
    if not _safe_name(item.get("name")):
        raise ValueError("ชื่อไฟล์ Drive ไม่สามารถใช้เป็นพาธร่วม")


def _media_fingerprint(item):
    digest=str(item.get("md5Checksum","")).lower()
    try:
        size=int(item["size"])
    except (KeyError,ValueError,TypeError):
        raise ValueError("Drive ไม่ส่งขนาดไฟล์เพลง")
    if not re.fullmatch(r"[0-9a-f]{32}",digest) or not 0<size<=2**53-1:
        raise ValueError("Drive ไม่ส่ง MD5/ขนาดที่ตรวจสอบได้")
    return digest,size


def index_songs(drive, songs_id):
    """Walk exact children with paginated Drive listings; no content reads."""
    from .shared_catalog_builder import MAX_PACKAGES
    _safe_id(songs_id)
    stack=[(songs_id,"")]
    seen_folders=set()
    index={}
    seen_paths=set()
    while stack:
        parent,prefix=stack.pop()
        if parent in seen_folders:
            raise ValueError("พบโฟลเดอร์อ้างอิงซ้ำ")
        seen_folders.add(parent)
        for item in drive.children(parent):
            _verified_child(item,parent)
            relative=prefix+item["name"]
            key=relative.casefold()
            if key in seen_paths:
                raise ValueError("พบชื่อไฟล์หรือโฟลเดอร์ Cloud ซ้ำ: "+relative)
            seen_paths.add(key)
            if item["mimeType"]==FOLDER:
                stack.append((item["id"],relative+"/"))
            elif item["mimeType"]!=SHORTCUT and Path(relative).suffix.lower() in (".xmid",".xsk"):
                _media_fingerprint(item)
                index[key]=(relative,item)
                if len(index)>MAX_PACKAGES:
                    raise ValueError("จำนวนไฟล์เพลงเกินขีดจำกัด")
    return index


def resolve_legacy(raw,index):
    path=PureWindowsPath(str(raw))
    parts=list(path.parts)[1:] if path.anchor else list(path.parts)
    if not parts or not all(_safe_name(x) for x in parts):
        raise ValueError("พาธเดิมไม่ปลอดภัย: "+str(raw))
    suffixes=[parts[i:] for i in range(len(parts))]
    keys={"/".join(p).casefold() for p in suffixes}
    keys.update(("MIDI/"+"/".join(p)).casefold() for p in suffixes if len(p)>=2)
    hits={index[k][0]:index[k] for k in keys if k in index}
    if len(hits)!=1:
        raise ValueError(("ไม่พบไฟล์เพลงบน Cloud: " if not hits else "พาธ Cloud กำกวม: ")+str(raw))
    return next(iter(hits.values()))


def cloud_record(relative,item,old):
    digest,size=_media_fingerprint(item)
    kind=Path(relative).suffix.lower()[1:]
    if kind not in ("xmid","xsk"):
        raise ValueError("ชนิดแพ็กเกจไม่รองรับ")
    return {"webSongId":"browser/"+kind+"/"+digest,
            "sourceFormat":kind.upper(),"code":str(old["code"]),
            "sourceCode":str(old["code"]),"title":str(old["title"] or ""),
            "artist":str(old["artist"] or ""),
            "originalFilename":relative.rsplit("/",1)[-1],
            "originalRelativePath":relative,"originalFileSize":size,
            "midiSize":None,"lyricsMode":"unavailable",
            "firstLyric":str(old.get("first_lyric") or ""),
            "rhythm":str(old.get("rhythm") or ""),
            "keySignature":str(old.get("key_signature") or ""),
            "bpm":str(old.get("bpm") or ""),
            "cloudPackageVerification":"drive-metadata-only",
            kind:{"fileId":_safe_id(item["id"]),"path":"SONGS/"+relative,
                  "md5Checksum":digest,"size":size}}


class Drive:
    def __init__(self,token):
        if not token or "\n" in token or "\r" in token:
            raise ValueError("ต้องมี Google OAuth token ในสภาพแวดล้อมของโปรแกรม")
        self.token=token

    def request(self,route,**params):
        url="https://www.googleapis.com/drive/v3/"+route+"?"+urllib.parse.urlencode(params)
        req=urllib.request.Request(url,headers={"Authorization":"Bearer "+self.token,"Accept-Encoding":"identity"})
        return urllib.request.urlopen(req,timeout=60)

    def metadata(self,ident):
        with self.request("files/"+_safe_id(ident),fields=FIELDS,supportsAllDrives="true") as response:
            return json.load(response)

    def children(self,parent):
        _safe_id(parent)
        page=None
        seen=set()
        while True:
            params={"q":f"'{parent}' in parents and trashed=false","pageSize":1000,
                    "fields":f"nextPageToken,incompleteSearch,files({FIELDS})",
                    "supportsAllDrives":"true","includeItemsFromAllDrives":"true"}
            if page:params["pageToken"]=page
            with self.request("files",**params) as response:
                result=json.load(response)
            if result.get("incompleteSearch"):
                raise ValueError("Google Drive ส่งผลค้นหาไม่ครบ")
            yield from result.get("files",[])
            page=result.get("nextPageToken")
            if not page:return
            if page in seen:raise ValueError("Drive pagination loop")
            seen.add(page)

    def download_db(self,meta,destination):
        digest,size=_media_fingerprint(meta)
        checksum=hashlib.md5(usedforsecurity=False)
        count=0
        with self.request("files/"+_safe_id(meta["id"]),alt="media",supportsAllDrives="true") as response, \
             destination.open("xb") as out:
            while True:
                chunk=response.read(1024*1024)
                if not chunk:break
                count+=len(chunk)
                if count>size:raise ValueError("ขนาดฐาน Cloud เปลี่ยน")
                checksum.update(chunk);out.write(chunk)
            out.flush();os.fsync(out.fileno())
        if count!=size or checksum.hexdigest()!=digest:
            raise ValueError("MD5 หรือขนาดฐานไม่ตรง Cloud")


def _unique_child(drive,parent,name,folder):
    matches=[x for x in drive.children(parent) if x.get("name")==name]
    if len(matches)!=1:
        raise ValueError("ต้องพบ "+name+" เพียงรายการเดียว")
    item=matches[0];_verified_child(item,parent)
    if (item["mimeType"]==FOLDER)!=folder or item["mimeType"]==SHORTCUT:
        raise ValueError("ชนิดไฟล์ Drive ไม่ตรง: "+name)
    return item


def stage_cloud(drive,root_id,output,progress=None):
    from .legacy_catalog_migration import migrate
    from .local_master import snapshot
    _safe_id(root_id)
    root=drive.metadata(root_id)
    if root.get("id")!=root_id or root.get("trashed") or root.get("mimeType")!=FOLDER:
        raise ValueError("คลัง Google Drive ไม่ถูกต้อง")
    songs=_unique_child(drive,root_id,"SONGS",True)
    db=_unique_child(drive,root_id,"DB",True)
    source=_unique_child(drive,db["id"],"songs.sqlite3",False)
    _media_fingerprint(source)
    output=Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError("เลือกชื่อไฟล์ผลลัพธ์ใหม่ · ไม่เขียนทับฐานใด")
    with tempfile.TemporaryDirectory(prefix="xstage-cloud-migrate-") as tmp:
        home=Path(tmp)
        legacy=home/"legacy.sqlite3"
        drive.download_db(source,legacy)
        index=index_songs(drive,songs["id"])
        result=migrate(legacy,None,home,cloud_index=index,progress=progress)
        # Re-list before producing the candidate: detect changed paths, IDs,
        # package sizes and checksums rather than blindly trusting an old scan.
        latest=_unique_child(drive,db["id"],"songs.sqlite3",False)
        if (latest["id"],_media_fingerprint(latest),latest.get("version"))!=(source["id"],_media_fingerprint(source),source.get("version")):
            raise ValueError("ฐาน Cloud เปลี่ยนระหว่างย้าย")
        fresh=index_songs(drive,songs["id"])
        def signature(value):
            return {k:(rel,m["id"],_media_fingerprint(m)) for k,(rel,m) in value.items()}
        if signature(fresh)!=signature(index):
            raise ValueError("คลังเพลง Cloud เปลี่ยนระหว่างย้าย · ไม่สร้างผลลัพธ์")
        if output.exists() or output.is_symlink():
            raise FileExistsError("พบไฟล์ปลายทางใหม่ · ไม่เขียนทับ")
        # Exclusive output creation; a competing process cannot be overwritten.
        with Path(result["database"]).open("rb") as src, output.open("xb") as dest:
            try:
                while True:
                    block=src.read(1024*1024)
                    if not block:break
                    dest.write(block)
                dest.flush();os.fsync(dest.fileno())
            except BaseException:
                dest.close();output.unlink(missing_ok=True);raise
        result.update(database=str(output),source_file_id=source["id"],
                      source_md5=_media_fingerprint(source)[0],
                      source_version=source.get("version"),cloud_written=False)
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root-id",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    result=stage_cloud(Drive(os.environ.get("XSTAGE_DRIVE_ACCESS_TOKEN","")),
                       args.root_id,args.output,
                       progress=lambda info,msg:print(msg,info["scanned"],"/",info["total"],flush=True))
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    main()
