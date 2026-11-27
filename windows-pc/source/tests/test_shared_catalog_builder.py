"""Real PC builder regression: same SQLite as Online, no Studio DB writes."""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import struct
import tempfile
import threading
import unittest
from contextlib import closing
import zipfile
from pathlib import Path

from karaoke.shared_catalog_builder import build
from karaoke.shared_song_library import SharedSongLibrary


def _text(value):
    data=str(value).encode("utf-8")
    return struct.pack("<I",len(data))+data


def _xmid(code,title,artist,midi):
    metadata=b"".join(_text(value) for value in
        ("studio-id",code,"v1",title,artist,"timed"))+struct.pack("<I",0)
    header=struct.pack("<8sIQQ32s32s",b"XSTGPLS1",1,len(metadata),len(midi),
        hashlib.sha256(midi).digest(),hashlib.sha256(metadata).digest())
    return header+metadata+midi


def _xsk(code,title,artist,midi):
    document={
        "format":"XSK","formatVersion":2,"schemaVersion":2,
        "songCode":code,"title":title,"artist":artist,
        "audio":{"file":"song.mid","size":len(midi),
                 "sha256":hashlib.sha256(midi).hexdigest()},
        "lines":[{"startTime":0,"endTime":1,"text":"ทดสอบ",
                  "characters":[{"startTime":0,"text":"ทดสอบ"}]}
                 ]
    }
    content=io.BytesIO()
    with zipfile.ZipFile(content,mode="w",compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("song.mid",midi)
        z.writestr("lyrics.json",json.dumps(document,ensure_ascii=False))
    return b"XSK2"+content.getvalue()


class SharedPcBuilderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/"XStageKaraoke"
        for name in ("SONGS/MIDI/XMID/1","DB","SOUNDFONT","FX"):
            (self.root/name).mkdir(parents=True,exist_ok=True)
        self.midi=(b"MThd"+b"\x00\x00\x00\x06"+b"\x00\x00\x00\x01\x00\x60"+
                   b"MTrk"+b"\x00\x00\x00\x04\x00\xff\x2f\x00")
        self.songs=self.root/"SONGS/MIDI/XMID/1"
        (self.songs/"10001.xmid").write_bytes(
            _xmid("10001","เพลงทดสอบ","ศิลปิน",self.midi))

    def test_metadata_and_identity_match_portable_schema(self):
        from karaoke.shared_catalog_builder import _pc_id
        # 100 BPM, G major, end of track.
        events = bytes.fromhex("00 ff 51 03 09 27 c0 00 ff 59 02 01 00 00 ff 2f 00")
        midi = self.midi[:14] + b"MTrk" + struct.pack(">I", len(events)) + events
        packed = _xsk("10003", "เพลงทดสอบข้อมูล", "ศิลปิน", midi)
        # XSK provides its lyric in JSON; metadata extraction is independent of dedup.
        (self.songs / "10001.xmid").unlink()
        path = self.songs / "10003.xsk"
        path.write_bytes(packed)
        cache = Path(self.tmp.name) / "cache"
        build(self.root, cache_dir=cache, deduplicate=False)
        expected = "browser/xsk/" + hashlib.md5(packed).hexdigest()
        with closing(sqlite3.connect(self.root / "DB/songs.sqlite3")) as db:
            row = db.execute("SELECT id,web_song_id,first_lyric,key_signature,bpm,search,payload FROM songs").fetchone()
            self.assertEqual(row[:4], (_pc_id(expected), expected, "ทดสอบ", "G"))
            self.assertAlmostEqual(float(row[4]), 100)
            self.assertIn("ทดสอบ", row[5])
            payload = json.loads(row[6])
            self.assertEqual(payload["firstLyric"], row[2])
            self.assertEqual(payload["keySignature"], row[3])
            self.assertEqual(payload["bpm"], row[4])
            self.assertNotIn("blob", payload)
        build(self.root, cache_dir=cache, deduplicate=True)
        with closing(sqlite3.connect(self.root / "DB/songs.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT web_song_id FROM songs").fetchone()[0], expected)
        self.assertTrue(list((self.root / "BACKUP").glob("*.sqlite3.bak")))
        self.assertFalse(list((self.root / "DB").glob("*.bak")))

    def test_local_only_portable_snapshot_without_drive(self):
        from karaoke.local_master import activate
        home = Path(self.tmp.name) / "Installed"
        home.mkdir()
        source = self.root / "SONGS"
        result = build(home, source_songs=source, local_only=True, deduplicate=False)
        self.assertEqual(result["accepted"], 1)
        self.assertEqual(result["pending_drive_ids"], 1)
        self.assertFalse((home / "SONGS").exists())
        self.assertFalse((self.root / "DB/songs.sqlite3").exists())
        settings = {"pending_online_master": {"root": str(home), "generation": result["generation"],
                    "source_songs": str(source), "local_only": True}}
        master = activate(home, home / "data", settings, installed=True)
        self.assertEqual(master, home / "DB/songs.sqlite3")
        self.assertNotIn("shared_drive_root", settings)
        library = SharedSongLibrary(home, settings, database=master)
        self.assertEqual(library.count(), 1)
        self.assertTrue(Path(library.get(library.search("10001")[0]["id"])["path"]).samefile(self.songs / "10001.xmid"))
        self.assertTrue(library.path.samefile(master))

    def test_export_portable_after_copy_without_rebuilding(self):
        from karaoke.local_master import activate, export_portable
        import shutil
        home = Path(self.tmp.name) / "Installed"
        home.mkdir()
        result = build(home, source_songs=self.root / "SONGS", local_only=True, deduplicate=False)
        settings = {"pending_online_master": {"root": str(home), "generation": result["generation"],
                    "source_songs": str(self.root / "SONGS"), "local_only": True}}
        source = activate(home, home / "data", settings, installed=True)
        before = source.read_bytes()
        destination = Path(self.tmp.name) / "User chosen cloud name"
        destination.mkdir()
        shutil.copytree(self.root / "SONGS", destination / "SONGS")
        (destination / "SOUNDFONT").mkdir()
        exported = export_portable(home, destination)
        self.assertEqual(exported, destination / "DB/songs.sqlite3")
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(SharedSongLibrary(destination, {}).count(), 1)
        with self.assertRaises(FileExistsError):
            export_portable(home, destination)
        old = exported.read_bytes()
        missing = destination / "SONGS/MIDI/XMID/1/10001.xmid"
        original = missing.read_bytes()
        missing.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        with self.assertRaisesRegex(ValueError, "MD5"):
            export_portable(home, destination, overwrite=True)
        self.assertEqual(exported.read_bytes(), old)
        missing.write_bytes(original)
        missing.unlink()
        with self.assertRaises(ValueError):
            export_portable(home, destination, overwrite=True)
        self.assertEqual(exported.read_bytes(), old)
        shutil.copy2(self.songs / "10001.xmid", missing)
        stop = threading.Event()
        stop.set()
        with self.assertRaises(InterruptedError):
            export_portable(home, destination, overwrite=True, cancel=stop)
        self.assertEqual(exported.read_bytes(), old)
        export_portable(home, destination, overwrite=True)
        self.assertEqual(len(list(exported.parent.glob("*.bak"))), 1)
        self.assertEqual(source.read_bytes(), before)

    def test_preview_and_publish_compatible_sqlite(self):
        before=build(self.root,publish=False)
        self.assertEqual(before["accepted"],1)
        self.assertFalse((self.root/"DB/songs.sqlite3").exists())
        result=build(self.root)
        self.assertEqual(result["accepted"],1)
        self.assertEqual(result["pending_drive_ids"],1)
        self.assertEqual(result["duplicates"],0)
        library=SharedSongLibrary(self.root,{})
        self.assertEqual(library.count(),1)
        row=library.search("10001")[0]
        self.assertEqual(row["title"],"เพลงทดสอบ")
        self.assertTrue(library.get(row["id"])["path"].endswith("10001.xmid"))
        with closing(sqlite3.connect(self.root/"DB/songs.sqlite3")) as db:
            self.assertEqual(db.execute("PRAGMA quick_check").fetchone()[0],"ok")
            self.assertEqual(db.execute(
                "SELECT value FROM catalog_meta WHERE key='pcSchema'").fetchone()[0],
                "shared-v1")
            payload=json.loads(db.execute("SELECT payload FROM songs").fetchone()[0])
        self.assertTrue(payload["pendingDriveLink"])
        self.assertFalse(payload["xmid"]["fileId"])
        self.assertFalse((self.root/"DB/songs.sqlite3-wal").exists())
        self.assertFalse((self.root/"DB/songs.sqlite3-shm").exists())

    def test_xmid_missing_artist_or_title_remains_searchable_and_cached(self):
        (self.songs/"10001.xmid").write_bytes(
            _xmid("10001","เพลงไม่มีศิลปิน","   ",self.midi))
        changed = bytearray(self.midi)
        changed[13] = 97
        (self.songs/"10002.xmid").write_bytes(
            _xmid("10002","","ศิลปินจริง",bytes(changed)))
        cache = Path(self.tmp.name) / "index-cache"
        preview = build(self.root, cache_dir=cache, publish=False)
        self.assertEqual(preview["accepted"], 2)
        result = build(self.root, cache_dir=cache)
        self.assertEqual(result["reused"], 2)
        with closing(sqlite3.connect(self.root/"DB/songs.sqlite3")) as db:
            rows = db.execute(
                "SELECT code,title,artist,playable,payload FROM songs ORDER BY code"
            ).fetchall()
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(rows[0][:4], ("10001","เพลงไม่มีศิลปิน","ไม่ระบุศิลปิน",1))
        self.assertEqual(rows[1][:4], ("10002","10002","ศิลปินจริง",1))
        self.assertTrue(all(json.loads(row[4])["metadataComplete"] is False for row in rows))
        library = SharedSongLibrary(self.root,{})
        self.assertEqual(library.search("เพลงไม่มีศิลปิน")[0]["code"], "10001")
        self.assertEqual(library.search("10002")[0]["title"], "10002")

    def test_midi_dedup_and_distinct_xsk2(self):
        (self.songs/"10002.xmid").write_bytes(
            _xmid("10002","ซ้ำ","ศิลปินใหม่",self.midi))
        changed=bytearray(self.midi)
        changed[13]=97
        (self.songs/"10003.xsk").write_bytes(
            _xsk("10003","เพลง XSK","ศิลปิน XSK",bytes(changed)))
        stats=build(self.root)
        self.assertEqual(stats["scanned"],3)
        self.assertEqual(stats["accepted"],2)
        self.assertEqual(stats["duplicates"],1)
        lib=SharedSongLibrary(self.root,{})
        self.assertEqual({x["source_format"] for x in lib.search("")},
                         {"XMID","XSK"})

    def test_cancel_unchanged_old_database(self):
        old=self.root/"DB/songs.sqlite3"
        old.write_bytes(b"old-database-placeholder")
        stopped=threading.Event()
        stopped.set()
        with self.assertRaises(InterruptedError):
            build(self.root,cancel=stopped)
        self.assertEqual(old.read_bytes(),b"old-database-placeholder")

    def test_fast_cache_reuses_verified_unchanged_files(self):
        cache = Path(self.tmp.name) / "index-cache"
        first = build(self.root, cache_dir=cache, publish=False)
        self.assertEqual(first["reused"], 0)
        second = build(self.root, cache_dir=cache)
        self.assertEqual(second["reused"], 1)
        full = build(self.root, cache_dir=cache, publish=False, full_verify=True)
        self.assertEqual(full["reused"], 0)
        (self.songs/"10001.xmid").write_bytes(
            _xmid("10001","เพลงใหม่ยาวกว่า","ศิลปิน",self.midi))
        changed = build(self.root, cache_dir=cache)
        self.assertEqual(changed["reused"], 0)
        self.assertEqual(SharedSongLibrary(self.root,{}).search("10001")[0]["title"],"เพลงใหม่ยาวกว่า")
        self.assertFalse((self.root/"DB/songs.sqlite3-wal").exists())

    def test_fast_cache_keeps_verified_work_on_cancel(self):
        cache = Path(self.tmp.name) / "index-cache"
        for n in range(10002, 10030):
            (self.songs/f"{n}.xmid").write_bytes(
                _xmid(str(n),"เพลง","ศิลปิน",self.midi))
        # Stop during a preview after a verified package has been saved.
        from unittest.mock import patch
        from karaoke import shared_catalog_builder as builder
        original = builder._record
        stop = threading.Event()
        def record(*args):
            row = original(*args)
            stop.set()
            return row
        with patch.object(builder,"_record",side_effect=record):
            with self.assertRaises(InterruptedError):
                build(self.root,cache_dir=cache,cancel=stop)
        self.assertFalse((self.root/"DB/songs.sqlite3").exists())
        result = build(self.root,cache_dir=cache)
        self.assertGreaterEqual(result["reused"],1)
        self.assertEqual(result["accepted"],1)

    def test_bad_xmid_does_not_publish(self):
        (self.songs/"10001.xmid").write_bytes(b"corrupt")
        with self.assertRaises(ValueError):
            build(self.root)
        self.assertFalse((self.root/"DB/songs.sqlite3").exists())

    def test_preserve_verified_drive_id_on_rebuild(self):
        build(self.root)
        db_path=self.root/"DB/songs.sqlite3"
        with closing(sqlite3.connect(db_path)) as db:
            source=db.execute("SELECT payload FROM songs").fetchone()[0]
            row=json.loads(source)
            row["xmid"]["fileId"]="verifiedDriveSongId123"
            row["pendingDriveLink"]=False
            db.execute("UPDATE songs SET payload=?",
                       (json.dumps(row,ensure_ascii=False),))
            db.commit()
        result=build(self.root)
        self.assertEqual(result["pending_drive_ids"],0)
        with closing(sqlite3.connect(db_path)) as db:
            record=json.loads(db.execute("SELECT payload FROM songs").fetchone()[0])
        self.assertEqual(record["xmid"]["fileId"],"verifiedDriveSongId123")
        self.assertEqual(len(list((self.root/"BACKUP").glob("*.bak"))),1)
        self.assertEqual(list((self.root/"CACHE").iterdir()),[])


if __name__ == "__main__":
    unittest.main()
