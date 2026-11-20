"""Direct latest-version updates, GitHub range-resume, integrity and failures."""
from __future__ import annotations

import hashlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pro_updater as updater


def manifest(version,contents=b"MZ"+b"good"*300000):
    return {"name":"X-Stage Song Studio Pro","available":True,
            "version":version,
            "download_url":"https://github.com/webbase-x/xstage/releases/download/"
                "song-studio-pro-v"+version+"-preview/"
                "X-Stage-Song-Studio-Pro-v"+version+"-win-x64-Setup.exe",
            "sha256":hashlib.sha256(contents).hexdigest()}


class Response:
    def __init__(self,content,status=200,headers=None,url=None):
        self.stream=io.BytesIO(content)
        self.status=status
        self.headers=headers or {"Content-Length":str(len(content))}
        self.url=url or "https://release-assets.githubusercontent.com/releases/download/verified"
    def __enter__(self):return self
    def __exit__(self,*args):self.stream.close()
    def read(self,amount=-1):return self.stream.read(amount)
    def geturl(self):
        return self.url
    def getcode(self):return self.status


class LatestUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace=Path(self.tmp.name)/"studio"

    def test_selects_highest_published_version_without_incremental_steps(self):
        def feed(url):
            return updater.validate(manifest(
                "0.1.90" if url==updater.RAW_MANIFEST_URL else "0.1.89"))
        with patch.object(updater,"_read_feed",side_effect=feed), \
             patch.object(updater,"_read_release_api",side_effect=OSError("offline")):
            result=updater.check()
        self.assertEqual(result["version"],"0.1.90")
        self.assertTrue(result["newer"])

    def test_uses_raw_github_feed_when_pages_unavailable(self):
        def feed(url):
            if url==updater.MANIFEST_URL:
                raise OSError("Pages temporarily unavailable")
            return updater.validate(manifest("0.1.91"))
        with patch.object(updater,"_read_feed",side_effect=feed), \
             patch.object(updater,"_read_release_api",side_effect=OSError("offline")):
            self.assertEqual(updater.check()["version"],"0.1.91")

    def test_release_api_uses_actual_published_asset_digest(self):
        import json
        item=manifest("0.1.27")
        expected={
            "tag_name":"song-studio-pro-v0.1.27-preview",
            "draft":False,
            "assets":[{
                "name":"X-Stage-Song-Studio-Pro-v0.1.27-win-x64-Setup.exe",
                "browser_download_url":item["download_url"],
                "digest":"sha256:"+item["sha256"],
                "size":225446806,"state":"uploaded",
            }],
        }
        response=Response(json.dumps([expected]).encode("utf-8"),
            url="https://api.github.com/repos/webbase-x/xstage/releases?per_page=100")
        with patch.object(updater.urllib.request,"urlopen",return_value=response):
            release=updater._read_release_api()
        self.assertEqual(release["version"],"0.1.27")
        self.assertEqual(release["sha256"],item["sha256"])

    def test_unavailable_manifests_fall_back_to_verified_github_release(self):
        release=updater.validate(manifest("0.1.32"))
        release["feed"]="api.github.com"
        with patch.object(updater,"_read_feed",side_effect=
                          ValueError("ยังไม่มีไฟล์ Song Studio Pro ที่ยืนยันแล้ว")), \
             patch.object(updater,"_read_release_api",return_value=release):
            result=updater.check()
        self.assertEqual(result["version"],"0.1.32")
        self.assertTrue(result["newer"])

    def test_manifest_newer_than_uploaded_release_is_not_advertised(self):
        release=updater.validate(manifest("0.1.27"))
        with patch.object(updater,"_read_feed",
                          return_value=updater.validate(manifest("0.1.28"))), \
             patch.object(updater,"_read_release_api",return_value=release):
            result=updater.check()
        self.assertEqual(result["version"],"0.1.27")

    def test_download_snapshot_survives_second_manifest_failure(self):
        import app
        import plus_core as core
        earlier=updater.validate(manifest("0.1.99"))
        earlier.update({"current_version":"0.1.28","newer":True})
        with patch.object(core,"interrupted_import",return_value=None):
            state=app.State(self.workspace)
        with patch.object(updater,"check",return_value=earlier) as lookup:
            first=state.check_latest_update()
            target=state.download_target()
            self.assertEqual(lookup.call_count,1)
        self.assertEqual(target["sha256"],first["sha256"])
        with patch.object(updater,"check",
                          side_effect=ValueError("transient unavailable")):
            fallback=state.check_latest_update()
            self.assertTrue(fallback["used_previous_verification"])
            self.assertEqual(state.download_target()["version"],"0.1.99")

    def test_resumes_interrupted_github_asset_and_hashes_entire_file(self):
        content=b"MZ"+b"x"*(2*1024*1024)
        half=content[:1024*1024]
        requests=[]
        def urlopen(req,timeout=None):
            requests.append(req)
            if len(requests)==1:
                return Response(half,headers={"Content-Length":str(len(content))})
            remaining=content[len(half):]
            return Response(remaining,206,{
                "Content-Range":"bytes "+str(len(half))+"-"+str(len(content)-1)+"/"+str(len(content)),
                "Content-Length":str(len(remaining))})
        progress=[]
        with patch.object(updater.sys,"platform","win32"), \
             patch.object(updater.sys,"frozen",True,create=True), \
             patch.object(updater.urllib.request,"urlopen",side_effect=urlopen), \
             patch.object(updater.time,"sleep",return_value=None):
            result=updater.download(
                self.workspace,manifest("0.1.99",content),
                lambda p,m:progress.append((p,m)),None)
        self.assertEqual(len(requests),2)
        self.assertEqual(requests[1].get_header("Range"),"bytes=1048576-")
        self.assertEqual(Path(result["path"]).read_bytes(),content)
        self.assertEqual(updater.ready_file(self.workspace)["version"],"0.1.99")
        self.assertEqual(progress[-1][0]["downloaded_bytes"],len(content))

    def test_mismatched_range_cannot_corrupt_resume(self):
        content=b"MZ"+b"x"*(2*1024*1024)
        partial=self.workspace/"UPDATES"/"X-Stage-Song-Studio-Pro-v0.1.99-win-x64-Setup.exe.partial"
        partial.parent.mkdir(parents=True)
        partial.write_bytes(content[:1024*1024])
        marker=partial.with_name(partial.name+".json")
        import json
        entry=updater.validate(manifest("0.1.99",content))
        marker.write_text(json.dumps({"url":entry["url"],"sha256":entry["sha256"],
                                      "version":entry["version"]}),encoding="utf-8")
        bad=Response(content[1024*1024:],206,{
            "Content-Range":"bytes 0-1048577/2097154",
            "Content-Length":str(1024*1024+2)})
        with patch.object(updater.sys,"platform","win32"), \
             patch.object(updater.sys,"frozen",True,create=True), \
             patch.object(updater.urllib.request,"urlopen",return_value=bad):
            with self.assertRaisesRegex(ValueError,"ช่วงข้อมูล"):
                updater.download(self.workspace,manifest("0.1.99",content),None,None)
        self.assertEqual(partial.read_bytes(),content[:1024*1024])

    def test_wrong_hash_never_creates_ready_exe(self):
        content=b"MZ"+b"x"*(2*1024*1024)
        bad=manifest("0.1.99",b"DIFFERENT"+content)
        with patch.object(updater.sys,"platform","win32"), \
             patch.object(updater.sys,"frozen",True,create=True), \
             patch.object(updater.urllib.request,"urlopen",
                          side_effect=lambda req,timeout=None:Response(content)), \
             patch.object(updater.time,"sleep",return_value=None):
            with self.assertRaisesRegex(OSError,"SHA-256"):
                updater.download(self.workspace,bad,None,None)
        self.assertIsNone(updater.ready_file(self.workspace))


if __name__=="__main__":
    unittest.main()
