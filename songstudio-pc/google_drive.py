"""X-Stage Song Studio PC — real Google Desktop OAuth and PRIVATE Drive sync.

Standard library only; a user-supplied Google Desktop OAuth client JSON is
required. The app never publishes credentials or file permissions. OAuth uses
loopback + PKCE, and Windows DPAPI protects refresh tokens at rest.
Drive scope: drive.file (only files this OAuth app creates/opens).
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import http.client
import http.server
import io
import json
import mimetypes
import re
import os
import secrets
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zipfile
from ctypes import wintypes
from pathlib import Path

API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/drive.file"
ROOT_NAME = "X-Stage Song Studio"
MAX_HTTP_RESPONSE = 8 * 1024 * 1024


class GoogleError(RuntimeError):
    pass


def _focus_google_browser_window(stop_signal=None, timeout=4):
    """Best-effort bring the user's actual Google sign-in browser to foreground.

    The default browser may reuse a background tab even with autoraise=True.
    Only target a *visible browser window* whose title identifies Google
    Accounts; do not steal focus from an unrelated app. Windows may prohibit
    foreground changes, in which case the app provides a manual retry button.
    """
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.FlashWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if stop_signal is not None and stop_signal.is_set():
                return True
            windows = []

            @callback_type
            def collect(hwnd, _):
                if not user32.IsWindowVisible(hwnd):
                    return True
                n = user32.GetWindowTextLengthW(hwnd)
                if n < 5 or n > 500:
                    return True
                title_buffer = ctypes.create_unicode_buffer(n + 1)
                class_buffer = ctypes.create_unicode_buffer(128)
                user32.GetWindowTextW(hwnd, title_buffer, n + 1)
                user32.GetClassNameW(hwnd, class_buffer, 128)
                title = title_buffer.value.casefold()
                window_class = class_buffer.value.casefold()
                browser = ("chrome_widgetwin" in window_class or
                           "mozillawindowclass" in window_class)
                google = any(x in title for x in (
                    "google accounts", "accounts.google.com", "เลือกบัญชี",
                    "ลงชื่อเข้าใช้บัญชี", "choose an account",
                    "sign in - google", "เข้าสู่ระบบ - google"))
                if browser and google:
                    windows.append(hwnd)
                return True

            user32.EnumWindows(collect, 0)
            if windows:
                hwnd = windows[0]
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE, including minimized browsers
                user32.BringWindowToTop(hwnd)
                if user32.SetForegroundWindow(hwnd):
                    return True
                user32.FlashWindow(hwnd, True)
            time.sleep(.25)
    except (OSError, AttributeError, TypeError, ValueError):
        # Background raise is opportunistic, not a prerequisite for OAuth.
        return False
    return False


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _request(url, *, method="GET", headers=None, body=None, timeout=30):
    if not url.startswith(("https://www.googleapis.com/", "https://oauth2.googleapis.com/")):
        raise GoogleError("ปลายทาง Google API ไม่ได้รับอนุญาต")
    request = urllib.request.Request(url, method=method, data=body, headers=headers or {})
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        try:
            message = json.loads(exc.read(4096).decode("utf-8", "replace"))
            detail = message.get("error_description") or message.get("error", {}).get("message", "")
            if isinstance(detail, dict):
                detail = detail.get("message", "")
        except Exception:
            detail = ""
        raise GoogleError(f"Google API HTTP {exc.code}: {detail or exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise GoogleError("เชื่อมต่อ Google ไม่สำเร็จ: " + str(exc)) from exc


def _read_json(url, **options):
    with _request(url, **options) as response:
        data = response.read(MAX_HTTP_RESPONSE + 1)
    if len(data) > MAX_HTTP_RESPONSE:
        raise GoogleError("Google API ส่งข้อมูลตอบกลับเกินขนาด")
    return json.loads(data.decode("utf-8"))


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _crypt(data: bytes, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise GoogleError("Google Login แบบบันทึกโทเค็นรองรับเฉพาะ Windows")
    dll = ctypes.windll.crypt32
    kernel = ctypes.windll.kernel32
    # Windows HLOCAL is pointer-sized; without argtypes ctypes defaults to
    # 32-bit int and can truncate the returned DPAPI buffer on x64 Windows.
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        fn = dll.CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                       ctypes.POINTER(_Blob)]
    else:
        fn = dll.CryptProtectData
        fn.argtypes = [ctypes.POINTER(_Blob), ctypes.c_wchar_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                       ctypes.POINTER(_Blob)]
    fn.restype = wintypes.BOOL
    src_buf = ctypes.create_string_buffer(data)
    src = _Blob(len(data), ctypes.cast(src_buf, ctypes.POINTER(ctypes.c_char)))
    out = _Blob()
    # CRYPTPROTECT_UI_FORBIDDEN prevents unexpectedly opening an OS prompt.
    flags = 0x01
    args = ([ctypes.byref(src), None, None, None, None, flags, ctypes.byref(out)]
            if decrypt else
            [ctypes.byref(src), "X-Stage Song Studio", None, None, None,
             flags, ctypes.byref(out)])
    if not fn(*args):
        raise GoogleError("Windows DPAPI ไม่สามารถป้องกัน/ถอดรหัสโทเค็นได้")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def _read_client(path: str | Path) -> dict:
    file = Path(path).expanduser()
    if not file.is_file() or file.suffix.lower() != ".json":
        raise GoogleError("กรุณาเลือกไฟล์ Google Desktop OAuth Client JSON ที่ดาวน์โหลดจาก Google Cloud ก่อน")
    try:
        config = json.loads(file.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise GoogleError("ไฟล์ OAuth Client JSON ไม่ถูกต้อง") from exc
    data = config.get("installed", {})
    if not isinstance(data, dict) or not isinstance(data.get("client_id"), str) or not data["client_id"].endswith(".apps.googleusercontent.com"):
        raise GoogleError("ต้องเป็น OAuth Client ประเภท Desktop app (ไม่ใช่ Web/Android Client)")
    # Google issues a client_secret to Desktop OAuth clients, and its token
    # endpoint can respond HTTP 400 'client_secret is missing' if omitted.
    # A native client's secret is not confidential. Keep it inside the app's
    # Desktop config (NOT in a user's token store), and retain PKCE.
    if not isinstance(data.get("client_secret"), str) or not data["client_secret"].strip():
        raise GoogleError(
            "OAuth Desktop Client JSON ไม่มี client_secret จึงล็อกอิน Google ไม่ได้ "
            "· โปรดนำเข้า JSON ต้นฉบับจาก Google Cloud ใหม่หนึ่งครั้ง "
            "หรือให้ผู้พัฒนาบรรจุ Desktop Client ID + Client Secret ในรุ่น PC"
        )
    return data


class GoogleDrive:
    def __init__(self, data_dir, get_oauth_path):
        self.data = Path(data_dir)
        self.data.mkdir(parents=True, exist_ok=True)
        self.secret_file = self.data / "google-auth.dpapi"
        self.get_oauth_path = get_oauth_path
        self.lock = threading.RLock()
        self.refresh_token = ""
        self.access_token = ""
        self.access_expires = 0.0
        self.email = ""
        self.client_id = ""
        self.last_error = ""
        self.pending_auth_url = ""
        self.pending_auth_stop = None
        if self.secret_file.exists():
            try:
                saved = json.loads(_crypt(self.secret_file.read_bytes(), True))
                self.refresh_token = saved.get("refresh_token", "")
                self.email = saved.get("email", "")
                self.client_id = saved.get("client_id", "")
            except (GoogleError, OSError, ValueError):
                self.last_error = "โทเค็นเดิมอ่านไม่ได้ กรุณาล็อกอินใหม่บน Windows เครื่องนี้"

    def client_config(self):
        """Installed Desktop client from bundled build or user's stable override."""
        return _read_client(self.get_oauth_path())

    def import_client(self, filename):
        """Retain BOTH Desktop client fields. Never copy personal user tokens.

        The prior importer discarded Google's installed.client_secret, causing
        HTTP 400 'client_secret is missing'. Desktop apps are public OAuth
        clients; this field is an app credential, not the user's refresh token.
        """
        data = _read_client(filename)
        public = {"installed": {
            "client_id": data["client_id"],
            "client_secret": data["client_secret"],
            "auth_uri": AUTH_URL,
            "token_uri": TOKEN_URL,
            "redirect_uris": ["http://127.0.0.1"]
        }}
        output = self.data / "oauth-client.json"
        temp = output.with_name("oauth-client.json.tmp")
        try:
            temp.write_text(json.dumps(public, indent=2), encoding="utf-8")
            temp.replace(output)
        finally:
            temp.unlink(missing_ok=True)
        return str(output)

    def status(self):
        with self.lock:
            try:
                client = self.client_config()
                configured = True
                client_matches = bool(self.refresh_token) and client["client_id"] == self.client_id
                error = (self.last_error if client_matches or not self.refresh_token
                         else "OAuth Client เปลี่ยนแล้ว กรุณาลงชื่อเข้าใช้ใหม่")
                return {"configured": configured, "connected": client_matches,
                        "email": self.email if client_matches else "",
                        "error": error, "scope": SCOPE,
                        "config_source": ("user" if Path(self.get_oauth_path()) ==
                                          self.data / "oauth-client.json" else "bundled")}
            except GoogleError as exc:
                return {"configured": False, "connected": False, "email": "",
                        "error": str(exc), "scope": SCOPE, "config_source": "missing"}

    def _save(self):
        payload = _json_bytes({
            "client_id": self.client_id,
            "refresh_token": self.refresh_token,
            "email": self.email
        })
        protected = _crypt(payload, False)
        temp = self.secret_file.with_name(self.secret_file.name + ".tmp")
        temp.write_bytes(protected)
        temp.replace(self.secret_file)

    def logout(self):
        with self.lock:
            self.refresh_token = self.access_token = self.email = self.client_id = ""
            self.access_expires = 0
            self.last_error = ""
            self.secret_file.unlink(missing_ok=True)

    def _token_exchange(self, values):
        form = urllib.parse.urlencode(values).encode("ascii")
        return _read_json(TOKEN_URL, method="POST",
                          headers={"Content-Type": "application/x-www-form-urlencoded"},
                          body=form, timeout=45)

    def token(self):
        with self.lock:
            if self.access_token and time.time() + 90 < self.access_expires:
                return self.access_token
            if not self.refresh_token:
                raise GoogleError("ยังไม่ได้ลงชื่อเข้าใช้ Google Drive")
            client = _read_client(self.get_oauth_path())
            if client.get("client_id") != self.client_id:
                raise GoogleError("ไฟล์ OAuth Client เปลี่ยนไป กรุณาลงชื่อเข้าใช้ใหม่")
            form = {"client_id": self.client_id,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token"}
            if client.get("client_secret"):
                form["client_secret"] = client["client_secret"]
            answer = self._token_exchange(form)
            self.access_token = answer["access_token"]
            self.access_expires = time.time() + int(answer.get("expires_in", 3600))
            self.last_error = ""
            return self.access_token

    def show_pending_login(self):
        """Open the *same* active OAuth page again on explicit user request."""
        with self.lock:
            url = self.pending_auth_url
            signal = self.pending_auth_stop
        if not url or signal is None or signal.is_set():
            raise GoogleError("ยังไม่มีหน้า Google Login ที่รอการยืนยัน · กด Google Login ใหม่")
        if not webbrowser.open(url, new=1):
            raise GoogleError("เปิด Google Login ในเบราว์เซอร์เริ่มต้นไม่ได้")
        if os.name == "nt":
            threading.Thread(target=_focus_google_browser_window, args=(signal,),
                             daemon=True, name="xstage-google-login-foreground").start()
        return {"ok": True, "message": "เปิดหน้าต่าง Google Login อีกครั้ง · กรุณาเลือกบัญชีและกดอนุญาต"}

    def login(self, cancelled=None, on_status=None):
        client = _read_client(self.get_oauth_path())
        state = secrets.token_urlsafe(30)
        verifier = secrets.token_urlsafe(72)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()
        received = {}
        signal = threading.Event()

        class Callback(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                return

            def do_GET(self):
                uri = urllib.parse.urlsplit(self.path)
                params = urllib.parse.parse_qs(uri.query)
                if uri.path != "/google-callback" or params.get("state", [""])[0] != state:
                    self.send_error(403)
                    return
                received["code"] = params.get("code", [""])[0]
                received["error"] = params.get("error", [""])[0]
                signal.set()
                detail = (
                    "<h2>Google ไม่อนุญาตให้เชื่อมบัญชี</h2>"
                    "<p>กลับไป X-Stage Song Studio PC เพื่อตรวจข้อผิดพลาดและลองใหม่</p>"
                    if received["error"] else
                    "<h2>Google ส่งรหัสยืนยันแล้ว</h2>"
                    "<p>โปรดกลับไป X-Stage Song Studio PC "
                    "ระบบกำลังตรวจสอบและบันทึกสิทธิ์ Google Drive</p>")
                content = ("<!doctype html><meta charset=utf-8><title>X-Stage Song Studio</title>"
                           "<style>body{font:18px sans-serif;background:#102536;color:#d5faff;"
                           "padding:50px;text-align:center}</style>" + detail)
                content = content.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

        with http.server.HTTPServer(("127.0.0.1", 0), Callback) as listener:
            listener.timeout = 1
            redirect = f"http://127.0.0.1:{listener.server_port}/google-callback"
            params = {"client_id": client["client_id"], "redirect_uri": redirect,
                      "response_type": "code", "scope": SCOPE, "access_type": "offline",
                      "prompt": "consent", "include_granted_scopes": "true",
                      "state": state, "code_challenge": challenge,
                      "code_challenge_method": "S256"}
            url = AUTH_URL + "?" + urllib.parse.urlencode(params)
            with self.lock:
                self.pending_auth_url = url
                self.pending_auth_stop = signal
            try:
                if on_status:
                    on_status("เปิด Google Login ด้านหน้าแล้ว · โปรดเลือกบัญชี Google และกดอนุญาตสิทธิ์ (หากถูกบัง ให้กลับไปที่ Song Studio แล้วกด เปิด Google Login อีกครั้ง)")
                self.show_pending_login()
                start = time.monotonic()
                while not signal.is_set() and time.monotonic() - start < 180:
                    if cancelled and cancelled.is_set():
                        raise GoogleError("ยกเลิก Google Login")
                    listener.handle_request()
            finally:
                with self.lock:
                    self.pending_auth_url = ""
                    self.pending_auth_stop = None
        if not signal.is_set():
            raise GoogleError("หมดเวลาลงชื่อเข้าใช้ Google (3 นาที)")
        if received.get("error"):
            raise GoogleError("Google ปฏิเสธการเข้าสู่ระบบ: " + received["error"])
        if not received.get("code"):
            raise GoogleError("ไม่ได้รับรหัสยืนยันจาก Google")
        payload = {"grant_type": "authorization_code",
                   "client_id": client["client_id"],
                   "code": received["code"],
                   "redirect_uri": redirect, "code_verifier": verifier}
        if client.get("client_secret"):
            payload["client_secret"] = client["client_secret"]
        result = self._token_exchange(payload)
        if not result.get("refresh_token"):
            raise GoogleError("Google ไม่ส่ง refresh token; ลองยกเลิกสิทธิ์แอปแล้วเชื่อมใหม่")
        with self.lock:
            self.client_id = client["client_id"]
            self.refresh_token = result["refresh_token"]
            self.access_token = result["access_token"]
            self.access_expires = time.time() + int(result.get("expires_in", 3600))
            about = self.api("/about", {"fields": "user(emailAddress,displayName)"})
            self.email = about.get("user", {}).get("emailAddress", "")
            self.last_error = ""
            self._save()
        return self.status()

    def api(self, route, query=None, *, method="GET", data=None):
        url = API + route
        if query:
            url += "?" + urllib.parse.urlencode(query)
        body = _json_bytes(data) if data is not None else None
        headers = {"Authorization": "Bearer " + self.token()}
        if body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        return _read_json(url, method=method, headers=headers, body=body)

    @staticmethod
    def _quoted(name):
        return name.replace("\\", "\\\\").replace("'", "\\'")

    def list_children(self, parent):
        results, token = [], ""
        while True:
            q = f"'{self._quoted(parent)}' in parents and trashed = false"
            args = {"q": q, "pageSize": 1000, "fields": "nextPageToken,files(id,name,mimeType,size,md5Checksum)",
                    "spaces": "drive"}
            if token:
                args["pageToken"] = token
            data = self.api("/files", args)
            results.extend(data.get("files", []))
            token = data.get("nextPageToken", "")
            if not token:
                return results

    def folder(self, parent, name):
        existing = [x for x in self.list_children(parent) if
                    x["name"] == name and x.get("mimeType") == "application/vnd.google-apps.folder"]
        if len(existing) > 1:
            raise GoogleError(
                "พบโฟลเดอร์ Google Drive ชื่อเดียวกันหลายรายการ · "
                "ไม่เลือกคลังเพลงแบบสุ่มเพื่อป้องกันฐานเพลงซ้ำ: " + name)
        if existing:
            return existing[0]["id"]
        item = self.api("/files", {"fields": "id,name"}, method="POST",
                        data={"name": name, "mimeType": "application/vnd.google-apps.folder",
                              "parents": [parent]})
        return item["id"]

    @staticmethod
    def _upload_session_request(session, mime_type, total, *, offset=0, data=None,
                                cancelled=None, on_progress=None):
        """One bounded HTTPS upload request or empty status probe.

        Google Drive acknowledges partial uploads with HTTP 308 and Range.
        Keep each body at most 8 MiB; do not load large M4A files into RAM.
        Never follow an untrusted session URL to another host.
        """
        import http.client
        endpoint = urllib.parse.urlsplit(session)
        if (endpoint.scheme != "https" or endpoint.hostname != "www.googleapis.com"
                or endpoint.port not in (None, 443)
                or endpoint.username is not None or endpoint.password is not None
                or not endpoint.path.startswith("/upload/drive/v3/")):
            raise GoogleError("Google คืน URL ของช่องอัปโหลดที่ไม่ได้รับอนุญาต")
        body = data if data is not None else b""
        if data is not None and not body:
            raise GoogleError("ส่วนข้อมูลที่อัปโหลดต้องไม่ว่าง")
        conn = http.client.HTTPSConnection(endpoint.hostname, endpoint.port or 443,
                                           timeout=120)
        try:
            resource = endpoint.path + ("?" + endpoint.query if endpoint.query else "")
            conn.putrequest("PUT", resource)
            conn.putheader("Content-Type", mime_type)
            conn.putheader("Content-Length", str(len(body)))
            if data is None:
                conn.putheader("Content-Range", f"bytes */{total}")
            else:
                conn.putheader("Content-Range",
                               f"bytes {offset}-{offset+len(body)-1}/{total}")
            conn.endheaders()
            if body:
                for index in range(0, len(body), 1024 * 1024):
                    if cancelled and cancelled.is_set():
                        raise GoogleError("ผู้ใช้ยกเลิกอัปโหลด Google Drive")
                    part = body[index:index + 1024 * 1024]
                    conn.send(part)
                    if on_progress:
                        on_progress(min(total, offset + index + len(part)), total)
            response = conn.getresponse()
            result = response.read(MAX_HTTP_RESPONSE + 1)
            if len(result) > MAX_HTTP_RESPONSE:
                raise GoogleError("Google Drive ส่งผลตอบกลับอัปโหลดใหญ่เกินกำหนด")
            return response.status, response.getheader("Range", ""), result
        finally:
            conn.close()

    @staticmethod
    def _acknowledged_upload_offset(header, total):
        if not header:
            return 0
        match = re.fullmatch(r"bytes=0-(\d+)", header.strip())
        if not match:
            raise GoogleError("Google Drive คืน Range ของการอัปโหลดไม่ถูกต้อง")
        offset = int(match.group(1)) + 1
        if offset < 0 or offset > total:
            raise GoogleError("Google Drive ยืนยันจำนวน byte เกินขนาดไฟล์")
        return offset

    def _resumable_put(self, path, parent, filename, replacing=None,
                       cancelled=None, on_progress=None):
        size = path.stat().st_size
        if size < 1:
            raise GoogleError("ไม่อนุญาตให้อัปโหลดไฟล์ว่าง")
        meta = {"name": filename,
                "mimeType": mimetypes.guess_type(filename)[0] or "application/octet-stream"}
        if not replacing:
            meta["parents"] = [parent]
        route = f"/files/{replacing}" if replacing else "/files"
        url = UPLOAD + route + "?" + urllib.parse.urlencode(
            {"uploadType": "resumable", "fields": "id,name,md5Checksum,size"})
        req = urllib.request.Request(
            url, method="PATCH" if replacing else "POST",
            data=_json_bytes(meta),
            headers={"Authorization": "Bearer " + self.token(),
                     "Content-Type": "application/json; charset=utf-8",
                     "X-Upload-Content-Type": meta["mimeType"],
                     "X-Upload-Content-Length": str(size)})
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                session = response.headers.get("Location", "")
        except urllib.error.HTTPError as exc:
            raise GoogleError(
                "เปิดช่องอัปโหลด Google Drive ไม่สำเร็จ: HTTP " + str(exc.code)) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise GoogleError("เชื่อมต่อ Google Drive เพื่อเริ่มอัปโหลดไม่ได้") from exc
        # Validated again in _upload_session_request, before any PUT.
        endpoint = urllib.parse.urlsplit(session)
        if (endpoint.scheme != "https" or endpoint.hostname != "www.googleapis.com"
                or endpoint.port not in (None, 443)
                or not endpoint.path.startswith("/upload/drive/v3/")):
            raise GoogleError("Google Drive ไม่คืน resumable upload URL ที่ปลอดภัย")

        cursor = 0
        retry = 0
        chunk_size = 8 * 1024 * 1024  # exact multiple of Drive's 256 KiB
        with path.open("rb") as source:
            while cursor < size:
                if cancelled and cancelled.is_set():
                    raise GoogleError("ผู้ใช้ยกเลิกอัปโหลด Google Drive")
                source.seek(cursor)
                chunk = source.read(min(chunk_size, size - cursor))
                if not chunk:
                    raise GoogleError("ไฟล์ต้นฉบับเปลี่ยนหรืออ่านไม่ครบระหว่างอัปโหลด")
                try:
                    status, acknowledged, raw = self._upload_session_request(
                        session, meta["mimeType"], size, offset=cursor,
                        data=chunk, cancelled=cancelled, on_progress=on_progress)
                    if status in (200, 201):
                        if cursor + len(chunk) < size:
                            raise GoogleError("Google Drive ตอบว่าอัปโหลดเสร็จก่อนรับไฟล์ครบ")
                        try:
                            response = json.loads(raw)
                        except (ValueError, UnicodeError) as exc:
                            raise GoogleError("ผลตอบกลับการอัปโหลดไม่ใช่ JSON") from exc
                        if not isinstance(response, dict) or not response.get("id"):
                            raise GoogleError("Google Drive ไม่ส่ง File ID หลังอัปโหลด")
                        return response
                    if status == 308:
                        next_cursor = self._acknowledged_upload_offset(
                            acknowledged, size)
                        if next_cursor > cursor + len(chunk):
                            raise GoogleError("Google Drive ตอบรับ byte มากกว่าที่ส่งไป")
                        if next_cursor > cursor:
                            cursor = next_cursor
                            retry = 0
                            continue
                        raise OSError("Google Drive ยังไม่ยืนยันข้อมูลของส่วนนี้")
                    if status not in (429, 500, 502, 503, 504):
                        raise GoogleError("อัปโหลด Google Drive ไม่สำเร็จ: HTTP " +
                                          str(status) + " · ไฟล์เดิมยังไม่ถูกเผยแพร่")
                    raise OSError("Google Drive ส่ง HTTP " + str(status))
                except (OSError, http.client.HTTPException) as exc:
                    if cancelled and cancelled.is_set():
                        raise GoogleError("ผู้ใช้ยกเลิกอัปโหลด Google Drive") from exc
                    retry += 1
                    if retry > 4:
                        raise GoogleError(
                            "การเชื่อมต่อ Google Drive ขัดข้องหลายครั้ง · "
                            "ยังไม่ได้เผยแพร่ current.json และจะตรวจซ้ำเมื่ออัปโหลดใหม่") from exc
                    seconds = min(2 ** (retry - 1), 8)
                    if on_progress:
                        on_progress(cursor, size)
                    if cancelled:
                        if cancelled.wait(seconds):
                            raise GoogleError("ผู้ใช้ยกเลิกอัปโหลด Google Drive")
                    else:
                        time.sleep(seconds)
                    # Query the SAME resumable session before retransmitting.
                    # A lost final response may mean the file is already
                    # complete; never create a second remote file in that case.
                    try:
                        status, acknowledged, raw = self._upload_session_request(
                            session, meta["mimeType"], size, cancelled=cancelled)
                        if status in (200, 201):
                            value = json.loads(raw)
                            if not isinstance(value, dict) or not value.get("id"):
                                raise GoogleError("Google Drive ไม่ส่ง File ID สำหรับไฟล์ที่อัปโหลดครบ")
                            return value
                        if status == 308:
                            cursor = self._acknowledged_upload_offset(
                                acknowledged, size)
                            if cursor >= size:
                                raise GoogleError("Google Drive ยืนยัน byte ครบแต่ไม่คืนสถานะสำเร็จ")
                        elif status not in (429, 500, 502, 503, 504):
                            raise GoogleError(
                                "Google Drive ไม่อนุญาตให้ทำต่อจากการอัปโหลดเดิม: HTTP " +
                                str(status))
                    except (OSError, http.client.HTTPException):
                        # The probe itself can fail transiently. Retry the
                        # probe next time, without switching the public DB.
                        continue
        raise GoogleError("อัปโหลดไม่สมบูรณ์ · Google Drive ยังไม่ยืนยันไฟล์")

    def upload_file(self, parent, path, name, *, replace_pointer=False, cancelled=None,
                    on_progress=None, existing_items=None):
        expected = hashlib.md5()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                expected.update(chunk)
        # Online bulk sync can pass one verified folder listing for the whole
        # batch, avoiding one Drive files.list request for every music file.
        children = self.list_children(parent) if existing_items is None else existing_items
        if isinstance(children, dict):
            # Online bulk sync passes a pre-indexed folder snapshot. Looking
            # up 10,000 songs by walking the entire folder for EACH upload
            # caused quadratic work; this reduces name lookup to O(1).
            candidates = children.get(name, [])
        else:
            candidates = [f for f in children if f.get("name") == name]
        matches = [f for f in candidates
                   if f.get("mimeType") != "application/vnd.google-apps.folder"]
        for match in matches:
            if match.get("md5Checksum", "").lower() == expected.hexdigest():
                return ("skipped", match)
        if matches and not replace_pointer:
            raise GoogleError("พบไฟล์ชื่อเดียวกันแต่เนื้อหาต่างกันบน Drive: " + name +
                              " — ไม่เขียนทับหรือสร้างซ้ำ")
        answer = self._resumable_put(path, parent, name,
                                     replacing=matches[0]["id"] if matches else None,
                                     cancelled=cancelled, on_progress=on_progress)
        if answer.get("md5Checksum", "").lower() != expected.hexdigest():
            raise GoogleError("Google Drive MD5 ไม่ตรงกับต้นฉบับ: " + name)
        return ("updated" if matches else "created", answer)

    def _download_verified(self, item, dest, *, rel="", cancelled=None, on_status=None):
        """Resume partial private Drive downloads, verify MD5 before publish.

        Partial files stay hidden and never appear in the song catalog. A
        retry uses HTTP Range only if the Google response confirms 206 and
        the exact expected offset. If Range is ignored, restart the transfer
        from byte zero instead of appending duplicated bytes.
        """
        expected = str(item.get("md5Checksum") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{32}", expected):
            raise GoogleError("Google Drive ไม่คืน MD5 ที่ตรวจสอบได้: " + rel)
        if not isinstance(item.get("id"), str) or not item["id"]:
            raise GoogleError("ไม่พบรหัสไฟล์ Google Drive: " + rel)
        partial = dest.with_name("." + dest.name + "." + expected[:16] + ".xstagepart")
        if partial.is_symlink() or (partial.exists() and not partial.is_file()):
            raise GoogleError("มีไฟล์ชั่วคราวที่ไม่ปลอดภัย: " + str(partial))
        if partial.exists() and file_md5(partial) == expected:
            if dest.exists():
                raise GoogleError("มีไฟล์ปลายทางอยู่แล้ว: " + str(dest))
            partial.replace(dest)
            return
        url = API + "/files/" + urllib.parse.quote(item["id"], safe="") + "?alt=media"
        import http.client
        for attempt in range(1, 5):
            if cancelled and cancelled.is_set():
                raise GoogleError("ผู้ใช้ยกเลิกดาวน์โหลด · เก็บข้อมูลชั่วคราวเพื่อทำต่อ")
            offset = partial.stat().st_size if partial.is_file() else 0
            if offset > (1 << 47):
                raise GoogleError("ไฟล์ดาวน์โหลดชั่วคราวใหญ่ผิดปกติ: " + rel)
            headers = {"Authorization": "Bearer " + self.token()}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            try:
                with _request(url, headers=headers, timeout=120) as response:
                    status = getattr(response, "status", None)
                    if status is None:
                        status = response.getcode() if hasattr(response, "getcode") else 200
                    if status not in (200, 206):
                        raise GoogleError("Google Drive ไม่ยอมรับคำขอดาวน์โหลด: HTTP " +
                                          str(status))
                    if offset and status == 206:
                        content_range = response.headers.get("Content-Range", "") if hasattr(response, "headers") else ""
                        if not content_range.startswith(f"bytes {offset}-"):
                            raise GoogleError("Google Drive ส่งช่วงข้อมูลไม่ตรงกับไฟล์ที่ดาวน์โหลดค้างไว้")
                    # Some proxies ignore Range and respond 200 with the
                    # complete resource. Replace the PARTIAL bytes, never
                    # append a second copy of the resource.
                    append = bool(offset and status == 206)
                    total = offset if append else 0
                    with partial.open("ab" if append else "wb") as sink:
                        while True:
                            if cancelled and cancelled.is_set():
                                raise GoogleError("ผู้ใช้ยกเลิกดาวน์โหลด · เก็บข้อมูลชั่วคราวเพื่อทำต่อ")
                            block = response.read(1024 * 1024)
                            if not block:
                                break
                            sink.write(block)
                            total += len(block)
                            if on_status and total % (16 * 1024 * 1024) < len(block):
                                on_status(f"ดาวน์โหลด {rel} · รับแล้ว {total // (1024 * 1024):,} MB")
                if file_md5(partial) != expected:
                    # A full successful HTTP response that disagrees with
                    # Drive's checksum is corrupt. Do not concatenate it on
                    # retry or publish the corrupted bytes.
                    partial.unlink(missing_ok=True)
                    raise GoogleError("MD5 ดาวน์โหลดไม่ตรง: " + rel)
                if dest.exists():
                    raise GoogleError("ไฟล์ปลายทางปรากฏระหว่างดาวน์โหลด: " + str(dest))
                partial.replace(dest)
                return
            except (GoogleError, OSError, http.client.HTTPException) as exc:
                if cancelled and cancelled.is_set():
                    raise
                message = str(exc)
                recoverable = not isinstance(exc, GoogleError) or (
                    message.startswith("เชื่อมต่อ Google ไม่สำเร็จ") or
                    any(("Google API HTTP " + str(code)) in message
                        for code in (429, 500, 502, 503, 504)))
                if not recoverable or attempt >= 4:
                    raise
                seconds = min(2 ** (attempt - 1), 8)
                if on_status:
                    on_status(f"การเชื่อมต่อขัดข้อง · ทำต่อไฟล์ {rel} "
                              f"ครั้งที่ {attempt + 1}/4 จาก {offset:,} bytes")
                if cancelled:
                    if cancelled.wait(seconds):
                        raise GoogleError("ผู้ใช้ยกเลิกดาวน์โหลด")
                else:
                    time.sleep(seconds)

    def _tree_folder(self, *, create=True):
        """Resolve the private library; downloads must NEVER create empty folders."""
        if create:
            root = self.folder("root", ROOT_NAME)
            return self.folder(root, "songs")

        def existing_folder(parent, name):
            matches = [item for item in self.list_children(parent)
                       if item.get("name") == name
                       and item.get("mimeType") == "application/vnd.google-apps.folder"]
            return matches[0]["id"] if matches else None

        root = existing_folder("root", ROOT_NAME)
        if not root:
            raise GoogleError(
                "ไม่พบโฟลเดอร์ '" + ROOT_NAME + "' ในไฟล์ที่แอปได้รับสิทธิ์ Google Drive "
                "(drive.file) · ตรวจสอบบัญชี Google/OAuth Client ที่ใช้ซิงค์เพลง "
                "หรือซิงค์คลังจาก Song Studio PC ก่อน · ไม่มีการสร้างโฟลเดอร์ใหม่")
        songs = existing_folder(root, "songs")
        if not songs:
            raise GoogleError(
                "พบโฟลเดอร์ '" + ROOT_NAME + "' แต่ไม่พบโฟลเดอร์ songs "
                "ที่แอปเข้าถึงได้ · ตรวจสอบการซิงค์เพลงและสิทธิ์ drive.file "
                "· ไม่มีการสร้างโฟลเดอร์ใหม่")
        return songs

    def _raw_library_download_plan(self, root_id, kind, *, library_name):
        """Read an existing categorized Drive tree without requiring current.json.

        A missing catalog means files can be backed up, NOT that their song
        metadata or code registry is verified. Never create/update Drive files.
        """
        folders = {"application/vnd.google-apps.folder"}
        records = []
        seen_paths = set()
        visited = set()
        max_items = 300000

        def walk(folder_id, prefix="", depth=0):
            if depth > 12 or folder_id in visited:
                raise GoogleError("โครงสร้างโฟลเดอร์ Drive ซ้อนลึกหรือวนซ้ำผิดปกติ")
            visited.add(folder_id)
            for item in self.list_children(folder_id):
                name = item.get("name")
                if (not isinstance(name, str) or name in ("", ".", "..")
                        or "/" in name or chr(92) in name or ":" in name
                        or any(ord(char) < 32 for char in name)):
                    raise GoogleError("ชื่อไฟล์หรือโฟลเดอร์ XStageWeb ไม่ปลอดภัย")
                relative = prefix + name
                if relative in seen_paths:
                    raise GoogleError("พบชื่อไฟล์ซ้ำใน XStageWeb: " + relative)
                seen_paths.add(relative)
                if len(seen_paths) > max_items:
                    raise GoogleError("พบไฟล์เกิน 300,000 รายการ · ต้องแบ่งการสำรองเป็นชุด")
                is_folder = item.get("mimeType") in folders
                if is_folder:
                    walk(item["id"], relative + "/", depth + 1)
                elif item.get("mimeType", "").startswith("application/vnd.google-apps."):
                    # Google native Docs are not binary song library files.
                    continue
                else:
                    is_db = (relative == "current.json" or relative.startswith("DB/")
                             or relative.startswith("catalog-") or
                             relative.startswith("database-"))
                    if kind == "db" and not is_db:
                        continue
                    if kind in ("songs", "zip") and relative.startswith(".xstage-"):
                        continue
                    if not item.get("md5Checksum"):
                        raise GoogleError("ไม่พบ MD5 สำหรับไฟล์บน Drive: " + relative)
                    records.append((relative, item))
        walk(root_id)
        if not records:
            if kind == "db":
                raise GoogleError("ไม่พบไฟล์ DB หรือ current.json ใน XStageWeb · "
                                  "ดาวน์โหลด Song หรือ ZIP ได้ แต่ยังไม่มีฐานเพลงให้กู้คืน")
            raise GoogleError("พบคลัง " + library_name +
                              " แต่ไม่พบไฟล์ที่แอปเข้าถึงได้ · "
                              "ตรวจสิทธิ์ Google Drive ของโฟลเดอร์และไฟล์ภายใน")
        records.sort(key=lambda x: x[0])
        return records, library_name

    def _online_download_plan(self, kind):
        """Plan a read-only, checksum-verified snapshot of XStageWeb.

        The actual Online publisher uses XStageWeb/current.json, with
        immutable catalogs and media referenced by private Google file IDs.
        The legacy Song Studio/songs path is a DIFFERENT backup format.
        """
        roots = [f for f in self.list_children("root")
                 if f.get("name") in ("StageWeb", "XStageWeb") and
                 f.get("mimeType") == "application/vnd.google-apps.folder"]
        if len(roots) > 1:
            raise GoogleError("พบ XStageWeb หลายคลังที่มองเห็นได้ · กรุณาเลือกคลังให้ชัดเจน")
        if not roots:
            return None
        library_name = roots[0]["name"]
        children = self.list_children(roots[0]["id"])
        pointers = [f for f in children if f.get("name") == "current.json"
                    and f.get("mimeType") != "application/vnd.google-apps.folder"]
        if len(pointers) > 1:
            raise GoogleError("พบ current.json ซ้ำใน XStageWeb · หยุดเพื่อป้องกันกู้คืนฐานผิด")
        if not pointers:
            # Existing user-organized AUDIO/VIDEO/MIDI/DB can be downloaded
            # as files even when the online catalog was never published.
            # This is a backup, not a playable song-code registry.
            return self._raw_library_download_plan(
                roots[0]["id"], kind, library_name=library_name)
        def checksum(value, label):
            if not isinstance(value, str) or not re.fullmatch("[0-9a-fA-F]{32}", value):
                raise GoogleError("ไม่พบ MD5 สำหรับตรวจสอบไฟล์: " + label)
            return value.lower()
        def read_json(item, label):
            expected = checksum(item.get("md5Checksum"), label)
            url = API + "/files/" + urllib.parse.quote(item["id"], safe="") + "?alt=media"
            try:
                with _request(url, headers={"Authorization": "Bearer " + self.token()},
                              timeout=120) as stream:
                    raw = stream.read(128 * 1024 * 1024 + 1)
            except GoogleError as exc:
                raise GoogleError("ไม่สามารถอ่าน " + label +
                                  " · ตรวจบัญชี Google และ OAuth Client ที่มีสิทธิ์ "
                                  "drive.file เข้าถึงไฟล์เดิม: " + str(exc)) from exc
            if len(raw) > 128 * 1024 * 1024 or hashlib.md5(raw).hexdigest() != expected:
                raise GoogleError(label + " มีขนาดหรือ MD5 ไม่ถูกต้อง")
            try:
                obj = json.loads(raw.decode("utf-8-sig"))
            except (ValueError, UnicodeError) as exc:
                raise GoogleError(label + " ไม่ใช่ JSON ที่สมบูรณ์") from exc
            if not isinstance(obj, dict):
                raise GoogleError(label + " มีโครงสร้างไม่ถูกต้อง")
            return obj
        pointer_file = pointers[0]
        pointer = read_json(pointer_file, library_name + "/current.json")
        base_id, deltas = pointer.get("catalogFileId"), pointer.get("deltaFileIds")
        count = pointer.get("songCount")
        if (pointer.get("schemaVersion") != 1 or not isinstance(base_id, str)
                or not base_id or not isinstance(deltas, list) or len(deltas) > 32
                or any(not isinstance(x, str) or not x for x in deltas)
                or len(set(deltas)) != len(deltas)
                or type(count) is not int or count < 0):
            raise GoogleError("โครงสร้าง XStageWeb/current.json ไม่ถูกต้อง")
        files, known = [], {}
        def add(relative, file_id, digest):
            if (not isinstance(relative, str) or not relative or
                    relative.startswith("/") or "\\" in relative or ":" in relative
                    or any(s in ("", ".", "..") for s in relative.split("/"))):
                raise GoogleError("พบพาธไฟล์ไม่ปลอดภัยใน XStageWeb")
            digest = checksum(digest, relative)
            if not isinstance(file_id, str) or not file_id:
                raise GoogleError("แค็ตตาล็อกไม่มี Drive File ID: " + relative)
            duplicate = known.get(relative)
            if duplicate is not None:
                if duplicate != (file_id, digest):
                    raise GoogleError("พาธไฟล์ซ้ำที่มีข้อมูลต่างกัน: " + relative)
                return
            known[relative] = (file_id, digest)
            files.append((relative, {"id": file_id, "md5Checksum": digest}))
        def catalog(file_id, prefix):
            try:
                meta = self.api("/files/" + urllib.parse.quote(file_id, safe=""),
                                {"fields": "id,name,mimeType,size,md5Checksum"})
            except GoogleError as exc:
                raise GoogleError("ไม่สามารถอ่าน Catalog XStageWeb เดิม · "
                                  "ตรวจบัญชี/OAuth Client และสิทธิ์ drive.file: " +
                                  str(exc)) from exc
            name = meta.get("name")
            if (not isinstance(name, str) or not name.startswith(prefix) or
                    not name.endswith(".json") or "/" in name or "\\" in name):
                raise GoogleError("ชื่อ Catalog ไม่ตรงกับ XStageWeb/current.json")
            doc = read_json(meta, library_name + "/" + name)
            add(("DB/" + name if pointer.get("layoutVersion") == 2 else name),
                file_id, meta.get("md5Checksum"))
            return doc
        base = catalog(base_id, "catalog-base-")
        if base.get("schemaVersion") != 1 or not isinstance(base.get("songs"), list):
            raise GoogleError("Catalog หลัก XStageWeb ไม่สมบูรณ์")
        songs = {}
        def row_id(row):
            if (not isinstance(row, dict) or
                    not isinstance(row.get("webSongId"), str) or not row["webSongId"]):
                raise GoogleError("Catalog มีรายการเพลงที่ไม่มี webSongId")
            return row["webSongId"]
        for row in base["songs"]:
            key = row_id(row)
            if key in songs:
                raise GoogleError("Catalog หลักมีรหัสเพลงซ้ำ")
            songs[key] = row
        for file_id in deltas:
            delta = catalog(file_id, "catalog-delta-")
            if (delta.get("schemaVersion") != 1 or
                    not isinstance(delta.get("upserts"), list) or
                    not isinstance(delta.get("removes"), list)):
                raise GoogleError("Catalog ส่วนเพิ่ม XStageWeb ไม่สมบูรณ์")
            for key in delta["removes"]:
                if not isinstance(key, str):
                    raise GoogleError("Catalog มีรหัสเพลงที่จะลบไม่ถูกต้อง")
                songs.pop(key, None)
            for row in delta["upserts"]:
                songs[row_id(row)] = row
        if len(songs) != count:
            raise GoogleError("จำนวนเพลงใน current.json และ Catalog ไม่ตรงกัน")
        if kind != "db":
            if not songs:
                raise GoogleError("XStageWeb ยังไม่มีเพลงที่เผยแพร่")
            for row in songs.values():
                for field, prefix in (
                    ("audio", "audio/"), ("lyrics", "lyrics/"),
                    ("lrc", "lyrics/"), ("vocals", "audio/"),
                ):
                    media = row.get(field)
                    if field in ("lrc", "vocals") and media is None:
                        continue
                    if not isinstance(media, dict):
                        raise GoogleError("Catalog มีเพลงที่ไม่มีไฟล์ " + field)
                    rel = media.get("path")
                    new_layout = (isinstance(rel, str) and
                                  rel.startswith("AUDIO/") and
                                  ("/Songs/" in rel if field in ("audio", "vocals")
                                   else "/Lyrics/" in rel))
                    if (not isinstance(rel, str) or
                            not (new_layout or rel.startswith(prefix) or
                                 rel.startswith("songs/" + prefix))):
                        raise GoogleError("พาธไฟล์ " + field + " ใน Catalog ไม่ถูกต้อง")
                    add(rel, media.get("fileId"), media.get("md5Checksum"))
        add("current.json", pointer_file["id"], pointer_file.get("md5Checksum"))
        return files, library_name

    def upload_library(self, local_songs, selected_records, cancelled=None, on_progress=None):
        """Upload completed selected songs, catalogs, then current.json LAST."""
        local_songs = Path(local_songs)
        if not (local_songs / "current.json").is_file():
            raise GoogleError("ยังไม่มี songs/current.json กรุณาสร้างเพลงก่อน")
        songs_dir = self._tree_folder()
        folder_cache = {"": songs_dir}
        def subdir(parts):
            parent = songs_dir
            key = ""
            for name in parts:
                key = (key + "/" + name).lstrip("/")
                if key not in folder_cache:
                    folder_cache[key] = self.folder(parent, name)
                parent = folder_cache[key]
            return parent
        files = {}
        for row in selected_records:
            for kind in ("audio", "lyrics", "vocals"):
                field = row.get(kind)
                if field and field.get("path"):
                    relative = field["path"]
                    files[relative] = False
                    if kind == "lyrics":
                        lrc = str(Path(relative).with_suffix(".lrc")).replace("\\", "/")
                        if (local_songs / lrc).is_file():
                            files[lrc] = False
        # Catalog snapshots and pointer must be uploaded after media; the
        # published pointer references ALL buckets and can be restored later.
        for path in sorted((local_songs / "catalogs").glob("*.json")):
            files[path.relative_to(local_songs).as_posix()] = False
        counts = {"created": 0, "skipped": 0, "updated": 0}
        for rel in sorted(files):
            if cancelled and cancelled.is_set():
                raise GoogleError("ผู้ใช้ยกเลิกอัปโหลด")
            file = local_songs / rel
            if not file.is_file() or not file.resolve().is_relative_to(local_songs.resolve()):
                raise GoogleError("ไม่พบไฟล์ที่จะส่ง Google Drive: " + rel)
            parts = Path(rel).parts
            status, _ = self.upload_file(subdir(parts[:-1]), file, parts[-1],
                                         cancelled=cancelled, on_progress=on_progress)
            counts[status] += 1
        pointer = local_songs / "current.json"
        status, _ = self.upload_file(songs_dir, pointer, "current.json",
                                     replace_pointer=True, cancelled=cancelled,
                                     on_progress=on_progress)
        counts[status] += 1
        return counts

    def download_library(self, target_root, kind="songs", cancelled=None, on_status=None,
                         on_item=None):
        if kind not in ("songs", "db", "zip"):
            raise GoogleError("ประเภทดาวน์โหลดไม่ถูกต้อง")
        target_root = Path(target_root)
        online = self._online_download_plan(kind)
        if online is not None:
            collected, library_name = online
        else:
            # Compatibility with an older, separately uploaded PC backup.
            # The current Karaoke Online uploader does NOT publish here.
            songs_folder = self._tree_folder(create=False)
            library_name = "songs"
            collected = []
            def walk(parent, prefix=""):
                for item in self.list_children(parent):
                    rel = f"{prefix}{item['name']}"
                    if (rel.startswith("/") or "\\" in rel or ":" in rel or
                            any(p in ("..", "") for p in rel.split("/"))):
                        raise GoogleError("พบพาธ Google Drive ที่ไม่ปลอดภัย")
                    if item.get("mimeType") == "application/vnd.google-apps.folder":
                        walk(item["id"], rel + "/")
                    elif kind != "db" or rel.startswith("catalogs/") or rel == "current.json":
                        collected.append((rel, item))
            walk(songs_folder)
            if not collected:
                raise GoogleError(
                    "พบโฟลเดอร์คลังเพลงสำรองแบบเก่า X-Stage Song Studio/songs ที่ว่าง "
                    "และไม่พบ XStageWeb ที่แอปมองเห็นได้ · การอัปโหลดปัจจุบันใช้ "
                    "XStageWeb/current.json ไม่ใช่ songs/current.json · "
                    "ตรวจบัญชี Google และ OAuth Client ของการซิงค์เดิม "
                    "· ห้ามสร้างคลังใหม่เพื่อแก้ข้อผิดพลาดนี้")
            if not any(rel == "current.json" for rel, _ in collected):
                raise GoogleError(
                    "คลังสำรองแบบเก่าไม่มี songs/current.json ที่เผยแพร่ครบ "
                    "· ไม่ดาวน์โหลดฐานที่อาจไม่สมบูรณ์")
        missing_hashes = [rel for rel, item in collected if not item.get("md5Checksum")]
        if missing_hashes:
            raise GoogleError(
                "Google Drive ไม่ส่ง MD5 สำหรับไฟล์ " + missing_hashes[0] +
                " · ไม่ดาวน์โหลดไฟล์ที่ตรวจความถูกต้องไม่ได้")
        if on_status:
            on_status("พบคลังเพลงบน Google Drive · " + str(len(collected)) +
                      " ไฟล์ · กำลังดาวน์โหลด " + kind.upper())
        base = (Path(tempfile.mkdtemp(prefix="xstage-drive-zip-")) if kind == "zip"
                else target_root / library_name if library_name in ("StageWeb", "XStageWeb")
                else target_root / "X-Stage Song Studio" / "songs")
        done = 0
        if on_item:
            on_item(0, len(collected))
        try:
            for rel, item in collected:
                if cancelled and cancelled.is_set():
                    raise GoogleError("ผู้ใช้ยกเลิกดาวน์โหลด")
                dest = base / rel
                if not dest.resolve().is_relative_to(base.resolve()):
                    raise GoogleError("พาธดาวน์โหลดไม่ปลอดภัย")
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.is_file() and item.get("md5Checksum"):
                    if file_md5(dest) == item["md5Checksum"]:
                        done += 1
                        if on_item:
                            on_item(done, len(collected))
                        continue
                    raise GoogleError("ไฟล์ในเครื่องชื่อเดียวกันแต่ต่างเนื้อหา: " + str(dest))
                self._download_verified(item, dest, rel=rel,
                                        cancelled=cancelled, on_status=on_status)
                done += 1
                if on_item:
                    on_item(done, len(collected))
                if on_status:
                    on_status(f"ดาวน์โหลด {done}/{len(collected)} · {rel}")
            if kind == "zip":
                if on_status:
                    on_status("ดาวน์โหลดครบและตรวจ MD5 แล้ว · กำลังประกอบ ZIP โดยไม่บีบอัด M4A ซ้ำ")
                target_root.mkdir(parents=True, exist_ok=True)
                name = ("X-Stage-Songs-" + time.strftime("%Y%m%d-%H%M%S") +
                        "-" + secrets.token_hex(4) + ".zip")
                out = target_root / name
                temp_zip = target_root / ("." + name + ".partial")
                try:
                    # M4A/MP3/AAC/FLAC are already compressed: ZIP_STORED
                    # avoids burning CPU compressing them a second time.
                    with zipfile.ZipFile(temp_zip, "x", allowZip64=True) as archive:
                        for f in base.rglob("*"):
                            if cancelled and cancelled.is_set():
                                raise GoogleError("ผู้ใช้ยกเลิกการสร้าง ZIP")
                            if f.is_file():
                                already_compressed = f.suffix.lower() in (
                                    ".m4a", ".mp3", ".aac", ".flac", ".mp4",
                                    ".ogg", ".opus", ".jpg", ".png")
                                archive.write(f,
                                    library_name + "/" + f.relative_to(base).as_posix(),
                                    compress_type=(zipfile.ZIP_STORED if already_compressed
                                                   else zipfile.ZIP_DEFLATED),
                                    compresslevel=(None if already_compressed else 4))
                    if out.exists():
                        raise GoogleError("ไฟล์ ZIP ปลายทางมีอยู่แล้ว: " + str(out))
                    temp_zip.replace(out)
                finally:
                    temp_zip.unlink(missing_ok=True)
                return {"files": done, "path": str(out), "source": library_name}
            return {"files": done, "path": str(base), "source": library_name}
        finally:
            if kind == "zip":
                shutil.rmtree(base, ignore_errors=True)


def file_md5(path):
    digest = hashlib.md5()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
