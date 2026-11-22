"""Opt-in loopback companion for X-Stage Karaoke Online on Windows.

A browser has no Windows Core Audio master-volume API. This helper runs only
after the user launches it, binds to 127.0.0.1, requires a one-time pairing
code and a bearer token, and allows only the official GitHub Pages origin.
"""
from __future__ import annotations

import hmac
import json
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from karaoke.system_volume import WindowsVolume

HOST = "127.0.0.1"
PORT = 48731
ALLOWED_ORIGIN = "https://webbase-x.github.io"


class VolumeBridgeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address=(HOST, PORT), volume_factory=WindowsVolume, code=None):
        super().__init__(address, VolumeBridgeHandler)
        self.volume_factory = volume_factory
        self.pair_code = code or str(secrets.randbelow(10**10)).zfill(10)
        self.session_token = ""
        self.failed_pairs = []
        self.guard = threading.Lock()

    def volume(self, update=None, muted=None):
        # Core Audio COM initialization and cleanup occur on the request thread.
        controller = self.volume_factory()
        try:
            if update is not None:
                return controller.write(update)
            if muted is not None:
                return controller.set_muted(muted)
            return controller.read()
        finally:
            controller.close()

    def pair(self, code):
        with self.guard:
            now = time.monotonic()
            self.failed_pairs = [v for v in self.failed_pairs if now - v < 60]
            if len(self.failed_pairs) >= 5:
                return None
            if not isinstance(code, str) or not hmac.compare_digest(code, self.pair_code):
                self.failed_pairs.append(now)
                return None
            self.failed_pairs.clear()
            self.session_token = secrets.token_urlsafe(32)
            return self.session_token


class VolumeBridgeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format, *_args):
        # Never log bearer tokens, URL payloads, or pair codes.
        pass

    def _approved(self):
        host = self.headers.get("Host", "")
        host_ok = host in {
            f"{HOST}:{self.server.server_port}",
            f"localhost:{self.server.server_port}",
        }
        return host_ok and self.headers.get("Origin", "") == ALLOWED_ORIGIN

    def _headers(self):
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")

    def _json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        if self._approved():
            self._headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _request(self):
        try:
            size = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            size = -1
        if not 0 <= size <= 2048:
            raise ValueError("JSON body size invalid")
        try:
            payload = json.loads(self.rfile.read(size))
        except (ValueError, UnicodeError) as error:
            raise ValueError("Invalid JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("Expected object")
        return payload

    def _authorized(self):
        header = self.headers.get("Authorization", "")
        token = self.server.session_token
        return bool(token and header.startswith("Bearer ") and
                    hmac.compare_digest(header[7:], token))

    def do_OPTIONS(self):
        if not self._approved():
            self._json(403, {"error": "Origin denied"})
            return
        self.send_response(204)
        self._headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if not self._approved():
            return self._json(403, {"error": "Origin denied"})
        if self.path == "/v1/health":
            return self._json(200, {"service": "XStageWindowsVolumeBridge", "paired": bool(self.server.session_token)})
        if self.path != "/v1/volume":
            return self._json(404, {"error": "Not found"})
        if not self._authorized():
            return self._json(401, {"error": "Pair with Windows helper first"})
        try:
            level, muted = self.server.volume()
            return self._json(200, {"volume": round(level, 2), "muted": muted})
        except (OSError, ValueError) as error:
            return self._json(503, {"error": str(error)})

    def do_POST(self):
        if not self._approved():
            return self._json(403, {"error": "Origin denied"})
        if self.path != "/v1/pair":
            return self._json(404, {"error": "Not found"})
        try:
            payload = self._request()
        except ValueError as error:
            return self._json(400, {"error": str(error)})
        token = self.server.pair(payload.get("code"))
        if not token:
            return self._json(403, {"error": "Incorrect code or too many attempts"})
        try:
            level, muted = self.server.volume()
            return self._json(200, {"token": token, "volume": round(level, 2), "muted": muted})
        except (OSError, ValueError) as error:
            return self._json(503, {"error": str(error)})

    def do_PUT(self):
        if not self._approved():
            return self._json(403, {"error": "Origin denied"})
        if self.path not in ("/v1/volume", "/v1/mute"):
            return self._json(404, {"error": "Not found"})
        if not self._authorized():
            return self._json(401, {"error": "Pair with Windows helper first"})
        try:
            payload = self._request()
            if self.path == "/v1/volume":
                value = payload.get("volume")
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
                    raise ValueError("Volume must be 0–100")
                level, muted = self.server.volume(update=value)
            else:
                value = payload.get("muted")
                if not isinstance(value, bool):
                    raise ValueError("Muted must be boolean")
                level, muted = self.server.volume(muted=value)
            return self._json(200, {"volume": round(level, 2), "muted": muted})
        except ValueError as error:
            return self._json(400, {"error": str(error)})
        except OSError as error:
            return self._json(503, {"error": str(error)})


def main():
    if sys.platform != "win32":
        raise SystemExit("X-Stage Windows Volume Bridge requires Windows 10/11")
    with VolumeBridgeServer() as server:
        print("X-Stage Windows Volume Bridge", flush=True)
        print("Pairing code:", server.pair_code, flush=True)
        print("Keep this window open while controlling Windows volume from Karaoke Online.", flush=True)
        print("Listening only on http://127.0.0.1:" + str(server.server_port), flush=True)
        print("Press Ctrl+C to stop and revoke access.", flush=True)
        try:
            server.serve_forever(poll_interval=.25)
        except KeyboardInterrupt:
            pass
        finally:
            server.shutdown()


if __name__ == "__main__":
    main()
