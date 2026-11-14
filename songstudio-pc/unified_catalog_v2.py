"""X-Stage Unified Song Catalog v2 contract (standard library, no network).

Same semantic song fields for PC SQLite exports, Song Studio and private Drive.
A locator may be localPath (offline PC) OR fileId (private Drive). Converting a
local record to a cloud record requires explicit upload; paths never become URLs.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath

SCHEMA_VERSION = 2
CATALOG_FORMAT = "xstage-unified-v2"
MAX_SONGS = 1_000_000
MEDIA_KEYS = frozenset(("mp3", "m4a", "midi", "video"))
VIDEO_TYPES = frozenset(("avi", "mpg", "vcd", "wmv", "mp4"))
MIDI_TYPES = frozenset(("ncn", "emk"))
SAFE_ID = re.compile(r"^[^\x00-\x1f/\\?#]{1,256}$")
SONG_ID = re.compile(r"^[^\x00-\x1f?#]{1,256}$")  # V1 IDs can contain audio/0/00001
DIGEST = re.compile(r"^[0-9a-fA-F]{64}$")
MD5 = re.compile(r"^[0-9a-fA-F]{32}$")


class CatalogValidationError(ValueError):
    """An invalid catalog must never replace the current active pointer."""


def _string(value, field, *, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()) or len(value) > 1024:
        raise CatalogValidationError(field + " must be a non-empty string")
    if any(ord(x) < 32 for x in value):
        raise CatalogValidationError(field + " contains control characters")
    return value


def _logical_path(value):
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise CatalogValidationError("Invalid media path")
    if "\\" in value or ":" in value or value.startswith("/"):
        raise CatalogValidationError("Unsafe media path")
    if any(p in ("", ".", "..") for p in value.split("/")):
        raise CatalogValidationError("Unsafe media path")
    path = PurePosixPath(value)
    if str(path) != value:
        raise CatalogValidationError("Non-canonical media path")
    return value


def validate_locator(value, *, cloud=False, label="media"):
    if not isinstance(value, dict):
        raise CatalogValidationError(label + " must be an object")
    file_id = value.get("fileId")
    local_path = value.get("localPath")
    if cloud:
        if local_path is not None:
            raise CatalogValidationError("Local file paths must never be published to Google Drive")
        if not isinstance(file_id, str) or not SAFE_ID.fullmatch(file_id):
            raise CatalogValidationError(label + ".fileId missing or unsafe")
    elif bool(file_id) == bool(local_path):
        raise CatalogValidationError(label + " requires exactly one of fileId or localPath")
    if file_id is not None and (not isinstance(file_id, str) or not SAFE_ID.fullmatch(file_id)):
        raise CatalogValidationError(label + ".fileId unsafe")
    if local_path is not None:
        _string(local_path, label + ".localPath")
        if not (re.match(r"^[A-Za-z]:[\\/]", local_path) or local_path.startswith("/")):
            raise CatalogValidationError(label + ".localPath must be absolute")
    if "path" in value:
        _logical_path(value["path"])
    if "size" in value and (type(value["size"]) is not int or value["size"] < 0):
        raise CatalogValidationError(label + ".size invalid")
    if "sha256" in value and (not isinstance(value["sha256"], str) or not DIGEST.fullmatch(value["sha256"])):
        raise CatalogValidationError(label + ".sha256 invalid")
    if "md5Checksum" in value and (not isinstance(value["md5Checksum"], str) or not MD5.fullmatch(value["md5Checksum"])):
        raise CatalogValidationError(label + ".md5Checksum invalid")
    return value


def validate_song(item, *, cloud=False):
    if not isinstance(item, dict):
        raise CatalogValidationError("Song must be an object")
    song_id = item.get("id")
    if not isinstance(song_id, str) or not SONG_ID.fullmatch(song_id):
        raise CatalogValidationError("Song id missing or invalid")
    if item.get("webSongId", song_id) != song_id:
        raise CatalogValidationError("id and webSongId must match")
    code = _string(item.get("code"), "code")
    if not SAFE_ID.fullmatch(code) or len(code) > 64:
        raise CatalogValidationError("Invalid song code")
    _string(item.get("title"), "title")
    _string(item.get("artist", ""), "artist", empty=True)
    media = item.get("media")
    if not isinstance(media, dict) or not media or any(k not in MEDIA_KEYS for k in media):
        raise CatalogValidationError("Song needs at least one supported media type")
    for kind, locator in media.items():
        validate_locator(locator, cloud=cloud, label=kind)
        if kind == "midi":
            if locator.get("type") not in MIDI_TYPES:
                raise CatalogValidationError("MIDI type must be ncn or emk")
            if locator["type"] == "ncn":
                for companion in ("lyr", "cur"):
                    validate_locator(locator.get(companion), cloud=cloud, label="midi." + companion)
        if kind == "video" and locator.get("type") not in VIDEO_TYPES:
            raise CatalogValidationError("Unsupported video container")
    if item.get("lyrics") is not None:
        validate_locator(item["lyrics"], cloud=cloud, label="lyrics")
    return item


def validate_catalog(doc, *, cloud=False, expected_count=None):
    if not isinstance(doc, dict) or doc.get("schemaVersion") != SCHEMA_VERSION:
        raise CatalogValidationError("Catalog schemaVersion must be 2")
    if "format" in doc and doc["format"] != CATALOG_FORMAT:
        raise CatalogValidationError("Unknown catalog format")
    songs = doc.get("songs")
    if not isinstance(songs, list) or len(songs) > MAX_SONGS:
        raise CatalogValidationError("Invalid number of songs")
    if expected_count is not None and len(songs) != expected_count:
        raise CatalogValidationError("Catalog does not match current.json songCount")
    ids = set()
    for song in songs:
        validate_song(song, cloud=cloud)
        if song["id"] in ids:
            raise CatalogValidationError("Duplicate stable song ID: " + song["id"])
        ids.add(song["id"])
    return doc


def validate_pointer(pointer):
    if not isinstance(pointer, dict) or pointer.get("schemaVersion") != SCHEMA_VERSION:
        raise CatalogValidationError("Invalid V2 pointer schema")
    if "format" in pointer and pointer["format"] != CATALOG_FORMAT:
        raise CatalogValidationError("Unknown pointer format")
    generation = pointer.get("generation")
    if not isinstance(generation, str) or not SAFE_ID.fullmatch(generation):
        raise CatalogValidationError("Invalid catalog generation")
    if not isinstance(pointer.get("catalogFileId"), str) or not SAFE_ID.fullmatch(pointer["catalogFileId"]):
        raise CatalogValidationError("Missing Drive catalog file ID")
    count = pointer.get("songCount")
    if type(count) is not int or not 0 <= count <= MAX_SONGS:
        raise CatalogValidationError("Invalid songCount")
    return pointer


def migrate_v1_song(row):
    """Convert a published V1 Drive song record WITHOUT mutating files/pointer."""
    if not isinstance(row, dict):
        raise CatalogValidationError("Invalid V1 song")
    sid = row.get("webSongId") or row.get("id")
    if not isinstance(sid, str) or not SONG_ID.fullmatch(sid):
        raise CatalogValidationError("V1 missing stable song ID")
    audio = row.get("audio")
    if not isinstance(audio, dict) or not audio.get("fileId"):
        raise CatalogValidationError("V1 missing audio Drive reference")
    path = str(audio.get("path") or "")
    suffix = PurePosixPath(path).suffix.lower()
    if suffix not in (".m4a", ".mp3"):
        raise CatalogValidationError("V1 audio extension cannot be inferred safely")
    key = suffix[1:]
    out = {
        "id":sid, "webSongId":sid,
        "code":str(row.get("code") or sid),
        "title":str(row.get("title") or row.get("code") or sid),
        "artist":str(row.get("artist") or ""),
        "media":{key:{k:v for k,v in audio.items() if k in ("fileId","path","size","md5Checksum","sha256")}},
        "lyrics":{k:v for k,v in row["lyrics"].items() if k in ("fileId","path","size","md5Checksum","sha256")}
            if isinstance(row.get("lyrics"),dict) and row["lyrics"].get("fileId") else None
    }
    validate_song(out,cloud=True)
    return out


def migrate_v1_catalog(songs):
    if not isinstance(songs,list) or len(songs)>MAX_SONGS:
        raise CatalogValidationError("V1 song list invalid")
    result={"schemaVersion":SCHEMA_VERSION,"format":CATALOG_FORMAT,
            "songs":[migrate_v1_song(row) for row in songs]}
    return validate_catalog(result,cloud=True)


def export_local_song(song):
    """Create v2 media locators from a row in the PC's existing SQLite DB."""
    if not isinstance(song, dict):
        raise CatalogValidationError("Invalid SQLite song row")
    ext = str(song.get("format") or song.get("kind") or "").lower().lstrip(".")
    path = str(song.get("path") or "")
    if ext in ("mid","midi","kar","emk","ncn"):
        kind, subtype="midi",("ncn" if ext=="ncn" else "emk")
    elif ext in ("avi","mpg","mpeg","dat","wmv","mp4"):
        kind, subtype="video",{"mpeg":"mpg","dat":"vcd"}.get(ext,ext)
    elif ext in ("mp3","m4a"):
        kind, subtype=ext,None
    else:
        raise CatalogValidationError("PC format cannot be exported as V2: " + ext)
    ref={"localPath":path}
    if subtype:ref["type"]=subtype
    if kind=="midi" and subtype=="ncn":
        raise CatalogValidationError("NCN requires verified LYR/CUR companion paths")
    ident=str(song.get("id"))
    out={"id":ident,"webSongId":ident,"code":str(song.get("code") or ident),
         "title":str(song.get("title") or song.get("code") or ident),
         "artist":str(song.get("artist") or ""),"media":{kind:ref},"lyrics":None}
    validate_song(out,cloud=False)
    return out
