"""Direct HTTPS song acquisition and single-file import integration tests."""
from __future__ import annotations

import hashlib
import io
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import plus_core as core
import song_download as download


class Response(io.BytesIO):
    def __init__(self,body,url,ctype="audio/mpeg",length=None):
        super().__init__(body)
        self.url=url
        self.headers={
            "Content-Type":ctype,
            "Content-Length":str(len(body) if length is None else length),
        }

    def geturl(self):
        return self.url


class Opener:
    def __init__(self,body,url,ctype="audio/mpeg",length=None):
        self.body,self.url,self.ctype,self.length=body,url,ctype,length
        self.calls=0

    def open(self,req,timeout=0):
        self.calls+=1
        return Response(self.body,self.url,self.ctype,self.length)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.workspace=self.root/"Song Studio งานเพลง"
        self.dest=self.root/"External Downloads"
        self.url="https://cdn.example.org/music/sample.mp3"
        core.init(self.workspace)
        self.dns=patch.object(download.socket,"getaddrinfo",
            return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,"",
                           ("93.184.216.34",443))])
        self.dns.start()

    def tearDown(self):
        self.dns.stop()
        self.temp.cleanup()

    def test_public_https_file_is_downloaded_and_indexed_exactly_once(self):
        raw=b"ID3"+b"OWNER-APPROVED-SONG"*600
        opening=Opener(raw,self.url)
        events=[]
        first=download.download_and_import(
            self.workspace,self.url,lambda summary,message:events.append(summary),
            destination=self.dest,opener=opening)
        self.assertEqual(opening.calls,1)
        self.assertEqual(first["sha256"],hashlib.sha256(raw).hexdigest())
        self.assertEqual(Path(first["download_path"]).read_bytes(),raw)
        self.assertEqual(first["import"]["files_new"],1)
        self.assertTrue(events)
        self.assertEqual(core.stats(self.workspace)["songs"],1)
        second=download.download_and_import(
            self.workspace,self.url,destination=self.dest,opener=Opener(raw,self.url))
        self.assertEqual(second["import"]["files_new"],0)
        self.assertGreaterEqual(second["import"]["media_duplicates"],1)
        self.assertEqual(core.stats(self.workspace)["songs"],1)
        self.assertEqual(len(list(self.dest.rglob("*.part"))),0)

    def test_single_file_import_does_not_scan_neighbor_file(self):
        folder=self.root/"source songs"
        folder.mkdir()
        one=folder/"one.mp3"
        other=folder/"other.mp3"
        one.write_bytes(b"AUDIO-ONE"*800)
        other.write_bytes(b"AUDIO-TWO"*800)
        first=core.import_folder(self.workspace,folder,selected_file=str(one))
        self.assertEqual(first["files_new"],1)
        self.assertEqual(core.stats(self.workspace)["songs"],1)
        second=core.import_folder(self.workspace,folder,selected_file=str(other))
        self.assertEqual(second["files_new"],1)
        self.assertEqual(core.stats(self.workspace)["songs"],2)
        again=core.import_folder(self.workspace,folder,selected_file=str(one))
        self.assertEqual(again["files_new"],0)
        with self.assertRaisesRegex(ValueError,"ไฟล์เพลงไม่อยู่ในโฟลเดอร์"):
            core.import_folder(self.workspace,folder,selected_file=str(self.root/"outside.mp3"))

    def test_local_private_or_insecure_urls_fail_before_any_download(self):
        for url in [
            "http://cdn.example.org/x.mid",
            "file:///C:/password.mid",
            "https://127.0.0.1/private.mid",
            "https://localhost/private.mid",
            "https://user:password@cdn.example.org/x.mid",
            "https://cdn.example.org:8443/x.mid",
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                download.validate_remote_url(url)
        with patch.object(download.socket,"getaddrinfo",
                return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,"",
                               ("192.168.1.10",443))]):
            with self.assertRaisesRegex(ValueError,"เครือข่ายภายใน"):
                download.validate_remote_url(self.url)

    def test_html_response_and_bad_content_length_never_import(self):
        with self.assertRaisesRegex(ValueError,"หน้าเว็บหรือ JSON"):
            download.download_and_import(self.workspace,self.url,
                destination=self.dest,
                opener=Opener(b"<html>Not a song</html>",self.url,ctype="text/html"))
        with self.assertRaisesRegex(ValueError,"ดาวน์โหลดไฟล์ไม่ครบ"):
            download.download_and_import(self.workspace,self.url,
                destination=self.dest,
                opener=Opener(b"ID3",self.url,length=500))
        self.assertEqual(core.stats(self.workspace)["songs"],0)
        self.assertEqual(list(self.dest.rglob("*.part")),[])

    def test_cancellation_removes_partial_file_and_leaves_sqlite_untouched(self):
        from threading import Event
        signal=Event()
        signal.set()
        with self.assertRaisesRegex(RuntimeError,"ยกเลิก"):
            download.download_and_import(
                self.workspace,self.url,cancel=signal,
                destination=self.dest,opener=Opener(b"ID3"*1200,self.url))
        self.assertEqual(core.stats(self.workspace)["songs"],0)
        self.assertEqual(list(self.dest.rglob("*.part")),[])

    def test_unsupported_suffix_and_redirect_to_private_host_are_denied(self):
        with self.assertRaisesRegex(ValueError,"ลงท้าย"):
            download.safe_filename("https://cdn.example.org/view")
        handler=download.PublicHttpsRedirect()
        with self.assertRaises(ValueError):
            handler.redirect_request(
                object(),None,302,"Found",{},
                "https://127.0.0.1/music/secret.mid")


if __name__=="__main__":
    unittest.main()
