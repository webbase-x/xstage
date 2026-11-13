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

    def test_http_confirm_build_creates_media_and_reuses_it_for_lyrics(self):
        """Test exactly what both UI Create buttons send over Local Engine API."""
        import time
        from http.server import ThreadingHTTPServer
        original = self.source / "004210.m4a"
        original.write_bytes(b"valid-for-copy-regression" * 240)
        (self.source / "004210.lrc").write_text("[00:01.00]ทดสอบ", encoding="utf-8")
        engine.FILES[:] = [{
            "id": 1, "path": str(original), "title": "ทดลองสร้างเพลง",
            "artist": "ทดสอบ", "code": "004210", "kind": "M4A",
            "size": original.stat().st_size
        }]
        engine.FILE_BY_ID.clear()
        engine.FILE_BY_ID[1] = engine.FILES[0]
        engine.PREFS["mode"] = "original"
        engine.CANCEL.clear()
        server = ThreadingHTTPServer(("127.0.0.1", 0), engine.Handler)
        old_port = engine.PORT
        engine.PORT = server.server_port
        runner = threading.Thread(target=server.serve_forever, daemon=True)
        runner.start()
        def request(url, body):
            client = HTTPConnection("127.0.0.1", server.server_port, timeout=15)
            encoded = json.dumps(body).encode("utf-8")
            client.request("POST", url, encoded, headers={
                "Content-Type":"application/json", "X-XStage-Token": engine.TOKEN
            })
            response = client.getresponse()
            result = response.status, json.loads(response.read().decode("utf-8"))
            client.close()
            return result
        def finish():
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                snapshot = engine.job_snapshot()
                if snapshot["state"] != "running":
                    return snapshot
                time.sleep(.05)
            self.fail("PC job was acknowledged but Engine never finished")
        try:
            status, first = request("/api/jobs", {"action":"build",
                                  "ids":[1], "audio_only":True})
            self.assertEqual(status, 200)
            self.assertTrue(first.get("id"), "No build receipt")
            self.assertEqual(first.get("total"), 1)
            done = finish()
            self.assertEqual(done["state"], "success", done.get("detail"))
            self.assertEqual((done["created"], done["m4aCount"]), (1, 1))
            audio = self.dest / "StageWeb/audio/0/004210.m4a"
            self.assertEqual(audio.read_bytes(), original.read_bytes())
            status, second = request("/api/jobs", {"action":"build",
                                   "ids":[1], "audio_only":False})
            self.assertEqual(status, 200)
            self.assertNotEqual(first["id"], second["id"])
            done = finish()
            self.assertEqual(done["state"], "success", done.get("detail"))
            self.assertEqual((done["created"], done["skipped"], done["lyricsCount"]), (0, 1, 1))
            self.assertTrue((self.dest / "StageWeb/lyrics/0/004210.json").is_file())
            self.assertEqual(len(list((self.dest / "StageWeb/audio").rglob("*.m4a"))), 1)
        finally:
            server.shutdown()
            server.server_close()
            runner.join(timeout=3)
            engine.PORT = old_port

    def test_estimate_93597_selected_tracks_does_not_require_three_times_all_sources(self):
        """Bulk selection is ~600 KB JSON, below the 1 MiB Local API limit."""
        import time
        from http.server import ThreadingHTTPServer
        sample = self.source / "test.m4a"
        sample.write_bytes(b"M4A-test" * 512)
        row = {"path":str(sample), "size":sample.stat().st_size,
               "code":"test", "kind":"M4A", "title":"test"}
        ids = list(range(1, 93598))
        engine.FILE_BY_ID.clear()
        engine.FILE_BY_ID.update({i: row for i in ids})
        server = ThreadingHTTPServer(("127.0.0.1", 0), engine.Handler)
        old_port = engine.PORT
        engine.PORT = server.server_port
        runner = threading.Thread(target=server.serve_forever, daemon=True)
        runner.start()
        try:
            raw = json.dumps({"ids":ids},separators=(",",":")).encode("utf-8")
            self.assertLess(len(raw), 1_048_576)
            client = HTTPConnection("127.0.0.1",server.server_port,timeout=30)
            client.request("POST","/api/estimate",raw,headers={
                "Content-Type":"application/json","X-XStage-Token":engine.TOKEN
            })
            response = client.getresponse()
            result = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status,200,result)
            self.assertEqual(result["StageWeb"],93597)
            self.assertTrue(result["warning"])
            self.assertIn("freeBytes",result)
            self.assertIn("estimatedOutputBytes",result)
            client.close()
        finally:
            server.shutdown()
            server.server_close()
            runner.join(timeout=3)
            engine.PORT = old_port

    def test_all_ncn_selected_rejected_before_build_job(self):
        source = self.source / "test.ncn"
        source.write_bytes(b"unsupported-NCN")
        row = {"id": 1, "path": str(source), "code": "test", "title": "NCN"}
        engine.FILE_BY_ID[1] = row
        with self.assertRaisesRegex(ValueError, "NCN ทั้งหมด"):
            engine.validate_build_request({"ids": [1], "audio_only": False})
        self.assertFalse((self.dest / "StageWeb").exists())

    def test_supported_format_preflight_counts_and_rejects_missing(self):
        source = self.source / "test.m4a"
        source.write_bytes(b"m4a-test")
        engine.FILE_BY_ID[1] = {"id": 1, "path": str(source), "code": "test", "title": "Test"}
        result = engine.validate_build_request({"ids": [1], "audio_only": True})
        self.assertEqual(result["supported"], 1)
        self.assertEqual(result["formats"], {".m4a": 1})

    def test_build_does_not_duplicate_source_between_independent_runs(self):
        audio = self.source / "001234.m4a"
        audio.write_bytes(b"A" * 4096)
        (self.source / "001234.lrc").write_text(
            "[00:01.00]สวัสดีทดสอบ", encoding="utf-8")
        original = {"id": 1, "path": str(audio), "title": "ทดสอบเพลง",
                    "code": "001234", "kind": "M4A"}
        engine.CANCEL.clear()
        first = engine.build_library([original], "original", {"audio_only": False})
        root = self.dest / "StageWeb"
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
        audio_dir = self.dest / "StageWeb" / "audio" / "0"
        self.assertEqual(sorted(file.name for file in audio_dir.glob("*.m4a")),
                         ["001234.m4a", "001235.m4a"])
        records = engine._song_export_module().existing_records(self.dest / "StageWeb")
        self.assertEqual({r["code"] for r in records}, {"001234", "001235"})
        self.assertEqual({r["originalCode"] for r in records}, {"001234"})
        repeat = engine.build_library(originals, "original", {"audio_only": False})
        self.assertEqual((repeat["created"], repeat["skipped"]), (0, 2))

    def test_existing_legacy_preview_output_is_not_built_again(self):
        audio = self.source / "007007.m4a"
        audio.write_bytes(b"E" * 4096)
        legacy = self.dest / "song" / "Old Song.m4a"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_bytes(b"OLD" * 4096)
        engine.CANCEL.clear()
        with self.assertRaisesRegex(RuntimeError, "ไม่มีเพลงที่สร้างสำเร็จ"):
            engine.build_library(
                [{"path": str(audio), "code": "007007", "title": "Old Song"}],
                "original", {"audio_only": False})
        # Unverified legacy output must not be counted as a successful skip.
        self.assertEqual(legacy.read_bytes(), b"OLD" * 4096)
        self.assertFalse((self.dest / "StageWeb" / "audio" / "0" / "007007.m4a").exists())

    def test_scan_ignores_previous_song_studio_output_inside_source_tree(self):
        # Source can be the workspace's parent; generated audio must not be
        # mistaken for new originals on the next scan.
        engine.PREFS["source"] = str(self.dir)
        audio = self.dir / "originals" / "000001.m4a"
        audio.parent.mkdir(parents=True)
        audio.write_bytes(b"F" * 4096)
        generated = self.dest / "StageWeb" / "audio" / "0" / "000001.m4a"
        generated.parent.mkdir(parents=True)
        generated.write_bytes(audio.read_bytes())
        self.assertEqual(engine.scan_source(), 1)
        self.assertEqual(Path(engine.FILES[0]["path"]), audio)

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
        root = self.dest / "StageWeb"
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
        target = self.dest / "StageWeb" / "audio" / "0" / original.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"OLD" * 4096)
        with self.assertRaisesRegex(RuntimeError, "ERR 1"):
            engine.build_library(
                [{"path": str(original), "code": "000888", "title": "Unindexed"}],
                "original", {"audio_only": False})
        self.assertEqual(target.read_bytes(), b"OLD" * 4096)
        self.assertFalse((target.parent / "000888 (2).m4a").exists())

    def test_audio_only_then_add_lyrics_keeps_existing_m4a(self):
        source = self.source / "021999.m4a"
        source.write_bytes(b"F" * 8000)
        (self.source / "021999.lrc").write_text("[00:01.00]เพลงทดสอบ", encoding="utf-8")
        row = {"path": str(source), "title": "เพลงทดสอบ", "code": "021999"}
        engine.CANCEL.clear()
        first = engine.build_library([row], "original", {"audio_only": True})
        self.assertEqual((first["created"], first["lyricsCount"]), (1, 0))
        audio = self.dest / "StageWeb/audio/0/021999.m4a"
        old_data = audio.read_bytes()
        second = engine.build_library([row], "original", {"audio_only": False})
        self.assertEqual((second["created"], second["skipped"], second["lyricsCount"]), (0, 1, 1))
        self.assertEqual(audio.read_bytes(), old_data)
        self.assertTrue((self.dest / "StageWeb/lyrics/0/021999.json").is_file())
        third = engine.build_library([row], "original", {"audio_only": False})
        self.assertEqual((third["created"], third["skipped"], third["lyricsCount"]), (0, 1, 0))
        self.assertEqual(len(list((self.dest / "StageWeb/audio").rglob("*.m4a"))), 1)

    def test_live_controls_update_gains_soundfont_and_midi_preset(self):
        spec = importlib.util.spec_from_file_location("songstudio_live_test",
            REPO / "songstudio-pc" / "live_preview.py")
        live = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(live)
        sf = self.dir / "test.sf2"
        sf.write_bytes(b"mock-sf")
        state = live.LiveControls(.8, .8, sf)
        assert state.snapshot()[0] == .8
        response = state.update(music_volume=1.0, synth_volume=0.0,
                                preset="bright", soundfont=str(sf))
        self.assertEqual(response, (1.0, 0.0, sf, "bright"))
        with self.assertRaisesRegex(ValueError, "0 ถึง 100"):
            state.update(music_volume=9)
        from array import array
        original = array("h", [1000, -1000, 2000, -2000]).tobytes()
        soundfont_pcm = array("h", [8000, 8000, 8000, 8000]).tobytes()
        self.assertEqual(live.blend_pcm(original, soundfont_pcm, 1, 0), original)
        self.assertEqual(live.blend_pcm(original, soundfont_pcm, 0, 1), soundfont_pcm)

    def test_app_oauth_client_is_public_and_persistent_for_other_users(self):
        spec = importlib.util.spec_from_file_location("xstage_google_public",
                 REPO / "songstudio-pc" / "google_drive.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        original = self.dir / "developer-client.json"
        original.write_text(json.dumps({"installed": {
            "client_id": "123456-correctdesktopid.apps.googleusercontent.com",
            "client_secret": "desktop-public-secret-from-google"
        }}), encoding="utf-8")
        data = self.dir / "WindowsUser" / "X-Stage" / "SongStudio"
        target = data / "oauth-client.json"
        drive = mod.GoogleDrive(data, lambda: str(target))
        self.assertFalse(drive.status()["configured"])
        saved = drive.import_client(original)
        self.assertEqual(saved, str(target))
        self.assertTrue(drive.status()["configured"])
        self.assertFalse(drive.status()["connected"])
        public = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(public["installed"]["client_id"],
                         "123456-correctdesktopid.apps.googleusercontent.com")
        self.assertEqual(public["installed"]["client_secret"],
                         "desktop-public-secret-from-google")
        self.assertNotIn("refresh_token", target.read_text(encoding="utf-8"))
        original.unlink()
        reloaded = mod.GoogleDrive(data, lambda: str(target))
        self.assertTrue(reloaded.status()["configured"])
        self.assertFalse(reloaded.status()["connected"])
        # A second Windows account has no token or private override by default.
        other = mod.GoogleDrive(self.dir / "OtherWindowsUser", lambda: "")
        self.assertFalse(other.status()["configured"])
        self.assertFalse(other.status()["connected"])

    def test_incomplete_legacy_desktop_oauth_client_fails_before_google_login(self):
        spec = importlib.util.spec_from_file_location("xstage_google_legacy",
             REPO / "songstudio-pc" / "google_drive.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        legacy = self.dir / "old-oauth-client.json"
        legacy.write_text(json.dumps({"installed":{
            "client_id": "12345-legacy.apps.googleusercontent.com"
        }}), encoding="utf-8")
        service = mod.GoogleDrive(self.dir / "fresh-user", lambda: str(legacy))
        status = service.status()
        self.assertFalse(status["configured"])
        self.assertIn("client_secret", status["error"])
        with self.assertRaisesRegex(mod.GoogleError, "client_secret"):
            service.login()
        with self.assertRaisesRegex(mod.GoogleError, "client_secret"):
            service.import_client(legacy)

    def test_windows_data_is_outside_portable_release(self):
        if os.name == "nt":
            self.assertNotEqual(engine.DATA, REPO / "songstudio-pc" / "data")
            self.assertEqual(engine.DATA.parts[-2:], ("X-Stage", "SongStudio"))
        self.assertTrue(engine.DATA.is_dir())

    def test_google_oauth_desktop_loopback_and_dpapi_storage_mock(self):
        # Simulate the Google browser callback + token endpoint, without a
        # network or actual account. Real authorization requires user consent.
        import urllib.parse
        import urllib.request
        import time
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location("xstage_google_test",
             REPO / "songstudio-pc" / "google_drive.py")
        google = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(google)
        client_path = self.dir / "oauth.json"
        client_path.write_text(json.dumps({"installed":{
            "client_id":"demo-test.apps.googleusercontent.com",
            "client_secret":"local-client-secret"
        }}), encoding="utf-8")
        drive = google.GoogleDrive(self.dir, lambda: str(client_path))
        browser_threads = []
        posted = []
        def exchange(form):
            posted.append(dict(form))
            if form["grant_type"] == "authorization_code":
                return {"access_token":"test-access",
                        "refresh_token":"test-refresh","expires_in":3600}
            return {"access_token":"refreshed-access","expires_in":3600}
        def open_callback(url, new=1):
            parsed = urllib.parse.urlsplit(url)
            params = urllib.parse.parse_qs(parsed.query)
            self.assertEqual(params["code_challenge_method"], ["S256"])
            self.assertIn("drive.file", params["scope"][0])
            target = params["redirect_uri"][0] + "?" + urllib.parse.urlencode({
                "state":params["state"][0], "code":"one-time-test-code"
            })
            def callback():
                time.sleep(.1)
                with urllib.request.urlopen(target, timeout=5) as response:
                    self.assertEqual(response.status, 200)
            thread = threading.Thread(target=callback)
            thread.start()
            browser_threads.append(thread)
            return True
        with patch.object(google, "_crypt", side_effect=lambda x, decrypt: x), \
             patch.object(google.webbrowser, "open", side_effect=open_callback), \
             patch.object(drive, "_token_exchange", side_effect=exchange), \
             patch.object(drive, "api", return_value={"user":{"emailAddress":"tester@example.com"}}):
            info = drive.login()
            self.assertTrue(info["connected"])
            self.assertEqual(info["email"], "tester@example.com")
            self.assertEqual(drive.pending_auth_url, "")
            self.assertIsNone(drive.pending_auth_stop)
            self.assertTrue(drive.secret_file.is_file())
            self.assertEqual(posted[0]["client_secret"], "local-client-secret")
            self.assertIn("code_verifier", posted[0])
            drive.access_expires = 0
            self.assertEqual(drive.token(), "refreshed-access")
            self.assertEqual(posted[1]["grant_type"], "refresh_token")
            self.assertEqual(posted[1]["client_secret"], "local-client-secret")
            drive.logout()
            self.assertFalse(drive.status()["connected"])
        for thread in browser_threads:
            thread.join(timeout=5)

    def test_google_login_reopens_same_pending_browser_without_new_auth_session(self):
        """Retry must raise existing Google page, not create another OAuth state."""
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location(
            "xstage_google_browser", REPO / "songstudio-pc" / "google_drive.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        service = mod.GoogleDrive(self.dir / "browser-window", lambda: "")
        url = "https://accounts.google.com/o/oauth2/v2/auth?state=pending-test"
        service.pending_auth_url = url
        service.pending_auth_stop = threading.Event()
        with patch.object(mod.webbrowser, "open", return_value=True) as opened:
            result = service.show_pending_login()
            self.assertTrue(result["ok"])
            opened.assert_called_once_with(url, new=1)
        service.pending_auth_stop.set()
        with self.assertRaisesRegex(mod.GoogleError, "ยังไม่มีหน้า Google Login"):
            service.show_pending_login()
        service.pending_auth_url = ""
        service.pending_auth_stop = None
        with self.assertRaisesRegex(mod.GoogleError, "ยังไม่มีหน้า Google Login"):
            service.show_pending_login()

    def test_google_login_rejects_missing_client_before_creating_job(self):
        # Browser sign-in to X-Stage Online is not Desktop OAuth for Song Studio.
        with patch.object(engine.GOOGLE, "status", return_value={
                    "configured": False, "connected": False,
                    "error": "ไม่พบ Google Desktop OAuth Client JSON"}):
            with self.assertRaisesRegex(ValueError, "Google Desktop OAuth Client JSON"):
                engine.start_job({"action": "login"})
        self.assertNotEqual(engine.JOB["state"], "running")

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
                         "engine.py", "google_drive.py", "song_export.py", "ai_separate.py", "ai-model.lock.json", "live_preview.py", "studio/index.html", "studio/app.js",
                         "studio/style.css", "studio/entry.js", "studio/app-icon.svg", "studio/site.webmanifest"]:
                self.assertIn("X-Stage-Song-Studio-PC-Source-Preview/" + name, files)
            self.assertTrue(z.testzip() is None)

if __name__ == "__main__":
    unittest.main(verbosity=2)
