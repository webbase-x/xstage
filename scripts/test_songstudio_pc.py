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
                         "engine.py", "studio/index.html", "studio/app.js",
                         "studio/style.css", "studio/entry.js"]:
                self.assertIn("X-Stage-Song-Studio-PC-Source-Preview/" + name, files)
            self.assertTrue(z.testzip() is None)

if __name__ == "__main__":
    unittest.main(verbosity=2)
