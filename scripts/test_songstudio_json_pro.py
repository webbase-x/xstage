"""Offline regressions for Song Studio Pro Lyrics JSON/media exporter."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1] / "songstudio-pc"


def load(name):
    spec = importlib.util.spec_from_file_location("studio_pro_test_" + name, BASE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pro = load("json_pro_export")
export = load("song_export")
folder_upload = load("folder_upload")


class JsonProTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.dest = self.root / "result"
        self.source.mkdir()
        self.dest.mkdir()
        self.mp3 = self.source / "00001.mp3"
        self.lrc = self.source / "00001.lrc"
        self.mp3.write_bytes(b"ID3" + b"X" * 3000)
        self.lrc.write_text("[00:02.50]เนื้อร้องบรรทัดแรก\n[00:05.10]บรรทัดสอง", encoding="utf-8")

    def run_export(self, fmt="original", **extra):
        return pro.export_folder(str(self.source), str(self.dest), output_format=fmt,
                                 export=export, scanner=folder_upload, **extra)

    def test_checkpoint_publishes_while_more_songs_remain(self):
        stream = load("json_source_stream")
        for number in (2, 3):
            code = f"{number:05d}"
            (self.source / (code + ".mp3")).write_bytes(
                b"ID3" + bytes([number]) * 3001)
            (self.source / (code + ".lrc")).write_text(
                "[00:01.00]บรรทัดทดสอบ", encoding="utf-8")
        with patch.object(pro, "CHECKPOINT_SIZE", 2), patch.object(
                export, "publish_batch", wraps=export.publish_batch) as publisher:
            result = self.run_export(source_stream=stream.stream)
        self.assertEqual(result["created"], 3)
        self.assertEqual(publisher.call_count, 2)
        library = self.dest / "XStageSong"
        self.assertEqual(len(export.existing_records(library)), 3)
        self.assertFalse((library / ".build-journal.jsonl").exists())

    def test_cancel_publishes_completed_song_without_waiting_for_full_scan(self):
        stream = load("json_source_stream")
        (self.source / "00002.mp3").write_bytes(b"ID3" + b"Y" * 3001)
        (self.source / "00002.lrc").write_text(
            "[00:02.00]อีกเพลง", encoding="utf-8")
        cancelled = threading.Event()
        def request_cancel(done, total, state):
            if done == 1:
                cancelled.set()
        with self.assertRaisesRegex(RuntimeError, "ยกเลิก"):
            self.run_export(source_stream=stream.stream, cancelled=cancelled,
                            progress=request_cancel)
        library = self.dest / "XStageSong"
        self.assertEqual(len(export.existing_records(library)), 1)
        self.assertFalse((library / ".build-journal.jsonl").exists())

    def test_stream_creates_json_from_ncn_without_any_source_json(self):
        stream = load("json_source_stream")
        self.mp3.unlink()
        self.lrc.unlink()
        src = self.source / "MIDI/NCN"
        midi = src / "SONG/0/00022.mid"
        lyr = src / "LYR/0/00022.lyr"
        cur = src / "CUR/0/00022.cur"
        for p in (midi, lyr, cur):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"NCN" + b"A" * 70)
        class UnusedPreflight:
            def scan(self, *args, **kwargs):
                raise AssertionError("Full-library preflight should never run")
        class Ncn:
            def ncn_document(self, companion):
                self.last = companion
                return export.lrc_to_json("[00:01.00]ตัวอย่างต้นฉบับ", companion["code"])
        ncn = Ncn()
        result = pro.export_folder(
            str(self.source), str(self.dest), output_format="original",
            export=export, scanner=UnusedPreflight(), ncn=ncn,
            source_stream=stream.stream)
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["total"], 1)
        self.assertEqual(ncn.last["code"], "00022")
        library = self.dest / "XStageSong"
        records = export.existing_records(library)
        self.assertEqual(len(records), 1)
        row = records[0]
        self.assertEqual(row["sourceFormat"], "NCN")
        self.assertIsNotNone(row["lyrics"])
        self.assertEqual(row["code"], Path(row["lyrics"]["path"]).stem)
        self.assertFalse((src / "SONG/0/00022.json").exists())
        repeat = pro.export_folder(
            str(self.source), str(self.dest), output_format="original",
            export=export, scanner=UnusedPreflight(), ncn=ncn,
            source_stream=stream.stream)
        self.assertEqual(repeat["created"], 0)
        self.assertEqual(repeat["skipped"], 1)

    def test_stream_keeps_existing_mp3_lrc_compatibility(self):
        stream = load("json_source_stream")
        result = self.run_export(source_stream=stream.stream)
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["total"], 1)

    def test_copy_original_json_and_catalog_skip_repeat(self):
        before = hashlib.sha256(self.mp3.read_bytes()).hexdigest()
        first = self.run_export()
        self.assertEqual(first["created"], 1)
        target = self.dest / "XStageSong"
        records = export.existing_records(target)
        self.assertEqual(len(records), 1)
        record = records[0]
        audio = export.safe_media_path(target, record["audio"]["path"], "audio")
        lyrics = export.safe_media_path(target, record["lyrics"]["path"], "lyrics")
        self.assertEqual(record["audio"]["path"], "AUDIO/MP3/SONG/0/00001.mp3")
        self.assertEqual(record["lyrics"]["path"], "AUDIO/MP3/LYRICS/0/00001.json")
        # Windows uses a case-insensitive filesystem: AUDIO and audio name
        # resolve to the same folder. Assert canonical catalog paths instead.
        self.assertTrue((target / "AUDIO").is_dir())
        self.assertTrue((target / "AUDIO/MP3/LYRICS").is_dir())
        self.assertEqual(hashlib.sha256(audio.read_bytes()).hexdigest(), before)
        doc = json.loads(lyrics.read_text(encoding="utf-8"))
        self.assertEqual(doc["lines"][0]["startTime"], 2.5)
        self.assertEqual(doc["lines"][1]["startTime"], 5.1)
        self.assertEqual(record["code"], audio.stem)
        self.assertEqual(record["code"], lyrics.stem)
        self.assertEqual(doc["songCode"], record["code"])
        self.assertEqual(record["code"], "00001")
        second = self.run_export()
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(export._read_current(target)[0]["songCount"], 1)
        self.assertEqual(hashlib.sha256(self.mp3.read_bytes()).hexdigest(), before)

    def test_configurable_code_length_matches_both_files(self):
        result = self.run_export(code_style="numeric", code_length=7)
        self.assertEqual(result["created"], 1)
        root = self.dest / "XStageSong"
        record = export.existing_records(root)[0]
        audio = export.safe_media_path(root, record["audio"]["path"], "audio")
        lyrics = export.safe_media_path(root, record["lyrics"]["path"], "lyrics")
        self.assertEqual(record["code"], "0000001")
        self.assertEqual((audio.stem, lyrics.stem), ("0000001", "0000001"))
        self.assertEqual(json.loads(lyrics.read_text(encoding="utf-8"))["songCode"], "0000001")

    def test_typed_pro_export_roundtrips_to_karaoke_pc_database(self):
        pc = load("pc_library_export")
        created = self.run_export()
        self.assertEqual(created["created"], 1)
        source = self.dest / "XStageSong"
        karaoke = self.root / "KaraokePC"
        outcome = pc.publish(source, str(karaoke), export)
        self.assertEqual(outcome["songCount"], 1)
        root = karaoke / "XStageSong"
        self.assertTrue((root / "AUDIO/MP3/SONG/0/00001.mp3").is_file())
        self.assertTrue((root / "AUDIO/MP3/LYRICS/0/00001.json").is_file())
        self.assertTrue((root / "LYRICS/current.json").is_file())
        doc = json.loads((root / "DB/songs-portable.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["songs"][0]["audio"]["path"], "AUDIO/MP3/SONG/0/00001.mp3")
        self.assertTrue((root / "DB/songs.sqlite3").is_file())

    def test_standalone_kar_has_no_redundant_lyrics_and_pc_db_roundtrip(self):
        kar = self.source / "00077.kar"
        kar.write_bytes(b"MThd" + b"K" * 128)
        class Scanner:
            def scan(self, folder, ncn=None, progress=None):
                if progress:
                    progress("discover", 1, None)
                    progress("validate", 1, 1)
                return {"complete": [{"kind": "KAR", "name": kar.stem,
                                     "files": [(kar, ("MIDI", "KAR"))]}],
                        "incomplete": [], "unsupported": []}
        class Ncn:
            def kar_document(self, path, code):
                return export.lrc_to_json("[00:01.00]ทดสอบ KAR", code)
        result = pro.export_folder(
            str(self.source), str(self.dest), output_format="original",
            export=export, scanner=Scanner(), ncn=Ncn())
        self.assertEqual(result["created"], 1)
        root = self.dest / "XStageSong"
        record = export.existing_records(root)[0]
        self.assertEqual(record["audio"]["path"], "MIDI/KAR/0/00001.kar")
        self.assertIsNone(record["lyrics"])
        self.assertFalse((root / "MIDI/KAR/LYRICS").exists())
        pc = load("pc_library_export")
        dest = self.root / "standalone-kar-pc"
        output = pc.publish(root, str(dest), export)
        self.assertEqual(output["songCount"], 1)
        library = dest / "XStageSong"
        self.assertTrue((library / "MIDI/KAR/0/00001.kar").is_file())
        portable = json.loads((library / "DB/songs-portable.json").read_text(encoding="utf-8"))
        self.assertIsNone(portable["songs"][0]["lyrics"])

    def test_source_code_style_keeps_safe_filename(self):
        result = self.run_export(code_style="source", code_length=5)
        self.assertEqual(result["created"], 1)
        record = export.existing_records(self.dest / "XStageSong")[0]
        self.assertEqual(record["code"], "00001")

    def test_letters_code_style(self):
        result = self.run_export(code_style="letters", code_length=3)
        self.assertEqual(result["created"], 1)
        record = export.existing_records(self.dest / "XStageSong")[0]
        self.assertEqual(record["code"], "AAB")
        self.assertEqual(record["audio"]["path"], "AUDIO/MP3/SONG/A/AAB.mp3")
        self.assertEqual(record["lyrics"]["path"], "AUDIO/MP3/LYRICS/A/AAB.json")

    def test_invalid_code_width_rejected(self):
        with self.assertRaisesRegex(ValueError, "1–12"):
            self.run_export(code_length=0)

    def test_nested_audio_and_lyrics_json_with_conversion(self):
        self.mp3.unlink()
        self.lrc.unlink()
        media = self.source / "Album" / "AUDIO" / "00234.mp3"
        lyric = self.source / "Album" / "LYRICS" / "00234.json"
        media.parent.mkdir(parents=True)
        lyric.parent.mkdir(parents=True)
        media.write_bytes(b"ID3" + b"T" * 3000)
        doc = export.lrc_to_json("[00:05.25]ทดสอบ", "00234")
        lyric.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        def fake_convert(src, out, fmt):
            self.assertEqual(fmt, "m4a")
            out.write_bytes(b"FAKE" + b"M" * 3000)
        result = self.run_export("m4a", convert=fake_convert)
        self.assertEqual(result["created"], 1)
        record = export.existing_records(self.dest / "XStageSong")[0]
        self.assertTrue(record["audio"]["path"].endswith(".m4a"))
        self.assertTrue(media.read_bytes().startswith(b"ID3"))
        self.assertEqual(record["sourceFormat"], "MP3")

    def test_renaming_identical_audio_and_lyrics_does_not_duplicate(self):
        original = self.mp3.read_bytes()
        text = self.lrc.read_text(encoding="utf-8")
        self.assertEqual(self.run_export()["created"], 1)
        (self.source / "99999.mp3").write_bytes(original)
        (self.source / "99999.lrc").write_text(text, encoding="utf-8")
        repeat = self.run_export()
        self.assertEqual(repeat["created"], 0)
        self.assertEqual(repeat["skipped"], 2)
        self.assertEqual(len(export.existing_records(
            self.dest / "XStageSong")), 1)

    def test_editing_only_lyrics_creates_new_immutable_version(self):
        first = self.run_export()
        self.assertEqual(first["created"], 1)
        root = self.dest / "XStageSong"
        original = export.existing_records(root)[0]
        audio_before = export.safe_media_path(root, original["audio"]["path"], "audio")
        lyrics_before = export.safe_media_path(root, original["lyrics"]["path"], "lyrics")
        original_audio = audio_before.read_bytes()
        original_text = lyrics_before.read_text(encoding="utf-8")
        self.lrc.write_text("[00:02.50]คำร้องที่แก้ไขแล้ว\\n[00:05.10]บรรทัดสอง",
                            encoding="utf-8")
        updated = self.run_export()
        self.assertEqual(updated["created"], 1)
        records = export.existing_records(root)
        self.assertEqual(len(records), 2)
        self.assertEqual(audio_before.read_bytes(), original_audio)
        self.assertEqual(lyrics_before.read_text(encoding="utf-8"), original_text)
        self.assertEqual(len({row["lyrics"]["path"] for row in records}), 2)
        self.assertEqual(len({row["webSongId"] for row in records}), 2)
        self.assertNotEqual(records[0]["sourceIdentity"]["lyricsSha256"],
                            records[1]["sourceIdentity"]["lyricsSha256"])
        again = self.run_export()
        self.assertEqual(again["created"], 0)
        self.assertEqual(again["skipped"], 1)

    def test_json_title_and_artist_are_preserved_in_catalog(self):
        self.mp3.unlink()
        self.lrc.unlink()
        midi = self.source / "02345.mid"
        midi.write_bytes(b"MThd" + b"T" * 100)
        doc = export.lrc_to_json("[00:01.50]เพลงไทย", "02345")
        doc["title"] = "ชื่อเพลงจาก JSON"
        doc["artist"] = "ศิลปินจาก JSON"
        (self.source / "02345.json").write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        result = self.run_export()
        self.assertEqual(result["created"], 1)
        saved = export.existing_records(self.dest / "XStageSong")[0]
        self.assertEqual(saved["title"], "ชื่อเพลงจาก JSON")
        self.assertEqual(saved["artist"], "ศิลปินจาก JSON")
        self.assertEqual(saved["audio"]["path"], "MIDI/MID/SONG/0/00001.mid")
        self.assertEqual(saved["lyrics"]["path"], "MIDI/MID/LYRICS/0/00001.json")

    def test_lrc_title_artist_survive_json_catalog_and_pc_export(self):
        pc = load("pc_library_export")
        self.lrc.write_text(
            "[ti:เพลงจากหัว LRC]\n[ar:ศิลปินจากหัว LRC]\n"
            "[00:02.50]เนื้อร้องบรรทัดแรก\n", encoding="utf-8")
        outcome = self.run_export()
        self.assertEqual(outcome["created"], 1)
        root = self.dest / "XStageSong"
        record = export.existing_records(root)[0]
        self.assertEqual((record["title"], record["artist"]),
                         ("เพลงจากหัว LRC", "ศิลปินจากหัว LRC"))
        doc = json.loads(export.safe_media_path(
            root, record["lyrics"]["path"], "lyrics").read_text(encoding="utf-8"))
        self.assertEqual((doc["title"], doc["artist"]),
                         ("เพลงจากหัว LRC", "ศิลปินจากหัว LRC"))
        out = self.root / "karaoke"
        pc.publish(root, str(out), export)
        manifest = json.loads((out / "XStageSong/DB/songs-portable.json").read_text(
            encoding="utf-8"))
        self.assertEqual((manifest["songs"][0]["title"],
                          manifest["songs"][0]["artist"]),
                         ("เพลงจากหัว LRC", "ศิลปินจากหัว LRC"))

    def test_ncn_metadata_promoted_to_top_level_json_and_catalog(self):
        stream = load("json_source_stream")
        self.mp3.unlink()
        self.lrc.unlink()
        base = self.source / "MIDI/NCN"
        midi = base / "SONG/0/00022.mid"
        lyr = base / "LYR/0/00022.lyr"
        cur = base / "CUR/0/00022.cur"
        for path in (midi, lyr, cur):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"MThd" + b"X" * 100)
        class Ncn:
            def ncn_document(self, companion):
                doc = export.lrc_to_json("[00:01.00]หนึ่งบรรทัด", companion["code"])
                doc["metadata"] = {"title": "เพลงจาก LYR", "artist": "ศิลปินจาก LYR"}
                return doc
        result = self.run_export(ncn=Ncn(), source_stream=stream.stream)
        self.assertEqual(result["created"], 1)
        root = self.dest / "XStageSong"
        record = export.existing_records(root)[0]
        self.assertEqual((record["title"], record["artist"]),
                         ("เพลงจาก LYR", "ศิลปินจาก LYR"))
        doc = json.loads(export.safe_media_path(
            root, record["lyrics"]["path"], "lyrics").read_text(encoding="utf-8"))
        self.assertEqual((doc["title"], doc["artist"]),
                         ("เพลงจาก LYR", "ศิลปินจาก LYR"))

    def test_existing_json_nested_identity_and_no_false_program_name(self):
        self.lrc.unlink()
        document = export.lrc_to_json("[00:01.00]คำร้อง", "00001")
        document["title"] = "00001"
        document["artist"] = "X-Stage Song Studio"
        document["metadata"] = {"title": "เพลงใน JSON", "artist": "ศิลปินใน JSON"}
        (self.source / "00001.json").write_text(
            json.dumps(document, ensure_ascii=False), encoding="utf-8")
        result = self.run_export()
        self.assertEqual(result["created"], 1)
        root = self.dest / "XStageSong"
        record = export.existing_records(root)[0]
        self.assertEqual((record["title"], record["artist"]),
                         ("เพลงใน JSON", "ศิลปินใน JSON"))
        doc = json.loads(export.safe_media_path(
            root, record["lyrics"]["path"], "lyrics").read_text(encoding="utf-8"))
        self.assertEqual((doc["title"], doc["artist"]),
                         ("เพลงใน JSON", "ศิลปินใน JSON"))

    def test_missing_name_is_not_silently_replaced_with_code_or_publisher(self):
        result = self.run_export()
        self.assertEqual(result["created"], 1)
        record = export.existing_records(self.dest / "XStageSong")[0]
        self.assertEqual(record["title"], "ไม่ระบุชื่อเพลง")
        self.assertEqual(record["artist"], "ไม่ระบุศิลปิน")


    def test_midi_to_mp3_uses_soundfont_wav_before_ffmpeg(self):
        engine = load("engine")
        midi = self.source / "00088.mid"
        midi.write_bytes(b"MThd" + b"M" * 100)
        wav = self.source / "render-temporary.wav"
        output = self.dest / "00088.mp3"
        args_seen = []

        def render(path):
            self.assertEqual(path, midi)
            wav.write_bytes(b"RIFF" + b"W" * 3000)
            return wav

        def ffmpeg(args):
            args_seen.extend(args)
            Path(args[-1]).write_bytes(b"ID3" + b"A" * 3000)

        with (patch.object(engine, "ensure_midi_wav", side_effect=render),
              patch.object(engine, "ffmpeg_binary", return_value="ffmpeg"),
              patch.object(engine, "run_process", side_effect=ffmpeg)):
            engine.json_pro_transcode(midi, output, "mp3")
        self.assertEqual(args_seen[args_seen.index("-i") + 1], str(wav))
        self.assertTrue(output.is_file())
        self.assertFalse(wav.exists(), "Temporary SoundFont WAV must be removed")

    def test_midi_soundfont_transcode_cleans_wav_after_error(self):
        engine = load("engine")
        midi = self.source / "00088.mid"
        midi.write_bytes(b"MThd" + b"M" * 100)
        wav = self.source / "temporary-failed.wav"

        def render(_):
            wav.write_bytes(b"RIFF" + b"W" * 3000)
            return wav

        with (patch.object(engine, "ensure_midi_wav", side_effect=render),
              patch.object(engine, "ffmpeg_binary", return_value="ffmpeg"),
              patch.object(engine, "run_process", side_effect=RuntimeError("codec failed"))):
            with self.assertRaisesRegex(RuntimeError, "codec failed"):
                engine.json_pro_transcode(midi, self.dest / "broken.ogg", "ogg")
        self.assertFalse(wav.exists())

    def test_output_formats_do_not_mask_other_formats(self):
        self.run_export()
        def fake_convert(src, out, fmt):
            out.write_bytes(b"FAKE" + bytes(fmt, "utf-8") * 1200)
        second = self.run_export("mp3", convert=fake_convert)
        self.assertEqual(second["created"], 1)
        records = export.existing_records(self.dest / "XStageSong")
        self.assertEqual(len(records), 2)

    def test_cannot_write_into_source_tree(self):
        with self.assertRaisesRegex(ValueError, "ต้นทางและปลายทางต้องแยก"):
            pro.export_folder(str(self.source), str(self.source),
                              output_format="original", export=export,
                              scanner=folder_upload)

    def test_recover_complete_files_after_interrupted_journal_append(self):
        with patch.object(export, "append_journal", side_effect=OSError("crash")):
            with self.assertRaisesRegex(ValueError, "ไม่มีไฟล์ที่ส่งออกสำเร็จ"):
                self.run_export()
        root = self.dest / "XStageSong"
        self.assertFalse((root / "current.json").exists())
        self.assertTrue(any((root / "AUDIO").rglob("*.mp3")))
        resumed = self.run_export()
        self.assertEqual(resumed["created"], 1)
        self.assertEqual(resumed["errors"], 0)
        self.assertEqual(len(export.existing_records(root)), 1)

    def test_exclusive_publish_never_overwrites_racing_file(self):
        stage = self.dest / "pending.json"
        target = self.dest / "new.json"
        stage.write_bytes(b"pending")
        def collision(_source, _target):
            target.write_bytes(b"other-process")
            raise FileExistsError("another writer")
        with patch.object(pro.os, "link", side_effect=collision):
            with self.assertRaises(FileExistsError):
                pro._publish_no_overwrite(stage, target)
        self.assertEqual(target.read_bytes(), b"other-process")
        self.assertEqual(stage.read_bytes(), b"pending")

    def test_recover_when_catalog_publish_was_interrupted(self):
        with patch.object(export, "publish_batch", side_effect=OSError("simulated interruption")):
            with self.assertRaisesRegex(OSError, "interruption"):
                self.run_export()
        root = self.dest / "XStageSong"
        self.assertFalse((root / "current.json").exists())
        self.assertEqual(len(export.journal_records(root)), 1)
        resumed = self.run_export()
        self.assertEqual(resumed["skipped"], 1)
        self.assertEqual(export._read_current(root)[0]["songCount"], 1)
        self.assertFalse((root / ".build-journal.jsonl").exists())

    def test_large_old_catalog_does_not_validate_every_media_before_first_song(self):
        # The old flow opened each media file and Lyrics JSON before finding
        # even the first source. Legacy metadata must be indexed without I/O.
        old = [
            {"webSongId": f"legacy-{i}", "code": str(10000 + i),
             "audio": {"path": f"AUDIO/MP3/SONG/1/{i}.mp3"},
             "lyrics": {"path": f"AUDIO/MP3/LYRICS/1/{i}.json"},
             "sourceIdentity": {"sha256": "f" * 64,
                                "outputFormat": "original",
                                "canonicalPath": f"legacy/{i}",
                                "bytes": 1000}}
            for i in range(5000)
        ]
        stages = []
        real_check = export.record_is_complete

        def verify_only_new(root, record):
            if str(record.get("webSongId") or "").startswith("legacy-"):
                raise AssertionError("Unrelated old files must be checked only on duplicate match")
            return real_check(root, record)

        with (patch.object(export, "existing_records", return_value=old),
              patch.object(export, "record_is_complete", side_effect=verify_only_new)):
            result = pro.export_folder(
                str(self.source), str(self.dest), output_format="original",
                export=export, scanner=folder_upload,
                scan_progress=lambda *parts: stages.append(parts))
        self.assertEqual(result["created"], 1)
        self.assertEqual([stage for stage in stages if stage[0] == "catalog"],
                         [("catalog", 0, None), ("catalog", 5000, 5000)])

    def test_missing_old_audio_must_not_suppress_regeneration(self):
        self.assertEqual(self.run_export()["created"], 1)
        root = self.dest / "XStageSong"
        previous = export.existing_records(root)[0]
        export.safe_media_path(root, previous["audio"]["path"], "audio").unlink()
        result = self.run_export()
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["skipped"], 0)
        # SHA-based song identity is stable: the corrected row replaces the
        # dangling catalog reference instead of duplicating its song ID.
        repaired = export.existing_records(root)
        self.assertEqual(len(repaired), 1)
        self.assertTrue(export.record_is_complete(root, repaired[0]))
        self.assertNotEqual(repaired[0]["audio"]["path"], previous["audio"]["path"])

    def test_new_ready_resumes_legacy_catalog_without_decoding_old_lyrics(self):
        self.assertEqual(self.run_export()["created"], 1)
        library = self.dest / "XStageSong"
        # Legacy Ready builds have a valid Catalog, not the new review database.
        (library / "DB" / "json-pro-review.sqlite3").unlink()
        with patch.object(pro, "_document", side_effect=AssertionError(
                "an already published source must not be parsed again")):
            resumed = self.run_export()
        self.assertEqual((resumed["created"], resumed["skipped"], resumed["resumed"]), (0, 1, 1))
        self.assertEqual(len(export.existing_records(library)), 1)

    def test_review_errors_persist_and_retry_only_reprocesses_failed_source(self):
        source_stream = load("json_source_stream")
        midi = self.source / "03702.mid"
        midi.write_bytes(b"NOPE" + b"\\0" * 60)

        class Ncn:
            def kar_document(self, source, code):
                raise ValueError("ไฟล์ MIDI ไม่มีส่วนหัว MThd")

        initial = self.run_export(ncn=Ncn(), source_stream=source_stream.stream)
        self.assertEqual((initial["created"], initial["errors"]), (1, 1))
        review = load("json_pro_review")
        library = self.dest / "XStageSong"
        first = review.review(library, self.source, "original", status="error")
        self.assertEqual(first["total"], 1)
        self.assertEqual(first["items"][0]["name"], "03702.mid")
        self.assertIn("MThd", first["items"][0]["reason"])

        # Restarting a newer PC Ready keeps the successful song and defers the
        # unchanged failure instead of reprocessing all files.
        continued = self.run_export(ncn=Ncn(), source_stream=source_stream.stream)
        self.assertEqual((continued["created"], continued["resumed"],
                          continued["deferred"], continued["errors"]), (0, 1, 1, 0))
        self.assertEqual(len(export.existing_records(library)), 1)

        # Once a real timed companion is supplied, retry only the saved ERR.
        (self.source / "03702.lrc").write_text(
            "[00:02.00]ซ่อมข้อมูลแล้ว", encoding="utf-8")
        retried = self.run_export(source_stream=source_stream.stream,
                                  retry_errors_only=True)
        self.assertEqual((retried["created"], retried["errors"], retried["total"]), (1, 0, 1))
        self.assertEqual(len(export.existing_records(library)), 2)
        self.assertEqual(review.review(library, self.source, "original", status="error")["total"], 0)

    def test_invalid_lyrics_not_published(self):
        self.lrc.write_text("ไม่มีเวลา", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "ไม่พบเพลง"):
            self.run_export()
        self.assertFalse((self.dest / "XStageSong" / "current.json").exists())


if __name__ == "__main__":
    unittest.main()
