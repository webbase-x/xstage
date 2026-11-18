"""Pre-X-Media preview tests: actual source, synchronized SQLite cues and Range."""
from __future__ import annotations

import http.client
import struct
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
import plus_core as core
import preview_player as preview
from test_plus import midi


class PreBuildPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.workspace=self.base/"workspace"
        self.source=self.base/"source"
        self.source.mkdir()
        core.init(self.workspace)

    def put(self,name,data):
        path=self.source/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data)
        return path

    def test_audio_preview_reads_original_and_timed_lyrics_without_x_copy(self):
        original=self.put("single.mp3",b"FAKE-MP3-STREAM"*200)
        self.put("single.lrc",b"[00:01.00]Hello\n[00:05.00]World\n")
        run=core.import_folder(self.workspace,self.source)
        self.assertEqual(run["files_new"],1)
        song=core.songs(self.workspace)[0]
        information=preview.preview_details(self.workspace,song["id"])
        self.assertEqual(information["mode"],"audio")
        self.assertEqual(information["timing_status"],"estimated")
        self.assertEqual(information["lines"][0]["text"],"Hello")
        self.assertEqual(information["lines"][0]["start"],1.0)
        self.assertTrue(information["lines"][0]["cues"])
        self.assertFalse((self.workspace/"SOURCE").exists())
        self.assertFalse(list(self.workspace.rglob("*.xmp3")))
        row,path=preview.source_info(self.workspace,song["id"])
        self.assertEqual(path,original)

    def test_midi_channel_voice_events_have_tempo_aligned_seconds(self):
        path=self.put("NCN/Song/0/00001.mid",midi())
        self.put("NCN/Lyrics/0/00001.lyr",
                 "ทดสอบ\nผู้ร้อง\nC\n\nNick\n".encode("cp874"))
        self.put("NCN/Cursor/0/00001.cur",struct.pack("<5H",0,1,2,3,4))
        core.import_folder(self.workspace,self.source)
        song=core.songs(self.workspace)[0]
        information=preview.preview_details(self.workspace,song["id"])
        self.assertEqual(information["mode"],"midi")
        self.assertAlmostEqual(information["duration"],20.0,places=1)
        events,duration=preview.iter_midi_messages(path)
        self.assertEqual(len(events),2)
        self.assertEqual(events[0][1]&0xFF,0x90)
        self.assertAlmostEqual(events[0][0],0)
        self.assertEqual(events[-1][1]&0xFF,0x80)
        self.assertAlmostEqual(events[-1][0],20.0,places=1)
        self.assertAlmostEqual(duration,20.0,places=1)

    def test_missing_original_is_not_claimed_playable(self):
        original=self.put("disconnected.mp3",b"audio"*200)
        core.import_folder(self.workspace,self.source)
        song=core.songs(self.workspace)[0]
        original.unlink()
        with self.assertRaisesRegex(ValueError,"ไม่พบไฟล์เพลงต้นฉบับ"):
            preview.preview_details(self.workspace,song["id"])

    def test_native_midi_on_non_windows_fails_explicitly(self):
        if sys.platform=="win32":self.skipTest("WinMM hardware availability requires manual test")
        self.put("solo.mid",midi())
        core.import_folder(self.workspace,self.source)
        song=core.songs(self.workspace)[0]
        with self.assertRaisesRegex(ValueError,"Windows MIDI Synthesizer"):
            preview.MidiPreview().play(self.workspace,song["id"])

    def test_http_range_reads_registered_audio_with_token_and_no_sidecar(self):
        raw=b"0123456789abcdefghijklmn"*100
        self.put("audio.mp3",raw)
        core.import_folder(self.workspace,self.source)
        song=core.songs(self.workspace)[0]
        state=app.State(self.workspace)
        handler=type("PreviewTestHandler",(app.Handler,),{"state":state})
        server=ThreadingHTTPServer(("127.0.0.1",0),handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True)
        worker.start()
        try:
            port=server.server_port
            def fetch(path,range_header=None):
                connection=http.client.HTTPConnection("127.0.0.1",port,timeout=5)
                headers={"Range":range_header} if range_header else {}
                connection.request("GET",path,headers=headers)
                response=connection.getresponse()
                status,headers,payload=response.status,response.getheaders(),response.read()
                connection.close()
                return status,dict(headers),payload
            media="/api/preview/media?song_id="+song["id"]+"&token="+state.token
            status,headers,data=fetch(media,"bytes=10-25")
            self.assertEqual(status,206)
            self.assertEqual(data,raw[10:26])
            self.assertEqual(headers["Content-Range"],"bytes 10-25/"+str(len(raw)))
            status,headers,data=fetch(media,"bytes=-7")
            self.assertEqual(status,206)
            self.assertEqual(data,raw[-7:])
            status,headers,data=fetch(media,"bytes=999999-")
            self.assertEqual(status,416)
            self.assertEqual(data,b"")
            status,headers,data=fetch("/api/preview/media?song_id="+song["id"])
            self.assertEqual(status,403)
            status,headers,data=fetch("/api/preview?song_id="+song["id"])
            self.assertEqual(status,200)
            self.assertIn(b'"mode": "audio"',data)
        finally:
            server.shutdown()
            worker.join(timeout=3)
            server.server_close()

    def test_preview_page_is_an_explicit_step_before_build_with_real_controls(self):
        root=Path(__file__).resolve().parents[1]
        html=(root/"web"/"index.html").read_text("utf-8")
        script=(root/"web"/"app.js").read_text("utf-8")
        css=(root/"web"/"style.css").read_text("utf-8")
        self.assertLess(html.index('data-view="preview"'),html.index('data-view="build"'))
        for anchor in ('id="preview-audio"','id="preview-video"','id="preview-seek"',
                       'id="preview-current-line"','id="preview-play"',
                       'id="preview-pass"','id="preview-fail"','id="preview-to-build"'):
            self.assertIn(anchor,html)
        self.assertIn("/api/preview/media",script)
        self.assertIn("/api/preview/midi/play",script)
        self.assertIn("/api/preview/review",script)
        self.assertIn("preview-glyph",css)


if __name__=="__main__":
    unittest.main()
