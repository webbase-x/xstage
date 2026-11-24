"""Mocked HTTP and Core Audio contract tests; run without Windows hardware."""
import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from karaoke.web_volume_bridge import ALLOWED_ORIGIN, HOST, VolumeBridgeServer
from karaoke.web_volume_update import asset_for_update, EXE, DOWNLOAD


class FakeVolume:
    state = {"volume": 71.0, "muted": False}

    def read(self):
        return self.state["volume"], self.state["muted"]

    def write(self, percent):
        self.state["volume"] = float(percent)
        self.state["muted"] = percent == 0
        return self.read()

    def set_muted(self, muted):
        self.state["muted"] = muted
        return self.read()

    def close(self):
        pass


class WebVolumeBridgeTests(unittest.TestCase):
    def setUp(self):
        FakeVolume.state = {"volume": 71.0, "muted": False}
        self.server = VolumeBridgeServer((HOST, 0), FakeVolume, code="1234567890")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_port)
        self.token = None

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=3)
        self.server.server_close()

    def call(self, path, method="GET", payload=None, origin=ALLOWED_ORIGIN, auth=None, host=None):
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Origin": origin}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if auth is not None:
            headers["Authorization"] = "Bearer " + auth
        if host:
            headers["Host"] = host
        req = Request(self.url + path, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=3) as response:
                body = response.read()
                return response.status, json.loads(body) if body else None, dict(response.headers)
        except HTTPError as error:
            return error.code, json.loads(error.read()), dict(error.headers)

    def test_opt_in_pair_read_write_mute_and_origin_isolation(self):
        status, info, _ = self.call("/v1/health")
        self.assertEqual(status, 200)
        self.assertEqual(info["service"], "XStageWindowsVolumeBridge")
        self.assertEqual(self.call("/v1/volume")[0], 401)
        self.assertEqual(self.call("/v1/pair", "POST", {"code": "wrong"})[0], 403)
        self.assertEqual(self.call("/v1/pair", "POST", {"code": "1234567890"},
                                   origin="https://evil.example")[0], 403)
        status, info, _ = self.call("/v1/pair", "POST", {"code": "1234567890"})
        self.assertEqual(status, 200)
        self.assertEqual(info["volume"], 71)
        self.token = info["token"]
        self.assertGreater(len(self.token), 32)
        self.assertEqual(self.call("/v1/volume", auth=self.token)[1]["volume"], 71)
        status, info, _ = self.call("/v1/volume", "PUT", {"volume": 42}, auth=self.token)
        self.assertEqual(status, 200)
        self.assertEqual(info["volume"], 42)
        self.assertEqual(self.call("/v1/mute", "PUT", {"muted": True},
                                   auth=self.token)[1]["muted"], True)
        self.assertEqual(self.call("/v1/mute", "PUT", {"muted": False},
                                   auth=self.token)[1]["muted"], False)
        self.assertEqual(FakeVolume.state["volume"], 42)
        self.assertEqual(self.call("/v1/volume", "PUT", {"volume": 105},
                                   auth=self.token)[0], 400)
        self.assertEqual(self.call("/v1/mute", "PUT", {"muted": "yes"},
                                   auth=self.token)[0], 400)
        self.assertEqual(self.call("/v1/volume", "PUT", {"volume": 13},
                                   auth="invalid")[0], 401)
        self.assertEqual(self.call("/v1/volume", "PUT", {"volume": 13},
                                   auth=self.token, origin="https://other.example")[0], 403)
        self.assertEqual(self.call("/v1/volume", auth=self.token,
                                   host="rebinding.invalid:48731")[0], 403)
        self.assertEqual(FakeVolume.state["volume"], 42)

    def test_update_manifest_validation(self):
        asset = {"name": EXE, "browser_download_url": DOWNLOAD, "label": "build-5", "digest": "sha256:" + "a"*64, "size": 100}
        self.assertEqual(asset_for_update({"assets": [asset]}, 4), (5, "a"*64, 100))
        self.assertIsNone(asset_for_update({"assets": [asset]}, 5))
        self.assertIsNone(asset_for_update({"assets": [dict(asset, digest="invalid")]}, 4))
        self.assertIsNone(asset_for_update({"assets": [dict(asset, browser_download_url="https://evil.invalid/a.exe")]}, 4))

    def test_automatic_connect_requires_local_approval(self):
        self.assertEqual(self.call("/v1/connect", "POST", {})[0], 403)
        self.server.approved = True
        self.assertEqual(self.call("/v1/connect", "POST", {}, origin="https://evil.example")[0], 403)
        self.assertEqual(self.call("/v1/connect", "POST", {}, host="evil.invalid:48731")[0], 403)
        status, data, _ = self.call("/v1/connect", "POST", {})
        self.assertEqual(status, 200)
        self.assertEqual(self.call("/v1/connect", "POST", {})[1]["token"], data["token"])
        self.assertEqual(self.call("/v1/volume", auth=data["token"])[0], 200)

    def test_preflight_restricts_origins(self):
        code, _, headers = self.call("/v1/volume", "OPTIONS")
        self.assertEqual(code, 204)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), ALLOWED_ORIGIN)
        self.assertEqual(headers.get("Access-Control-Allow-Private-Network"), "true")
        self.assertEqual(self.call("/v1/volume", "OPTIONS", origin="https://evil.example")[0], 403)

    def test_pairing_rate_limit(self):
        for _ in range(5):
            self.assertEqual(self.call("/v1/pair", "POST", {"code": "0000000000"})[0], 403)
        self.assertEqual(self.call("/v1/pair", "POST", {"code": "1234567890"})[0], 403,
                         "Pairing attempts must be throttled, even with correct code")


if __name__ == "__main__":
    unittest.main()
