"""Smoke tests for the source-only local Song Studio engine, no Windows runtime needed."""
from __future__ import annotations
import importlib.util
import json
import os
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from http.client import HTTPConnection
from pathlib import Path
from zipfile import ZipFile

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("songstudio_pc_engine", REPO / "songstudio-pc" / "engine.py")
engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(engine)

class PcSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.source = self.dir / "music"
        self.source.mkdir()
        self.dest = self.dir / "exports"
        self.dest.mkdir()
        engine.PREFS["source"] = str(self.source)
        engine.PREFS["workspace"] = str(self.dest)
        engine.FILES.clear()
        engine.FILE_BY_ID.clear()
        engine.NOTES.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def test_scan_and_lyrics_and_safe_naming(self):
        (self.source / "ทดสอบ.mp3").write_bytes(b"ID3-test")
        (self.source / "ทดสอบ.lrc").write_text("[00:01.00]สวัสดี", encoding="utf-8")
        (self.source / "not-song.txt").write_text("hello", encoding="utf-8")
        self.assertEqual(engine.scan_source(), 1)
        row = engine.FILES[0]
        self.assertEqual(row["title"], "ทดสอบ")
        self.assertIn("สวัสดี", engine.lyrics_text(row))
        self.assertEqual(engine.safe_stem('TEST<>:"'), "TEST____")
        first = engine.unique_target(self.dest, "song", ".m4a")
        first.write_bytes(b"old")
        second = engine.unique_target(self.dest, "song", ".m4a")
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), b"old")

    def test_build_does_not_duplicate_source_between_independent_runs(self):
        audio = self.source / "001234.m4a"
        audio.write_bytes(b"A" * 4096)
        (self.source / "001234.lrc").write_text(
            "[00:01.00]สวัสดีทดสอบ", encoding="utf-8")
        original = {"id": 1, "path": str(audio), "title": "ทดสอบเพลง",
                    "code": "001234", "kind": "M4A"}
        engine.CANCEL.clear()
        first = engine.build_library([original], "original", {"audio_only": False})
        root = self.dest / "songs"
        self.assertEqual(first["created"], 1)
        self.assertEqual(first["skipped"], 0)
        self.assertTrue((root / "audio/0/001234.m4a").is_file())
        self.assertTrue((root / "lyrics/0/001234.json").is_file())
        self.assertTrue((root / "current.json").is_file())
        before_audio = sorted(str(x) for x in root.rglob("*.m4a"))
        before_lyrics = sorted(str(x) for x in root.rglob("*.json"))
        pointer_before = (root / "current.json").read_text(encoding="utf-8")

        # The source, memory and selection may be reloaded on another day.
        second = engine.build_library([original], "original", {"audio_only": False})
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(second["errors"], 0)
        self.assertEqual(sorted(str(x) for x in root.rglob("*.m4a")), before_audio)
        self.assertEqual(sorted(str(x) for x in root.rglob("*.json")), before_lyrics)
        self.assertEqual((root / "current.json").read_text(encoding="utf-8"), pointer_before)

        # The very same audio may be renamed/copied to another folder.
        moved = self.source / "copy"
        moved.mkdir()
        copied = moved / "998877.m4a"
        copied.write_bytes(audio.read_bytes())
        renamed = {**original, "path": str(copied), "code": "998877"}
        third = engine.build_library([renamed], "original", {"audio_only": False})
        self.assertEqual((third["created"], third["skipped"]), (0, 1))
        self.assertEqual(sorted(str(x) for x in root.rglob("*.m4a")), before_audio)

    def test_build_distinct_source_same_name_keeps_both_without_overwriting(self):
        audio = self.source / "001234.m4a"
        audio.write_bytes(b"A" * 4096)
        second_folder = self.source / "other"
        second_folder.mkdir()
        another = second_folder / "001234.m4a"
        another.write_bytes(b"B" * 4096)
        originals = [
            {"path": str(audio), "code": "001234", "title": "First"},
            {"path": str(another), "code": "001234", "title": "Second"}
        ]
        engine.CANCEL.clear()
        result = engine.build_library(originals, "original", {"audio_only": False})
        self.assertEqual(result["created"], 2)
        audio_dir = self.dest / "songs" / "audio" / "0"
        self.assertEqual(sorted(file.name for file in audio_dir.glob("*.m4a")),
                         ["001234 (2).m4a", "001234.m4a"])
        repeat = engine.build_library(originals, "original", {"audio_only": False})
        self.assertEqual((repeat["created"], repeat["skipped"]), (0, 2))

    def test_stop_and_restart_reuses_durable_journal_without_reencoding(self):
        # Simulate power loss after audio+lyric are written and the fsynced
        # journal is saved, but before catalogs/current.json were switched.
        from importlib.util import spec_from_file_location, module_from_spec
        export_spec = spec_from_file_location("songstudio_export_test",
                                              REPO / "songstudio-pc" / "song_export.py")
        export = module_from_spec(export_spec)
        export_spec.loader.exec_module(export)
        audio = self.source / "000777.m4a"
        audio.write_bytes(b"Q" * 4096)
        root = self.dest / "songs"
        target = root / "audio/0/000777.m4a"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(audio.read_bytes())
        record = export.make_record(
            root, {"path": str(audio), "code": "000777", "title": "Recover"},
            target, None, None, "original")
        record["sourceIdentity"] = export.source_marker(audio, export.source_sha256(audio))
        export.append_journal(root, record)
        self.assertFalse((root / "current.json").exists())

        engine.CANCEL.clear()
        result = engine.build_library(
            [{"path": str(audio), "code": "000777", "title": "Recover"}],
            "original", {"audio_only": False})
        self.assertEqual((result["created"], result["skipped"]), (0, 1))
        self.assertEqual(len(list(root.rglob("*.m4a"))), 1)
        self.assertTrue((root / "current.json").is_file())
        self.assertFalse((root / export.JOURNAL_NAME).exists())

    def test_preexisting_unindexed_file_is_not_duplicated(self):
        original = self.source / "000888.m4a"
        original.write_bytes(b"D" * 4096)
        target = self.dest / "songs" / "audio" / "0" / original.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"OLD" * 4096)
        with self.assertRaisesRegex(RuntimeError, "ERR 1"):
            engine.build_library(
                [{"path": str(original), "code": "000888", "title": "Unindexed"}],
                "original", {"audio_only": False})
        self.assertEqual(target.read_bytes(), b"OLD" * 4096)
        self.assertFalse((target.parent / "000888 (2).m4a").exists())

    def test_windows_picker_returns_thai_unicode_path_and_reports_errors(self):
        # Mock Windows subprocess so this test also runs on Linux CI without GUI.
        import base64
        path = r"C:\เพลงไทย\ต้นฉบับ"
        payload = b"PICKED:" + base64.b64encode(path.encode("utf-8")) + b"\r\n"
        result = SimpleNamespace(stdout=payload, stderr=b"", returncode=0)
        process = SimpleNamespace(
            PIPE=-1, DEVNULL=-3, CREATE_NO_WINDOW=0x08000000,
            run=Mock(return_value=result)
        )
        with patch.object(engine, "os", SimpleNamespace(name="nt")), \
             patch.object(engine, "subprocess", process):
            self.assertEqual(engine.open_picker("source"), path)
            self.assertEqual(process.run.call_args.args[0][-4:],
                             ["-Kind", "source", "-InitialPath", str(self.source)])
            process.run.return_value = SimpleNamespace(
                stdout=b"CANCELLED\n", stderr=b"", returncode=0
            )
            self.assertEqual(engine.open_picker("workspace"), "")
            process.run.return_value = SimpleNamespace(
                stdout=b"", stderr=b"PowerShell picker failure", returncode=1
            )
            with self.assertRaisesRegex(RuntimeError, "PowerShell picker failure"):
                engine.open_picker("source")

    def test_local_http_only_and_auth(self):
        from http.server import ThreadingHTTPServer
        server = ThreadingHTTPServer(("127.0.0.1", 0), engine.Handler)
        engine.PORT = server.server_port
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def get(path, headers):
                conn = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                try:
                    conn.request("GET", path, headers=headers)
                    res = conn.getresponse()
                    return res.status, res.read()
                finally:
                    conn.close()
            host = f"127.0.0.1:{server.server_port}"
            no_token = {"Host": host}
            self.assertEqual(get("/api/status", no_token)[0], 403)
            self.assertEqual(get("/api/status", {"Host": "fake.malicious.example", "X-XStage-Token": engine.TOKEN})[0], 403)
            self.assertEqual(get("/api/status", {"Host": host, "Origin":"https://evil.example",
                                                  "X-XStage-Token": engine.TOKEN})[0], 403)
            code, content = get("/api/status", {"Host": host, "X-XStage-Token": engine.TOKEN})
            self.assertEqual(code, 200)
            state = json.loads(content)
            self.assertEqual(state["build"], "205-SRC")
            self.assertFalse(state["google"]["connected"])
            code, content = get("/", no_token)
            self.assertEqual(code, 200)
            self.assertIn(b"Song Studio", content)
            code, icon = get("/app-icon.svg", no_token)
            self.assertEqual(code, 200)
            self.assertIn(b"<svg", icon)
            code, manifest = get("/site.webmanifest", no_token)
            self.assertEqual(code, 200)
            self.assertEqual(json.loads(manifest)["short_name"], "X-Stage Studio")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_packaged_tree(self):
        from importlib.machinery import SourceFileLoader
        import importlib.util
        spec = importlib.util.spec_from_file_location("songstudio_packaging",
                                                      REPO / "scripts" / "package-song-studio-pc.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        target = module.package()
        with ZipFile(target) as z:
            files = set(z.namelist())
            for name in ["Start-Song-Studio.cmd", "Start-Song-Studio.ps1", "pick_path.ps1",
                         "engine.py", "song_export.py", "ai_separate.py", "ai-model.lock.json", "live_preview.py", "studio/index.html", "studio/app.js",
                         "studio/style.css", "studio/entry.js", "studio/app-icon.svg", "studio/site.webmanifest"]:
                self.assertIn("X-Stage-Song-Studio-PC-Source-Preview/" + name, files)
            self.assertTrue(z.testzip() is None)

if __name__ == "__main__":
    unittest.main(verbosity=2)
