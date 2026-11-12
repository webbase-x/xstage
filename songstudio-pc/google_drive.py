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
import http.server
import io
import json
import mimetypes
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
    if not isinstance(data, dict) or not data.get("client_id", "").endswith(".apps.googleusercontent.com"):
        raise GoogleError("ต้องเป็น OAuth Client ประเภท Desktop app (ไม่ใช่ Web/Android Client)")
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
        """Save only PUBLIC desktop client configuration, never user tokens."""
        data = _read_client(filename)
        # Desktop OAuth clients are public and cannot keep secrets private.
        # We deliberately store only the ID: PKCE works without a secret.
        public = {"installed": {
            "client_id": data["client_id"],
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
                content = ("<!doctype html><meta charset=utf-8><title>X-Stage Song Studio</title>"
                           "<style>body{font:18px sans-serif;background:#102536;color:#d5faff;"
                           "padding:50px;text-align:center}</style>"
                           "<h2>เชื่อม Google Drive แล้ว</h2><p>กลับไปที่ X-Stage Song Studio PC ได้เลย</p>")
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
            if on_status:
                on_status("เปิด Google Browser เพื่อเลือกบัญชีและอนุญาตเข้าถึงไฟล์ที่ใช้กับแอป")
            if not webbrowser.open(url, new=1):
                raise GoogleError("ไม่สามารถเปิดเบราว์เซอร์สำหรับ Google Login ได้")
            start = time.monotonic()
            while not signal.is_set() and time.monotonic() - start < 180:
                if cancelled and cancelled.is_set():
                    raise GoogleError("ยกเลิก Google Login")
                listener.handle_request()
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
        if existing:
            return existing[0]["id"]
        item = self.api("/files", {"fields": "id,name"}, method="POST",
                        data={"name": name, "mimeType": "application/vnd.google-apps.folder",
                              "parents": [parent]})
        return item["id"]

    def _resumable_put(self, path, parent, filename, replacing=None, cancelled=None, on_progress=None):
        size = path.stat().st_size
        meta = {"name": filename, "mimeType": mimetypes.guess_type(filename)[0] or "application/octet-stream"}
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
                location = response.headers.get("Location", "")
        except urllib.error.HTTPError as exc:
            raise GoogleError("เปิดช่องอัปโหลด Google Drive ไม่สำเร็จ: HTTP " + str(exc.code)) from exc
        if not location.startswith("https://www.googleapis.com/"):
            raise GoogleError("Google Drive ไม่คืน resumable upload URL ที่ถูกต้อง")
        # Streaming PUT with http.client; avoid loading multi-GB M4A into RAM.
        import http.client
        endpoint = urllib.parse.urlsplit(location)
        conn = http.client.HTTPSConnection(endpoint.hostname, endpoint.port or 443, timeout=90)
        try:
            conn.putrequest("PUT", endpoint.path + ("?" + endpoint.query if endpoint.query else ""))
            conn.putheader("Content-Type", meta["mimeType"])
            conn.putheader("Content-Length", str(size))
            conn.endheaders()
            sent = 0
            with path.open("rb") as file:
                while True:
                    if cancelled and cancelled.is_set():
                        raise GoogleError("ผู้ใช้ยกเลิกอัปโหลด")
                    chunk = file.read(1024 * 1024)
                    if not chunk:
                        break
                    conn.send(chunk)
                    sent += len(chunk)
                    if on_progress:
                        on_progress(sent, size)
            answer = conn.getresponse()
            raw = answer.read(MAX_HTTP_RESPONSE + 1)
            if answer.status not in (200, 201):
                raise GoogleError("อัปโหลด Google Drive ไม่สำเร็จ: HTTP " + str(answer.status) +
                                  " " + raw[:300].decode("utf-8", "replace"))
            if len(raw) > MAX_HTTP_RESPONSE:
                raise GoogleError("ผลตอบกลับ Google Drive ใหญ่เกินกำหนด")
            return json.loads(raw)
        finally:
            conn.close()

    def upload_file(self, parent, path, name, *, replace_pointer=False, cancelled=None, on_progress=None):
        expected = hashlib.md5()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                expected.update(chunk)
        matches = [f for f in self.list_children(parent)
                   if f.get("name") == name and f.get("mimeType") != "application/vnd.google-apps.folder"]
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

    def _tree_folder(self):
        root = self.folder("root", ROOT_NAME)
        songs = self.folder(root, "songs")
        return songs

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

    def download_library(self, target_root, kind="songs", cancelled=None, on_status=None):
        if kind not in ("songs", "db", "zip"):
            raise GoogleError("ประเภทดาวน์โหลดไม่ถูกต้อง")
        target_root = Path(target_root)
        songs_folder = self._tree_folder()
        collected = []
        def walk(parent, prefix=""):
            for item in self.list_children(parent):
                rel = f"{prefix}{item['name']}"
                if rel.startswith("/") or any(p in ("..", "") for p in Path(rel).parts):
                    raise GoogleError("พบพาธ Google Drive ที่ไม่ปลอดภัย")
                if item.get("mimeType") == "application/vnd.google-apps.folder":
                    walk(item["id"], rel + "/")
                elif kind != "db" or rel.startswith("catalogs/") or rel == "current.json":
                    collected.append((rel, item))
        walk(songs_folder)
        if not collected:
            raise GoogleError("ไม่พบไฟล์คลังเพลงบน Google Drive ที่แอปมีสิทธิ์เข้าถึง")
        base = (Path(tempfile.mkdtemp(prefix="xstage-drive-zip-")) if kind == "zip"
                else target_root / "X-Stage Song Studio" / "songs")
        done = 0
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
                        continue
                    raise GoogleError("ไฟล์ในเครื่องชื่อเดียวกันแต่ต่างเนื้อหา: " + str(dest))
                url = API + "/files/" + urllib.parse.quote(item["id"], safe="") + "?alt=media"
                temp = dest.with_name("." + dest.name + ".download")
                try:
                    with _request(url, headers={"Authorization": "Bearer " + self.token()}, timeout=90) as response:
                        with temp.open("xb") as sink:
                            while True:
                                if cancelled and cancelled.is_set():
                                    raise GoogleError("ผู้ใช้ยกเลิกดาวน์โหลด")
                                part = response.read(1024 * 1024)
                                if not part:
                                    break
                                sink.write(part)
                    if item.get("md5Checksum") and file_md5(temp) != item["md5Checksum"]:
                        raise GoogleError("MD5 ดาวน์โหลดไม่ตรง: " + rel)
                    if dest.exists():
                        raise GoogleError("ไฟล์มีอยู่แล้ว: " + str(dest))
                    temp.replace(dest)
                finally:
                    temp.unlink(missing_ok=True)
                done += 1
                if on_status:
                    on_status(f"ดาวน์โหลด {done}/{len(collected)} · {rel}")
            if kind == "zip":
                target_root.mkdir(parents=True, exist_ok=True)
                name = "X-Stage-Songs-" + time.strftime("%Y%m%d-%H%M%S") + ".zip"
                out = target_root / name
                with zipfile.ZipFile(out, "x", zipfile.ZIP_DEFLATED,
                                     compresslevel=6, allowZip64=True) as archive:
                    for f in base.rglob("*"):
                        if f.is_file():
                            archive.write(f, "songs/" + f.relative_to(base).as_posix())
                return {"files": done, "path": str(out)}
            return {"files": done, "path": str(base)}
        finally:
            if kind == "zip":
                shutil.rmtree(base, ignore_errors=True)


def file_md5(path):
    digest = hashlib.md5()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
