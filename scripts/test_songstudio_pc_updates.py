"""Offline regression: verified Ready downloads and safe side-by-side installation."""
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
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
                          side_effect=lambda *_args, **_kwargs:
                              Response(json.dumps(good).encode())):
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


    @staticmethod
    def _ready_zip(root_name, *, unsafe=False):
        archive = io.BytesIO()
        content = {name: (b"ready-component:" + name.encode("utf-8"))
                   for name in updates.MANDATORY if name != ".engine-ready-manifest.json"}
        manifest = {
            "version": "0.3.43", "build": 343,
            "bundle_type": "ready-offline", "platform": "windows-x64",
            "files": [{"path": name,
                       "sha256": hashlib.sha256(value).hexdigest()}
                      for name, value in content.items()]
        }
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            for name, value in content.items():
                z.writestr(root_name + "/" + name, value)
            z.writestr(root_name + "/.engine-ready-manifest.json",
                       json.dumps(manifest).encode())
            if unsafe:
                z.writestr(root_name + "/../outside.txt", b"malicious")
        return archive.getvalue()

    def test_install_verified_ready_side_by_side_without_launch(self):
        name = metadata()["archive_file"]
        root_name = Path(name).stem
        data = self._ready_zip(root_name)
        doc = metadata(data)
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            current = parent / "running-build342"
            current.mkdir()
            (current / ".engine-ready-manifest.json").write_text("{}")
            archive = parent / name
            archive.write_bytes(data)
            with patch.object(updates, "_metadata", return_value=doc):
                result = updates.install(archive, current, launch=False)
                target = Path(result["path"])
                self.assertTrue(target.is_dir())
                self.assertEqual(target.name, root_name)
                self.assertTrue((target / "studio" / "app.js").is_file())
                self.assertTrue((current / ".engine-ready-manifest.json").is_file())
                with self.assertRaises(FileExistsError):
                    updates.install(archive, current, launch=False)

    def test_install_rejects_unsafe_archive_before_extraction(self):
        name = metadata()["archive_file"]
        data = self._ready_zip(Path(name).stem, unsafe=True)
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            current = parent / "running-build342"
            current.mkdir()
            (current / ".engine-ready-manifest.json").write_text("{}")
            archive = parent / name
            archive.write_bytes(data)
            with patch.object(updates, "_metadata", return_value=metadata(data)):
                with self.assertRaisesRegex(ValueError, "ไม่ปลอดภัย"):
                    updates.install(archive, current, launch=False)
            self.assertFalse((parent / "outside.txt").exists())
            self.assertFalse((parent / Path(name).stem).exists())

    def test_install_rejects_tampering_even_with_archive_validated(self):
        name = metadata()["archive_file"]
        original = self._ready_zip(Path(name).stem)
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            current = parent / "running-build342"
            current.mkdir()
            (current / ".engine-ready-manifest.json").write_text("{}")
            archive = parent / name
            archive.write_bytes(original + b"modified")
            with patch.object(updates, "_metadata", return_value=metadata(original)):
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    updates.install(archive, current, launch=False)
            self.assertFalse((parent / Path(name).stem).exists())



if __name__=="__main__": unittest.main()
