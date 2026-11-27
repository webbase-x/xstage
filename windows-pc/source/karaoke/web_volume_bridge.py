"""Opt-in loopback companion for X-Stage Karaoke Online on Windows.

A browser has no Windows Core Audio master-volume API. This helper runs only
after the user launches it, binds to 127.0.0.1, requires local user approval
and a bearer token, and allows only the official GitHub Pages origin.
"""
from __future__ import annotations

import hmac
import ctypes
import os
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr
import json
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from karaoke.system_volume import WindowsVolume
from karaoke import web_volume_update

HOST = "127.0.0.1"
PORT = 48731
ALLOWED_ORIGIN = "https://webbase-x.github.io"


class VolumeBridgeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address=(HOST, PORT), volume_factory=WindowsVolume, code=None, approved=False):
        super().__init__(address, VolumeBridgeHandler)
        self.volume_factory = volume_factory
        self.pair_code = code  # legacy test/explicit compatibility only
        self.approved = approved
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

    def connect(self):
        with self.guard:
            if not self.approved:
                return None
            if not self.session_token:
                self.session_token = secrets.token_urlsafe(32)
            return self.session_token

    def pair(self, code):
        with self.guard:
            now = time.monotonic()
            self.failed_pairs = [v for v in self.failed_pairs if now - v < 60]
            if len(self.failed_pairs) >= 5:
                return None
            if not self.pair_code or not isinstance(code, str) or not hmac.compare_digest(code, self.pair_code):
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
            return self._json(200, {"service": "XStageWindowsVolumeBridge", "paired": bool(self.server.session_token), "automatic": self.server.approved})
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
        if self.path not in ("/v1/pair", "/v1/connect"):
            return self._json(404, {"error": "Not found"})
        try:
            payload = self._request()
        except ValueError as error:
            return self._json(400, {"error": str(error)})
        if self.headers.get_content_type() != "application/json":
            return self._json(400, {"error": "Expected JSON content type"})
        token = self.server.connect() if self.path == "/v1/connect" else self.server.pair(payload.get("code"))
        if not token:
            return self._json(403, {"error": "Local Windows approval required or legacy pairing denied"})
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


def consent():
    # Approval is scoped to this Windows user and exact browser origin.
    root = Path(os.environ["LOCALAPPDATA"]) / "XStage" / "VolumeBridge"
    root.mkdir(parents=True, exist_ok=True)
    marker = root / "approved-v1"
    if marker.is_file():
        return True
    yes = ctypes.windll.user32.MessageBoxW(None,
        "Allow X-Stage Karaoke Online (https://webbase-x.github.io) to control Windows master volume on this computer? You can revoke approval from the tray icon menu.",
        "X-Stage Windows Volume Bridge", 0x24 | 0x100)
    if yes != 6:
        return False
    marker.write_text(ALLOWED_ORIGIN, encoding="utf-8")
    if getattr(sys, "frozen", False):
        if ctypes.windll.user32.MessageBoxW(None,
            "Start the volume helper automatically when you sign in to Windows?",
            "X-Stage Windows Volume Bridge", 0x24 | 0x100) == 6:
            try:
                import winreg
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                    winreg.SetValueEx(key, "XStageWindowsVolumeBridge", 0, winreg.REG_SZ, '"'+sys.executable+'"')
            except OSError as error:
                print("Startup registration failed:", error, flush=True)
    return True


def run_in_tray(server, icon_factory=None):
    """Keep the HTTP listener alive until the user exits the tray."""
    if icon_factory is None:
        import pystray
        from PIL import Image, ImageDraw
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((2, 2, 61, 61), radius=12, fill="#17233b")
        draw.line((17, 17, 47, 47), fill="#ffffff", width=8)
        draw.line((47, 17, 17, 47), fill="#55c7ff", width=8)
        def exit_bridge(icon, _item):
            icon.stop()
        def revoke(icon, _item):
            marker = Path(os.environ["LOCALAPPDATA"]) / "XStage" / "VolumeBridge" / "approved-v1"
            try:
                marker.unlink(missing_ok=True)
            except OSError as error:
                ctypes.windll.user32.MessageBoxW(None, str(error), "X-Stage Windows Volume Bridge", 0x10)
                return
            icon.stop()
        icon_factory = lambda: pystray.Icon(
            "XStageWindowsVolumeBridge", image, "X-Stage Windows Volume Bridge",
            pystray.Menu(pystray.MenuItem("Exit", exit_bridge),
                         pystray.MenuItem("Revoke approval and exit", revoke)))
    icon = icon_factory()
    worker = threading.Thread(target=server.serve_forever,
                              kwargs={"poll_interval": .25}, daemon=True)
    worker.start()
    try:
        icon.run()
    finally:
        server.shutdown()
        worker.join()


def _run():
    if sys.platform != "win32":
        raise SystemExit("X-Stage Windows Volume Bridge requires Windows 10/11")
    smoke = '--ci-smoke' in sys.argv
    if not smoke and '--no-update' not in sys.argv and web_volume_update.check_and_install():
        return
    approved = False if smoke else consent()
    if not approved and not smoke:
        return
    with VolumeBridgeServer(approved=approved) as server:
        print('X-Stage Windows Volume Bridge · automatic connection enabled', flush=True)
        print("Listening only on http://127.0.0.1:" + str(server.server_port), flush=True)
        if smoke:
            server.serve_forever(poll_interval=.25)
        else:
            run_in_tray(server)


def main():
    if sys.platform != "win32":
        raise SystemExit("X-Stage Windows Volume Bridge requires Windows 10/11")
    # PyInstaller windowed builds have no stdout or stderr. Use a local log
    # for startup/update failures without creating a console window.
    if sys.stdout is not None and sys.stderr is not None:
        _run()
        return
    try:
        root = Path(os.environ["LOCALAPPDATA"]) / "XStage" / "VolumeBridge"
        root.mkdir(parents=True, exist_ok=True)
        with (root / "bridge.log").open("w", encoding="utf-8", buffering=1) as log:
            with redirect_stdout(log), redirect_stderr(log):
                _run()
    except Exception as error:
        ctypes.windll.user32.MessageBoxW(None, str(error),
            "X-Stage Windows Volume Bridge", 0x10)


if __name__ == "__main__":
    main()
