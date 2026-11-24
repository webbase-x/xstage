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
