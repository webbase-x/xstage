"""Offline regression: release metadata validation, SHA download and no self-install."""
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

file = Path(__file__).resolve().parents[1] / "songstudio-pc" / "pc_ready_updates.py"
spec = importlib.util.spec_from_file_location("updates", file)
updates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updates)


class Response:
    status = 200
    headers = {}
    def __init__(self, content, url="https://github.com/webbase-x/xstage"):
        self.content = io.BytesIO(content)
        self.url = url
    def read(self, count=-1): return self.content.read(count)
    def geturl(self): return self.url
    def __enter__(self): return self
    def __exit__(self, *_): return False


def metadata(archive=b"zip-bytes"):
    name = "X-Stage-Song-Studio-PC-Ready-v0.3.43-build343.zip"
    return dict(channel="pc-ready", platform="windows-x64",
                package_type="portable_zip", available=True,
                version="0.3.43", build=343, archive_file=name,
                sha256=hashlib.sha256(archive).hexdigest(),
                download_url=updates.RELEASE_PREFIX +
                "song-studio-pc-ready-v0.3.43-build343/" + name)


class UpdateTests(unittest.TestCase):
    def test_metadata_and_version(self):
        good=metadata()
        with patch.object(updates.urllib.request, "urlopen",
                          return_value=Response(json.dumps(good).encode())):
            self.assertTrue(updates.check("0.3.42", "342")["update"])
            self.assertFalse(updates.check("0.3.43", "343")["update"])
        for edit in ({"download_url":"https://attacker.invalid/zip"},
                     {"version":"9.9.9"}, {"channel":"online"}):
            bad={**good,**edit}
            with patch.object(updates.urllib.request, "urlopen",
                              return_value=Response(json.dumps(bad).encode())):
                with self.assertRaises(ValueError): updates._metadata()

    def test_verified_download_and_reuse(self):
        body=b"zip-bytes"
        doc=metadata(body)
        calls=[]
        def respond(req,**_):
            calls.append(req.full_url)
            return (Response(json.dumps(doc).encode()) if req.full_url==updates.METADATA_URL
                    else Response(body, doc["download_url"]))
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(updates.urllib.request, "urlopen", side_effect=respond):
                first=updates.download(folder, "0.3.42", "342")
                second=updates.download(folder, "0.3.42", "342")
                self.assertEqual(first["path"], second["path"])
                self.assertEqual(Path(first["path"]).read_bytes(),body)
                self.assertEqual(calls.count(doc["download_url"]),1)

    def test_tamper_fails_without_writing_final_zip(self):
        doc=metadata(b"real-package")
        def respond(req,**_):
            return (Response(json.dumps(doc).encode()) if req.full_url==updates.METADATA_URL
                    else Response(b"tampered",doc["download_url"]))
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(updates.urllib.request,"urlopen",side_effect=respond):
                with self.assertRaisesRegex(ValueError,"SHA-256"):
                    updates.download(folder,"0.3.42","342")
            self.assertEqual(list(Path(folder).iterdir()),[])


if __name__=="__main__": unittest.main()
