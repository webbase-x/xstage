"""Verify folder upload readiness and immediate online DB publication contract."""
from __future__ import annotations
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "songstudio-pc"

def load(name):
    spec = importlib.util.spec_from_file_location(name, BASE / (name + ".py"))
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

folder = load("folder_upload")
export = load("song_export")
online = load("online_publish")


class PublisherStub:
    def __init__(self):
        self.published = []

    def read_code_registry(self, *, allow_missing_root=False):
        return {"visible": False, "songs": []}

    def publish(self, root, rows, *, create_new_library=False, **kwargs):
        assert create_new_library
        assert (root / "current.json").is_file()
        for row in rows:
            assert online._valid_row(root, row)
            assert (root / row["audio"]["path"]).is_file()
            assert (root / row["lyrics"]["path"]).is_file()
            assert (root / Path(row["lyrics"]["path"]).with_suffix(".lrc")).is_file()
        self.published.extend(rows)
        return {"newSongs": len(rows), "updatedSongs": 0,
                "duplicates": 0, "conflicts": 0, "totalSongs": len(rows),
                "published": True}


class FolderUploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.audio = self.root / "A001.mp3"
        self.audio.write_bytes(b"ID3" + b"x" * 2500)
        self.lrc = self.root / "A001.lrc"
        self.lrc.write_text("[00:05.00]ร้องเพลงบรรทัดแรก\n[00:12.50]บรรทัดสอง", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_publish_ready_audio_and_lyrics_through_online_catalog(self):
        publisher = PublisherStub()
        result = folder.upload(object(), str(self.root), create_new_library=True,
                               export=export, publisher=publisher, staging_root=self.root)
        self.assertEqual(result["newSongs"], 1)
        self.assertTrue(result["published"])
        self.assertEqual(result["ready"], 1)
        self.assertEqual(self.audio.read_bytes(), b"ID3" + b"x" * 2500)
        self.assertFalse(list(self.root.glob("xstage-upload-*")))

    def test_existing_stageweb_catalog_publishes_original_rows(self):
        self.audio.unlink()
        self.lrc.unlink()
        library = self.root / "StageWeb"
        audio = library / "audio" / "0" / "00001.m4a"
        lyric = library / "lyrics" / "0" / "00001.json"
        audio.parent.mkdir(parents=True)
        lyric.parent.mkdir(parents=True)
        audio.write_bytes(b"A" * 4500)
        lyric.write_text(json.dumps(export.lrc_to_json(
            "[00:05.00]ทดสอบต้นฉบับ", "00001"), ensure_ascii=False), encoding="utf-8")
        lyric.with_suffix(".lrc").write_text("[00:05.00]ทดสอบต้นฉบับ", encoding="utf-8")
        record = {"webSongId": "audio/0/00001", "code": "00001",
                  "title": "เพลงทดสอบ", "artist": "", "bucket": "0",
                  "audio": {"path": "audio/0/00001.m4a"},
                  "lyrics": {"path": "lyrics/0/00001.json"}}
        export.publish_batch(library, [record])
        summary = folder.report(str(self.root), export)
        self.assertEqual(summary["ready"], 1)
        publisher = PublisherStub()
        uploaded = folder.upload(object(), str(self.root),
                                 create_new_library=True, export=export,
                                 publisher=publisher, staging_root=self.root,
                                 validator=online._valid_row)
        self.assertEqual(uploaded["newSongs"], 1)
        self.assertEqual(publisher.published[0]["webSongId"], record["webSongId"])

    def test_soundfont_header_and_private_folder_upload(self):
        font = self.root / "Piano.sf2"
        # A minimal RIFF sfbk header is adequate for header-only preflight.
        font.write_bytes(b"RIFF" + b"\x00"*4 + b"sfbk" + b"x"*1000)
        self.assertEqual(folder.inspect_soundfont(str(font))["format"], "SF2")

        class FakeDrive:
            def __init__(self):
                self.folders = {}
                self.files = {}
            def list_children(self, parent):
                return [dict(id=ident, name=name,
                    mimeType=folder.FOLDER) for (p,name), ident in self.folders.items()
                    if p == parent]
            def folder(self, parent, name):
                key=(parent,name)
                if key not in self.folders:
                    self.folders[key]=str(len(self.folders)+1)
                return self.folders[key]
            def upload_file(self, parent, path, name, **kwargs):
                key=(parent,name)
                value=folder.digest(path)
                if key in self.files:
                    return "skipped", self.files[key]
                item={"id":"media1", "md5Checksum":value}
                self.files[key]=item
                return "created", item
        drive=FakeDrive()
        first=folder.upload_soundfont(drive,str(font),create_new_library=True)
        second=folder.upload_soundfont(drive,str(font),create_new_library=True)
        self.assertTrue(first["uploaded"])
        self.assertTrue(second["skipped"])
        self.assertEqual(first["path"].split("/")[:2], ["XStageWeb","AUDIO"])
        self.assertTrue(first["webMidiReady"])

    def test_invalid_soundfont_is_rejected_without_upload(self):
        font = self.root / "fake.sf3"
        font.write_bytes(b"not a SoundFont"*100)
        with self.assertRaisesRegex(ValueError,"RIFF"):
            folder.inspect_soundfont(str(font))

    def test_missing_lyrics_does_not_publish(self):
        self.lrc.unlink()
        self.assertEqual(folder.report(str(self.root))["ready"], 0)
        with self.assertRaises(ValueError):
            folder.upload(object(), str(self.root), create_new_library=True,
                          export=export, publisher=PublisherStub(), staging_root=self.root)

    def test_existing_folder_requires_complete_ncn_companions(self):
        self.audio.unlink()
        self.lrc.unlink()
        (self.root / "001.mid").write_bytes(b"MThd" + b"\0"*50)
        (self.root / "001.lyr").write_bytes(b"\x00"*90)
        (self.root / "001.cur").write_bytes(b"\x00"*100)
        scan = folder.scan(str(self.root))
        self.assertEqual(scan["total"], 1)
        self.assertEqual(scan["complete"][0]["kind"], "NCN")
        with self.assertRaises(ValueError):
            folder.upload(object(), str(self.root), create_new_library=True,
                          export=export, publisher=PublisherStub(), staging_root=self.root)

    def test_organized_audio_songs_lyrics_pair(self):
        self.audio.unlink()
        self.lrc.unlink()
        song = self.root / "AUDIO" / "MP3" / "Songs" / "A" / "A001.mp3"
        lyr = self.root / "AUDIO" / "MP3" / "Lyrics" / "A" / "A001.lrc"
        song.parent.mkdir(parents=True)
        lyr.parent.mkdir(parents=True)
        song.write_bytes(b"ID3"+b"A"*2400)
        lyr.write_text("[00:01.00]ทดสอบ", encoding="utf-8")
        self.assertEqual(folder.report(str(self.root))["ready"], 1)


if __name__ == "__main__":
    unittest.main()
