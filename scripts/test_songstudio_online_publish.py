"""XStageWeb online publish protocol tests against a private mock Drive.

No real Google OAuth is used. The production publisher and upload_file paths
run; only the Google network transport is mocked.
"""
from __future__ import annotations
import importlib.util
import hashlib
import io
import urllib.parse
import zipfile
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_songstudio_drive_roundtrip import FakePrivateDrive
import test_songstudio_drive_roundtrip as roundtrip

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "xstage_online_publish_test", REPO / "songstudio-pc" / "online_publish.py")
online = importlib.util.module_from_spec(spec)
spec.loader.exec_module(online)


class FakeOnlineDrive(FakePrivateDrive):
    def api(self, route, query=None, *, method="GET", data=None):
        if route.startswith("/files/") and method == "GET":
            ident = route.split("/")[-1]
            return dict(self.items[ident]["metadata"])
        raise AssertionError("Unexpected Google API call: " + route)


class OnlinePublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "songs"
        self.root.mkdir()
        (self.root / "current.json").write_text('{"songCount":1}', encoding="utf-8")
        self.drive = FakeOnlineDrive()
        # Existing visible XStageWeb library is normal for incremental syncing.
        self.drive.folder("root", "XStageWeb")
        self.publisher = online.OnlinePublisher(self.drive)
        self.source_json = self.publisher._json
        # Mock ONLY the private Drive GET file body. Actual JSON schema
        # parsing, upload_file, pointer switching and metadata reads stay real.
        self.publisher._json = lambda ident: json.loads(
            self.drive.items[str(ident)]["body"].decode("utf-8"))
        self.first = self.make_song("00001", b"A" * 5200, "เพลงหนึ่ง")

    def tearDown(self):
        self.temp.cleanup()

    def make_song(self, code, audio, lyric, *, with_lyrics=True):
        bucket = code[0]
        audio_path = "audio/" + bucket + "/" + code + ".m4a"
        lyric_path = "lyrics/" + bucket + "/" + code + ".json"
        (self.root / audio_path).parent.mkdir(parents=True, exist_ok=True)
        (self.root / audio_path).write_bytes(audio)
        record = {"webSongId": "audio/" + bucket + "/" + code,
                  "code": code, "title": "เพลง " + code, "artist": "ศิลปิน",
                  "sourceFormat": "NCN", "audio": {"path": audio_path}}
        if with_lyrics:
            (self.root / lyric_path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / lyric_path).write_text(json.dumps({
                "schemaVersion": 1, "lines": [{"startTime": 1, "endTime": 4,
                                               "text": lyric}]}, ensure_ascii=False),
                                               encoding="utf-8")
            (self.root / ("lyrics/" + bucket + "/" + code + ".lrc")).write_text(
                "[00:01.00]" + lyric, encoding="utf-8")
            record["lyrics"] = {"path": lyric_path}
        return record

    def folder_files(self, parent="root"):
        return [r["metadata"] for r in self.drive.items.values()
                if r["parent"] == parent]

    def remote_root(self):
        root = [f for f in self.folder_files() if f["name"] == "XStageWeb"]
        self.assertEqual(len(root), 1)
        return root[0]["id"]

    def pointer(self):
        root_id = self.remote_root()
        entries = [f for f in self.folder_files(root_id) if f["name"] == "current.json"]
        self.assertEqual(len(entries), 1)
        ident = entries[0]["id"]
        return self.publisher._json(ident), ident

    def published(self):
        pointer, _ = self.pointer()
        base = self.publisher._json(pointer["catalogFileId"])
        songs = {s["webSongId"]:s for s in base["songs"]}
        for ident in pointer["deltaFileIds"]:
            part = self.publisher._json(ident)
            for key in part["removes"]:
                songs.pop(key, None)
            for row in part["upserts"]:
                songs[row["webSongId"]] = row
        self.assertEqual(len(songs), pointer["songCount"])
        return songs

    def test_first_publish_matches_online_schema_and_uploads_real_private_files(self):
        result = self.publisher.publish(self.root, [self.first])
        self.assertTrue(result["published"])
        self.assertEqual(result["newSongs"], 1)
        pointer, _ = self.pointer()
        self.assertEqual(pointer["schemaVersion"], 1)
        self.assertEqual(pointer["songCount"], 1)
        self.assertEqual(pointer["deltaFileIds"], [])
        remote = self.published()[self.first["webSongId"]]
        self.assertEqual(remote["code"], "00001")
        self.assertTrue(remote["audio"]["fileId"])
        self.assertTrue(remote["lyrics"]["fileId"])
        self.assertIn(remote["audio"]["fileId"], self.drive.items)
        self.assertIn(remote["lyrics"]["fileId"], self.drive.items)
        self.assertIn(remote["lrc"]["fileId"], self.drive.items)
        self.assertEqual(self.drive.upload_order[-1], "current.json")
        # Neither fake absolute local path nor user OAuth credentials leak.
        self.assertNotIn(str(self.base), json.dumps(remote))
        # Category folders and a compatible current.json are in the root;
        # immutable catalog files are stored under DB/.
        names = {x["name"] for x in self.folder_files(self.remote_root())}
        self.assertTrue({"AUDIO", "VIDEO", "MIDI", "DB", "current.json"}.issubset(names))

    def test_new_drive_publishes_requested_xstageweb_taxonomy(self):
        # Explicit consent only. A genuinely empty Drive gets XStageWeb.
        self.drive.items.clear()
        result = self.publisher.publish(
            self.root, [self.first], create_new_library=True)
        self.assertEqual(result["newSongs"], 1)
        folder = next(
            f["metadata"] for f in self.drive.items.values()
            if f["parent"] == "root" and f["metadata"]["name"] == "XStageWeb")
        children = self.folder_files(folder["id"])
        names = {f["name"] for f in children}
        self.assertTrue({"AUDIO", "VIDEO", "MIDI", "DB", "current.json"}.issubset(names))
        self.assertNotIn("songs", names)
        self.assertNotIn("audio", names)
        pointer_id = next(f["id"] for f in children if f["name"] == "current.json")
        pointer = self.publisher._json(pointer_id)
        songs = self.publisher._json(pointer["catalogFileId"])["songs"]
        self.assertEqual(len(songs), 1)
        self.assertTrue(songs[0]["audio"]["path"].startswith("AUDIO/M4A/Songs/0/"))
        self.assertTrue(songs[0]["lyrics"]["path"].startswith("AUDIO/M4A/Lyrics/0/"))
        self.assertTrue(songs[0]["lrc"]["path"].startswith("AUDIO/M4A/Lyrics/0/"))
        self.drive.locked = True
        with patch.object(roundtrip.drive, "_request",
                          side_effect=self._download_private_json):
            got = self.drive.download_library(self.base / "stage-download", "songs")
            db = self.drive.download_library(self.base / "stage-db", "db")
        self.assertEqual(got["source"], "XStageWeb")
        self.assertEqual(Path(got["path"]).name, "XStageWeb")
        self.assertEqual(len(list(Path(got["path"]).rglob("*.m4a"))), 1)
        self.assertEqual(db["files"], 2)

    def test_raw_xstageweb_folder_without_pointer_downloads_songs_zip_db(self):
        """User-managed AUDIO/MIDI/VIDEO/DB libraries need not have current.json."""
        self.drive.items.clear()
        root = self.drive.folder("root", "XStageWeb")
        audio = self.drive.folder(self.drive.folder(
            self.drive.folder(self.drive.folder(root, "AUDIO"), "MP3"), "Songs"), "A")
        mid = self.drive.folder(self.drive.folder(
            self.drive.folder(root, "MIDI"), "NCN"), "Cursor")
        db = self.drive.folder(root, "DB")
        sample = self.base / "sample.mp3"
        sample.write_bytes(b"ID3" + b"Z" * 5000)
        cursor = self.base / "sample.cur"
        cursor.write_bytes(b"C" * 1200)
        catalog = self.base / "catalog-data.json"
        catalog.write_text('{"count":1}', encoding="utf-8")
        self.drive.upload_file(audio, sample, "A001.mp3")
        self.drive.upload_file(mid, cursor, "A001.CUR")
        self.drive.upload_file(db, catalog, "library.json")
        self.drive.locked = True
        count = len(self.drive.items)
        with patch.object(roundtrip.drive, "_request",
                          side_effect=self._download_private_json):
            songs = self.drive.download_library(self.base / "raw-songs", "songs")
            database = self.drive.download_library(self.base / "raw-db", "db")
            archive = self.drive.download_library(self.base / "raw-zip", "zip")
        restored = Path(songs["path"])
        self.assertEqual((restored / "AUDIO/MP3/Songs/A/A001.mp3").read_bytes(),
                         sample.read_bytes())
        self.assertEqual((restored / "MIDI/NCN/Cursor/A001.CUR").read_bytes(),
                         cursor.read_bytes())
        self.assertFalse((restored / "DB").exists())
        self.assertEqual((Path(database["path"]) / "DB/library.json").read_bytes(),
                         catalog.read_bytes())
        self.assertFalse((Path(database["path"]) / "AUDIO").exists())
        with zipfile.ZipFile(archive["path"]) as bundle:
            self.assertIn("XStageWeb/AUDIO/MP3/Songs/A/A001.mp3", bundle.namelist())
            self.assertIn("XStageWeb/DB/library.json", bundle.namelist())
        self.assertEqual(len(self.drive.items), count)

    def test_raw_xstageweb_db_without_database_gives_clear_error(self):
        self.drive.items.clear()
        root = self.drive.folder("root", "XStageWeb")
        audio = self.drive.folder(root, "AUDIO")
        song = self.base / "alone.m4a"
        song.write_bytes(b"A" * 2000)
        self.drive.upload_file(audio, song, "alone.m4a")
        self.drive.locked = True
        with self.assertRaisesRegex(roundtrip.drive.GoogleError, "ไม่พบไฟล์ DB"):
            self.drive.download_library(self.base / "missing-db", "db")

    def test_raw_xstageweb_rejects_unsafe_names_without_writing(self):
        self.drive.items.clear()
        root = self.drive.folder("root", "XStageWeb")
        source = self.base / "file.mp3"
        source.write_bytes(b"A" * 2000)
        self.drive.upload_file(root, source, "../unsafe.mp3")
        self.drive.locked = True
        with self.assertRaisesRegex(roundtrip.drive.GoogleError, "ไม่ปลอดภัย"):
            self.drive.download_library(self.base / "unsafe", "songs")
        self.assertFalse((self.base / "unsafe").exists())

    def test_visible_old_and_new_cloud_roots_do_not_create_duplicate_catalog(self):
        self.drive.folder("root", "StageWeb")
        before = len(self.drive.items)
        with self.assertRaisesRegex(online.PublishError, "มากกว่าหนึ่ง"):
            self.publisher.publish(self.root, [self.first], create_new_library=True)
        self.assertEqual(len(self.drive.items), before)

    def _download_private_json(self, url, **kwargs):
        ident = urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]
        return io.BytesIO(self.drive.items[ident]["body"])

    def test_download_published_xstageweb_from_real_online_schema(self):
        self.publisher.publish(self.root, [self.first])
        # An old empty PC backup tree should not shadow a valid online
        # library. Download never creates folders or changes Drive media.
        self.drive.folder(self.drive.folder("root", "X-Stage Song Studio"), "songs")
        self.drive.locked = True
        original_count = len(self.drive.items)
        with patch.object(roundtrip.drive, "_request",
                          side_effect=self._download_private_json):
            folder = self.drive.download_library(self.base / "restore", kind="songs")
            restored = Path(folder["path"])
            self.assertEqual(folder["source"], "XStageWeb")
            self.assertEqual(restored.name, "XStageWeb")
            self.assertTrue((restored / "current.json").is_file())
            self.assertEqual(len(list(restored.glob("DB/catalog-base-*.json"))), 1)
            self.assertTrue(list(restored.rglob("*.m4a")))
            self.assertTrue(list(restored.rglob("*.lrc")))
            self.assertTrue(list(restored.rglob("*.json")))
            db = self.drive.download_library(self.base / "db", kind="db")
            self.assertEqual(db["files"], 2)
            self.assertTrue((Path(db["path"]) / "current.json").is_file())
            self.assertFalse(list(Path(db["path"]).rglob("*.m4a")))
            archive = self.drive.download_library(self.base / "zip", kind="zip")
        with zipfile.ZipFile(archive["path"]) as bundle:
            self.assertIn("XStageWeb/current.json", bundle.namelist())
            self.assertTrue(any(x.startswith("XStageWeb/AUDIO/M4A/Songs/") for x in bundle.namelist()))
        self.assertEqual(len(self.drive.items), original_count)

    def test_online_restore_includes_delta_and_current_media_only(self):
        self.publisher.publish(self.root, [self.first])
        next_song = self.make_song("10002", b"B" * 5200, "เพลงสอง")
        self.publisher.publish(self.root, [self.first, next_song])
        # The second generation references the existing immutable base
        # plus a delta; all current songs must be downloaded.
        self.drive.locked = True
        with patch.object(roundtrip.drive, "_request",
                          side_effect=self._download_private_json):
            result = self.drive.download_library(self.base / "delta", "songs")
            db = self.drive.download_library(self.base / "delta-db", "db")
        downloaded = Path(result["path"])
        self.assertEqual(len(list(downloaded.rglob("*.m4a"))), 2)
        self.assertTrue(list(downloaded.glob("DB/catalog-delta-*.json")) )
        self.assertEqual(db["files"], 3)
        pointer = json.loads((downloaded / "current.json").read_text(encoding="utf-8"))
        self.assertEqual(pointer["songCount"], 2)

    def test_online_download_rejects_unpublished_staging_without_creating_files(self):
        self.drive.folder("root", "XStageWeb")
        self.drive.locked = True
        target = self.base / "not-started"
        with patch.object(roundtrip.drive, "_request",
                          side_effect=self._download_private_json):
            with self.assertRaisesRegex(roundtrip.drive.GoogleError, "ไม่พบไฟล์ที่แอปเข้าถึงได้"):
                self.drive.download_library(target, kind="songs")
        self.assertFalse(target.exists())

    def test_online_download_missing_catalog_access_does_not_fallback_to_legacy(self):
        self.publisher.publish(self.root, [self.first])
        pointer, _ = self.pointer()
        self.drive.items.pop(pointer["catalogFileId"])
        self.drive.locked = True
        target = self.base / "catalog-invisible"
        with patch.object(roundtrip.drive, "_request",
                          side_effect=self._download_private_json):
            with self.assertRaises((KeyError, roundtrip.drive.GoogleError)):
                self.drive.download_library(target, kind="db")
        self.assertFalse(target.exists())

    def test_online_download_corrupt_md5_and_target_collision_fail_closed(self):
        self.publisher.publish(self.root, [self.first])
        pointer, pointer_id = self.pointer()
        self.drive.items[pointer_id]["metadata"]["md5Checksum"] = "f" * 32
        self.drive.locked = True
        with patch.object(roundtrip.drive, "_request",
                          side_effect=self._download_private_json):
            with self.assertRaisesRegex(roundtrip.drive.GoogleError, "MD5"):
                self.drive.download_library(self.base / "corrupt", "songs")
        self.assertFalse((self.base / "corrupt").exists())
        self.drive.items[pointer_id]["metadata"]["md5Checksum"] = hashlib.md5(
            self.drive.items[pointer_id]["body"]).hexdigest()
        conflicting = self.base / "conflict" / "XStageWeb" / "current.json"
        conflicting.parent.mkdir(parents=True)
        conflicting.write_bytes(b"owner-existing-content")
        with patch.object(roundtrip.drive, "_request",
                          side_effect=self._download_private_json):
            with self.assertRaisesRegex(roundtrip.drive.GoogleError, "ต่างเนื้อหา"):
                self.drive.download_library(self.base / "conflict", "db")
        self.assertEqual(conflicting.read_bytes(), b"owner-existing-content")

    def test_duplicate_rerun_never_creates_another_song_or_pointer(self):
        self.publisher.publish(self.root, [self.first])
        pointer, _ = self.pointer()
        before = len(self.drive.items)
        second = self.publisher.publish(self.root, [self.first])
        after, _ = self.pointer()
        self.assertEqual(second["duplicates"], 1)
        self.assertFalse(second["published"])
        self.assertEqual(after["generation"], pointer["generation"])
        self.assertEqual(len(self.drive.items), before)

    def test_incremental_delta_preserves_existing_drive_songs(self):
        self.publisher.publish(self.root, [self.first])
        prior, _ = self.pointer()
        original = self.published()[self.first["webSongId"]]
        second = self.make_song("10002", b"B" * 5500, "เพลงสอง")
        added = self.publisher.publish(self.root, [self.first, second])
        self.assertEqual(added["newSongs"], 1)
        self.assertEqual(added["duplicates"], 1)
        pointer, _ = self.pointer()
        self.assertEqual(pointer["catalogFileId"], prior["catalogFileId"])
        self.assertEqual(len(pointer["deltaFileIds"]), 1)
        self.assertEqual(pointer["songCount"], 2)
        self.assertEqual(self.published()[self.first["webSongId"]], original)
        self.assertIn(second["webSongId"], self.published())

    def test_small_batches_publish_immediately_and_player_sees_each_batch(self):
        second = self.make_song("10002", b"B" * 5200, "เพลงสอง")
        third = self.make_song("20003", b"C" * 5300, "เพลงสาม")
        observations = []
        result = self.publisher.publish(
            self.root, [self.first, second, third], batch_size=1,
            on_batch=lambda batch, total, created, revised:
            observations.append((batch, total, len(self.published()))))
        self.assertEqual(result["batches"], 3)
        self.assertEqual(result["totalSongs"], 3)
        self.assertEqual(observations, [(1, 1, 1), (2, 2, 2), (3, 3, 3)])
        self.assertEqual(len(self.pointer()[0]["deltaFileIds"]), 2)

    def test_failure_in_second_batch_leaves_first_batch_playable(self):
        second = self.make_song("10004", b"Z" * 5300, "เพลงสี่")
        original = self.drive.upload_file
        def fail_second(parent, path, name, **kwargs):
            if name.startswith("10004-") and name.endswith(".m4a"):
                raise online.PublishError("upload interrupted")
            return original(parent, path, name, **kwargs)
        with patch.object(self.drive, "upload_file", side_effect=fail_second):
            with self.assertRaisesRegex(online.PublishError, "upload interrupted"):
                self.publisher.publish(self.root, [self.first, second], batch_size=1)
        self.assertEqual(len(self.published()), 1)
        again = self.publisher.publish(self.root, [self.first, second], batch_size=1)
        self.assertEqual(again["duplicates"], 1)
        self.assertEqual(again["newSongs"], 1)
        self.assertEqual(len(self.published()), 2)

    def test_exact_duplicate_audio_and_lyrics_across_two_codes_is_skipped(self):
        duplicate = self.make_song("90009", b"A" * 5200, "เพลงหนึ่ง")
        result = self.publisher.publish(self.root, [self.first, duplicate], batch_size=1)
        self.assertEqual(result["newSongs"], 1)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(result["totalSongs"], 1)
        self.assertEqual(len(self.published()), 1)

    def test_same_code_different_audio_is_conflict_not_silent_overwrite(self):
        self.publisher.publish(self.root, [self.first])
        before = dict(self.published())
        original_pointer, _ = self.pointer()
        self.make_song("00001", b"Z" * 6000, "อีกเนื้อเพลง")
        result = self.publisher.publish(self.root, [self.first])
        self.assertEqual(result["conflicts"], 1)
        self.assertFalse(result["published"])
        self.assertEqual(self.published(), before)
        self.assertEqual(self.pointer()[0]["generation"], original_pointer["generation"])

    def test_same_websongid_different_audio_and_code_keeps_original_drive_song(self):
        self.publisher.publish(self.root, [self.first])
        original = dict(self.published())
        changed = self.make_song("00001", b"Z" * 5200, "เพลงใหม่คนละเพลง")
        changed["code"] = "00002"
        changed["originalCode"] = "00001"
        result = self.publisher.publish(self.root, [changed])
        self.assertEqual(result["newSongs"], 1)
        self.assertEqual(result["conflicts"], 0)
        after = self.published()
        self.assertEqual(len(after), 2)
        self.assertEqual(after[self.first["webSongId"]], original[self.first["webSongId"]])
        self.assertEqual({x["code"] for x in after.values()}, {"00001", "00002"})

    def test_registry_read_requires_visible_pointer_not_just_similar_folder(self):
        with self.assertRaisesRegex(online.PublishError, "ยังไม่มี current.json"):
            self.publisher.read_code_registry()
        self.publisher.publish(self.root, [self.first])
        verified = self.publisher.read_code_registry()
        self.assertTrue(verified["visible"])
        self.assertEqual([x["code"] for x in verified["songs"]], ["00001"])
        self.assertTrue(verified["generation"])

    def test_same_audio_changed_lyrics_preserves_audio_file_id(self):
        self.publisher.publish(self.root, [self.first])
        old = self.published()[self.first["webSongId"]]
        self.make_song("00001", b"A" * 5200, "แก้ไขเนื้อร้องแล้ว")
        result = self.publisher.publish(self.root, [self.first])
        new = self.published()[self.first["webSongId"]]
        self.assertEqual(result["updatedSongs"], 1)
        self.assertEqual(result["newSongs"], 0)
        self.assertEqual(new["audio"]["fileId"], old["audio"]["fileId"])
        self.assertNotEqual(new["lyrics"]["fileId"], old["lyrics"]["fileId"])

    def test_audio_only_does_not_publish_unplayable_song(self):
        only = self.make_song("20003", b"C" * 5200, "", with_lyrics=False)
        with self.assertRaisesRegex(online.PublishError, "Lyrics"):
            self.publisher.publish(self.root, [only])
        self.assertEqual(len(self.drive.items), 1)  # Keep existing empty root untouched

    def test_initial_sync_interruption_can_resume_from_verified_staging(self):
        original = self.drive.upload_file
        def fails_initial_lyrics(parent, path, name, **kwargs):
            if name.startswith("00001-") and name.endswith(".json"):
                raise online.PublishError("first sync interrupted")
            return original(parent, path, name, **kwargs)
        with patch.object(self.drive, "upload_file", side_effect=fails_initial_lyrics):
            with self.assertRaisesRegex(online.PublishError, "first sync interrupted"):
                self.publisher.publish(self.root, [self.first])
        root_id = self.remote_root()
        names = [f["name"] for f in self.folder_files(root_id)]
        self.assertIn(online.STAGING_MARKER, names)
        self.assertNotIn("current.json", names)
        recovered = self.publisher.publish(self.root, [self.first])
        self.assertTrue(recovered["published"])
        self.assertEqual(len(self.published()), 1)

    def test_missing_online_root_never_silently_creates_duplicate_library(self):
        self.drive.items.clear()
        with self.assertRaisesRegex(online.PublishError, "ไม่พบ XStageWeb"):
            self.publisher.publish(self.root, [self.first])
        self.assertEqual(self.drive.items, {})

    def test_explicit_fresh_drive_consent_creates_new_online_root(self):
        self.drive.items.clear()
        result = self.publisher.publish(
            self.root, [self.first], create_new_library=True)
        self.assertTrue(result["published"])
        self.assertEqual(result["totalSongs"], 1)

    def test_legacy_unindexed_online_root_stays_untouched(self):
        root = self.drive.folder("root", "XStageWeb")
        self.drive.folder(root, "audio")
        before = dict(self.drive.items)
        with self.assertRaisesRegex(online.PublishError, "ไม่มี current.json"):
            self.publisher.publish(self.root, [self.first])
        self.assertEqual(self.drive.items, before)

    def test_partial_failure_never_switches_online_pointer(self):
        self.publisher.publish(self.root, [self.first])
        old, _ = self.pointer()
        next_song = self.make_song("30004", b"D" * 5000, "บรรทัดใหม่")
        upload = self.drive.upload_file
        def broken_upload(parent, path, name, **kwargs):
            if name.endswith(".json") and name != "current.json":
                raise online.PublishError("network down")
            return upload(parent, path, name, **kwargs)
        with patch.object(self.drive, "upload_file", side_effect=broken_upload):
            with self.assertRaisesRegex(online.PublishError, "network down"):
                self.publisher.publish(self.root, [next_song])
        self.assertEqual(self.pointer()[0]["generation"], old["generation"])
        self.assertEqual(len(self.published()), 1)
        retry = self.publisher.publish(self.root, [next_song])
        self.assertEqual(retry["newSongs"], 1)
        self.assertEqual(len(self.published()), 2)

    def test_external_generation_change_aborts_pointer_switch(self):
        self.publisher.publish(self.root, [self.first])
        old, pointer_id = self.pointer()
        new = self.make_song("40005", b"E" * 5000, "เพลงใหม่")
        upload = self.drive.upload_file
        def concurrent_upload(parent, path, name, **kwargs):
            if name.startswith("catalog-delta-"):
                latest = dict(old)
                latest["generation"] = "another-publisher"
                self.drive.items[pointer_id]["body"] = json.dumps(latest).encode("utf-8")
            return upload(parent, path, name, **kwargs)
        with patch.object(self.drive, "upload_file", side_effect=concurrent_upload):
            with self.assertRaisesRegex(online.PublishError, "ผู้อื่นอัปเดต"):
                self.publisher.publish(self.root, [new])
        self.assertEqual(self.pointer()[0]["generation"], "another-publisher")


if __name__ == "__main__":
    unittest.main()
