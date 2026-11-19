"""HTTP integration checks for all native folder/file picker actions.

The real QApplication bridge is tested separately on Windows. The request
boundary is tested here with Unicode Thai paths and a fake GUI response.
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app


class NativePickerApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.workspace=self.root/"คลังเพลง"
        self.folder=self.root/"เพลงไทย ชั้น ป.๒"
        self.folder.mkdir()
        self.lrc=self.folder/"ทดสอบเนื้อร้อง.lrc"
        self.lrc.write_text("[00:01]ทดลอง",encoding="utf-8")
        self.state=app.State(self.workspace)
        handler=type("ProPickerTestHandler",(app.Handler,),{"state":self.state})
        self.server=ThreadingHTTPServer(("127.0.0.1",0),handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=4)

    def post(self,path,payload,token=None):
        request=urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_port}"+path,
            data=json.dumps(payload,ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type":"application/json",
                     "X-XStage-Token":token if token is not None else self.state.token},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request,timeout=8) as response:
                return response.status,json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code,json.loads(exc.read())

    def test_folder_selection_uses_gui_callback_and_preserves_thai_path(self):
        seen=[]
        def picker(kind,current):
            seen.append((kind,current,threading.current_thread().name))
            return {"path":str(self.folder),"cancelled":False}
        self.state.native_picker=picker
        code,result=self.post("/api/pick",{"kind":"folder","current":str(self.workspace)})
        self.assertEqual(code,200)
        self.assertEqual(result["path"],str(self.folder))
        self.assertEqual(seen[0][0:2],("folder",str(self.workspace)))
        self.assertNotEqual(seen[0][2],threading.current_thread().name)

    def test_lrc_selection_and_cancel_do_not_erase_previous_path(self):
        self.state.native_picker=lambda kind,current:{
            "path":str(self.lrc),"cancelled":False}
        code,data=self.post("/api/pick",{"kind":"lrc","current":str(self.folder)})
        self.assertEqual(code,200)
        self.assertEqual(data["path"],str(self.lrc))
        self.state.native_picker=lambda kind,current:{
            "path":"","cancelled":True}
        code,data=self.post("/api/pick",{"kind":"folder","current":str(self.folder)})
        self.assertEqual((code,data["cancelled"],data["path"]),(200,True,""))

    def test_rejected_access_and_unavailable_picker_has_readable_error(self):
        self.state.native_picker=None
        code,data=self.post("/api/pick",{"kind":"folder"})
        self.assertEqual(code,400)
        self.assertIn("Windows",data["error"])
        code,data=self.post("/api/pick",{"kind":"other"})
        self.assertEqual(code,400)
        code,_=self.post("/api/pick",{"kind":"folder"},token="invalid")
        self.assertEqual(code,403)

    def test_picker_runtime_errors_are_user_visible(self):
        def broken(kind,current):
            raise RuntimeError("ไม่สามารถเปิด Windows Dialog ได้")
        self.state.native_picker=broken
        code,data=self.post("/api/pick",{"kind":"folder"})
        self.assertEqual(code,400)
        self.assertIn("Windows Dialog",data["error"])

    def test_open_source_and_workspace_in_explorer(self):
        with patch.object(app.sys,"platform","win32"),\
             patch.object(app.os,"startfile",create=True) as start:
            code,data=self.post("/api/open-folder",{"scope":"source","path":str(self.folder)})
            self.assertEqual(code,200)
            self.assertTrue(data["opened"])
            start.assert_called_with(str(self.folder.resolve()))
            code,data=self.post("/api/open-folder",{"scope":"workspace"})
            self.assertEqual(code,200)
            self.assertTrue(data["opened"])
            start.assert_called_with(str(self.workspace.resolve()))
            code,data=self.post("/api/open-folder",{"scope":"source","path":str(self.root/"missing")})
            self.assertEqual(code,400)
            self.assertIn("ไม่พบโฟลเดอร์",data["error"])
            self.assertEqual(self.post("/api/open-folder",{"scope":"random"})[0],400)


if __name__=="__main__":
    unittest.main()
