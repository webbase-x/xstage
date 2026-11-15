"""Google OAuth desktop sign-in and explicit, user-owned Drive snapshot upload.

Refresh tokens may be saved using Windows DPAPI by the desktop application.
The user's system browser handles initial sign-in; this module stores nothing itself.
"""
from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import secrets
import threading
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from .cloud_sync import _safe_user_id, create_snapshot

API = 'https://www.googleapis.com/drive/v3/files'
UPLOAD_API = 'https://www.googleapis.com/upload/drive/v3/files'
FOLDER_MIME = 'application/vnd.google-apps.folder'
ROOT_NAME = 'XStageKaraoke'
SCOPES = 'openid email https://www.googleapis.com/auth/drive.file'
CHUNK = 8 * 1024 * 1024


def _client_search_roots(home, data_dir):
    """Search bounded, known X-Stage installation folders; never scan whole disks.

    The current Data folder is first, followed by legacy X-Stage installations.
    User-selected credentials remain in Data and always take precedence.
    """
    import sys
    home, data_dir = Path(home), Path(data_dir)
    roots = [data_dir, home / 'Data', home / 'data', home,
             data_dir.parent / 'Data', data_dir.parent]
    if os.name == 'nt':
        roots += [Path('D:/newKaraoke/Data'), Path('D:/newKaraoke'),
                  Path('C:/newKaraoke/Data'), Path('C:/newKaraoke'),
                  Path(sys.executable).resolve().parent / 'Data',
                  Path(sys.executable).resolve().parent]
        for key in ('LOCALAPPDATA', 'APPDATA'):
            if os.environ.get(key):
                base = Path(os.environ[key])
                roots += [base / 'XStageKaraoke' / 'Data', base / 'XStageKaraoke',
                          base / 'X-Stage-Karaoke' / 'Data', base / 'newKaraoke' / 'Data']
    seen = set()
    for root in roots:
        key = str(root).casefold()
        if key not in seen:
            seen.add(key)
            yield root


def find_client_file(home, data_dir):
    """Find the OAuth Desktop JSON on disk without returning any credential data."""
    env = os.environ.get('XSTAGE_GOOGLE_OAUTH_JSON', '').strip()
    if env:
        path = Path(env).expanduser()
        if path.is_file():
            return path
    for root in _client_search_roots(home, data_dir):
        for path in (root / 'google-oauth-client.json', root / 'oauth-client.json'):
            if path.is_file():
                return path
        try:
            for path in sorted(root.glob('client_secret_*.json')):
                if path.is_file():
                    return path
        except OSError:
            continue
    return None


def load_client(home, data_dir):
    """Load the pre-existing Desktop OAuth JSON; never package a real secret."""
    path = find_client_file(home, data_dir)
    if path is None:
        data = {'client_id': os.environ.get('XSTAGE_GOOGLE_CLIENT_ID', ''),
                'client_secret': os.environ.get('XSTAGE_GOOGLE_CLIENT_SECRET', '')}
    else:
        try:
            raw = json.loads(path.read_text(encoding='utf-8-sig'))
        except (ValueError, OSError) as error:
            raise ValueError(f'อ่านไฟล์ OAuth JSON เดิมไม่สำเร็จ ({path.name}): {error}') from error
        if not isinstance(raw, dict):
            raise ValueError(f'โครงสร้าง OAuth JSON ไม่ถูกต้อง ({path.name})')
        if 'web' in raw and 'installed' not in raw:
            raise ValueError('ไฟล์ OAuth นี้เป็น Web Client; Windows ต้องใช้ OAuth Desktop Client')
        data = raw.get('installed', raw)
        if not isinstance(data, dict):
            raise ValueError('โครงสร้าง OAuth Desktop Client ไม่ถูกต้อง')
    client_id = str(data.get('client_id') or '').strip()
    if not client_id.endswith('.apps.googleusercontent.com'):
        raise ValueError('ไม่พบ Google OAuth Desktop Client: วาง google-oauth-client.json ใน Data ของ X-Stage Windows')
    return client_id, str(data.get('client_secret') or '')


def _request(url, token='', method='GET', body=None, headers=None, timeout=45):
    request = urllib.request.Request(url, data=body, method=method,
        headers=({'Authorization': 'Bearer ' + token} if token else {}) | (headers or {}))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        detail = error.read(1000).decode('utf-8', 'replace')
        raise RuntimeError(f'Google API ตอบกลับ HTTP {error.code}: {detail}') from error


def sign_in(client_id, client_secret='', cancel=None):
    """PKCE + loopback callback; returns only a short-lived token and verified email."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')
    state = secrets.token_urlsafe(32)
    answer = {}

    def verify_account():
        if 'error' in answer:
            raise RuntimeError('Google Login ไม่สำเร็จ: ' + answer['error'])
        if not answer.get('code'):
            raise RuntimeError('Google ไม่ส่งรหัสยืนยันกลับมา')
        fields = {'client_id': client_id, 'code': answer['code'], 'code_verifier': verifier,
                  'redirect_uri': redirect, 'grant_type': 'authorization_code'}
        if client_secret:
            fields['client_secret'] = client_secret
        _, _, raw = _request('https://oauth2.googleapis.com/token', method='POST',
            body=urllib.parse.urlencode(fields).encode('ascii'),
            headers={'Content-Type': 'application/x-www-form-urlencoded'})
        credentials = json.loads(raw)
        token = credentials['access_token']
        _, _, raw = _request('https://openidconnect.googleapis.com/v1/userinfo', token)
        profile = json.loads(raw)
        if not profile.get('email_verified') or not profile.get('email'):
            raise RuntimeError('Google ไม่ยืนยันอีเมลบัญชีนี้')
        return token, profile['email'], credentials.get('refresh_token'), time.monotonic() + int(credentials.get('expires_in', 3600))

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            if query.get('state', [''])[0] != state:
                self.send_error(400, 'Invalid state')
                return
            answer.update({key: values[0] for key, values in query.items()})
            try:
                answer['session'] = verify_account()
            except Exception as error:
                answer['failure'] = error
            close_tab = 'window.close();' if 'session' in answer else ''
            payload = ('<!doctype html><html lang="th"><meta charset="utf-8">'
                       '<script>history.replaceState(null, "", "/");' + close_tab + '</script>'
                       '<body><p>ปิดแท็บนี้แล้วกลับไปที่ X-Stage Karaoke</p>'
                       '</body></html>').encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_):
            pass

    server = HTTPServer(('127.0.0.1', 0), Callback)
    server.timeout = 1
    redirect = f'http://127.0.0.1:{server.server_port}/'
    parameters = urllib.parse.urlencode({
        'client_id': client_id, 'redirect_uri': redirect, 'response_type': 'code',
        'scope': SCOPES, 'state': state, 'code_challenge': challenge,
        'code_challenge_method': 'S256', 'access_type': 'offline', 'prompt': 'consent select_account',
    })
    try:
        if not webbrowser.open('https://accounts.google.com/o/oauth2/v2/auth?' + parameters):
            raise RuntimeError('เปิดเบราว์เซอร์สำหรับ Google Login ไม่สำเร็จ')
        until = time.monotonic() + 180
        while not answer and time.monotonic() < until:
            if cancel is not None and cancel.is_set():
                raise RuntimeError('ยกเลิกการเข้าสู่ระบบ Google')
            server.handle_request()
    finally:
        server.server_close()
    if not answer:
        raise TimeoutError('หมดเวลารอ Google Login')
    if 'failure' in answer:
        raise answer['failure']
    return answer['session']


class Drive:
    def __init__(self, token, cancel=None, client_id='', client_secret='', refresh_token=None, expires_at=None):
        self.token = token
        self.cancel = cancel
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.expires_at = expires_at
        # R18 uploads multiple songs in parallel. Only one thread may refresh
        # shared OAuth credentials; concurrent refresh requests can revoke or
        # race the usable token on a long-running Windows sync.
        self._token_lock = threading.RLock()

    def check_cancelled(self):
        if self.cancel is not None and self.cancel.is_set():
            raise RuntimeError('ยกเลิกการซิงค์ Google Drive')

    def access_token(self):
        self.check_cancelled()
        with self._token_lock:
            if self.expires_at is not None and time.monotonic() >= self.expires_at - 120:
                if not self.refresh_token:
                    raise RuntimeError('Google Login หมดอายุ กรุณาเข้าสู่ระบบใหม่')
                fields = {'client_id': self.client_id, 'refresh_token': self.refresh_token,
                          'grant_type': 'refresh_token'}
                if self.client_secret:
                    fields['client_secret'] = self.client_secret
                _, _, raw = _request('https://oauth2.googleapis.com/token', method='POST',
                    body=urllib.parse.urlencode(fields).encode('ascii'),
                    headers={'Content-Type': 'application/x-www-form-urlencoded'})
                result = json.loads(raw)
                self.token = result['access_token']
                self.expires_at = time.monotonic() + int(result.get('expires_in', 3600))
            return self.token

    def json(self, url, method='GET', data=None):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8') if data is not None else None
        _, _, raw = _request(url, self.access_token(), method, body,
            {'Content-Type': 'application/json; charset=utf-8'} if body is not None else None)
        return json.loads(raw) if raw else {}

    def children(self, parent, name=None):
        query = f"'{parent}' in parents and trashed = false"
        if name is not None:
            query += " and name = '" + name.replace('\\', '\\\\').replace("'", "\\'") + "'"
        files = []
        page = ''
        while True:
            self.check_cancelled()
            params = {'q': query, 'fields': 'nextPageToken,files(id,name,mimeType,md5Checksum,size,modifiedTime)',
                      'pageSize': '1000'}
            if page:
                params['pageToken'] = page
            result = self.json(API + '?' + urllib.parse.urlencode(params))
            files.extend(result.get('files', []))
            page = result.get('nextPageToken', '')
            if not page:
                return files

    def folder(self, parent, name):
        matches = [item for item in self.children(parent, name) if item['mimeType'] == FOLDER_MIME]
        if len(matches) > 1:
            raise RuntimeError(f'มีโฟลเดอร์ชื่อ {name} ซ้ำใน Google Drive กรุณาจัดการก่อนซิงค์')
        if matches:
            return matches[0]
        return self.json(API + '?fields=id,name,mimeType', 'POST',
            {'name': name, 'mimeType': FOLDER_MIME, 'parents': [parent]})

    def inspect(self, email):
        roots = [item for item in self.children('root')
                 if item['name'] == ROOT_NAME and item['mimeType'] == FOLDER_MIME]
        if len(roots) > 1:
            raise RuntimeError('พบโฟลเดอร์ XStageKaraoke มากกว่าหนึ่งแห่ง กรุณาจัดการชื่อซ้ำก่อนซิงค์')
        root = roots[0] if roots else None
        snapshots = []
        if root:
            users = [item for item in self.children(root['id'], 'users') if item['mimeType'] == FOLDER_MIME]
            if len(users) > 1:
                raise RuntimeError('พบโฟลเดอร์ users ซ้ำใน Google Drive')
            if users:
                account = [item for item in self.children(users[0]['id'], _safe_user_id(email)) if item['mimeType'] == FOLDER_MIME]
                if len(account) > 1:
                    raise RuntimeError('พบโฟลเดอร์บัญชีซ้ำใน Google Drive')
                if account:
                    for item in self.children(account[0]['id']):
                        if item['mimeType'] != FOLDER_MIME:
                            continue
                        contents = self.children(item['id'])
                        children = {child['name'] for child in contents}
                        required = {'Songs', 'Fx', 'database', 'web-manifest.json', 'manifest.json'}
                        missing = sorted(required - children)
                        database = next((child for child in contents if child['name'] == 'database'
                                         and child['mimeType'] == FOLDER_MIME), None)
                        if database:
                            db_files = {child['name'] for child in self.children(database['id'])}
                            missing.extend('database/' + name for name in
                                sorted({'songs.sqlite3', 'settings.json', 'queue.json'} - db_files))
                        snapshots.append({'id': item['id'], 'name': item['name'], 'missing': missing})
        snapshots.sort(key=lambda item: item['name'], reverse=True)
        return {'root': root, 'snapshots': snapshots, 'latest': snapshots[0] if snapshots else None}

    @staticmethod
    def _received_offset(headers, size):
        """Validate Google's inclusive Range acknowledgement on HTTP 308."""
        value = (headers.get('Range', '') if headers else '').strip()
        if not value:
            return 0  # 308 without Range means no bytes are acknowledged.
        import re
        found = re.fullmatch(r'bytes=0-(\d+)', value)
        if not found:
            raise IOError('Google Drive ส่ง Range อัปโหลดไม่ถูกต้อง')
        offset = int(found.group(1)) + 1
        if offset < 0 or offset > size:
            raise IOError('Google Drive ส่งตำแหน่งอัปโหลดเกินขนาดไฟล์')
        return offset

    def _upload_status(self, session_url, size):
        """Query an interrupted live resumable session before retransmission.

        Session URLs are bearer-capability secrets. They stay in memory only,
        never in the SQLite journal, logs, or user-visible error messages.
        A restarted process resumes *verified songs* using its journal and
        reuses complete remote files; an unfinished chunk gets a new session.
        """
        request = urllib.request.Request(session_url, data=b'', method='PUT',
            headers={'Authorization': 'Bearer ' + self.access_token(),
                     'Content-Length': '0', 'Content-Range': f'bytes */{size}'})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                if response.status in (200, 201):
                    return size, json.loads(response.read())
                raise IOError('Google Drive คืนสถานะอัปโหลดที่ไม่รองรับ')
        except urllib.error.HTTPError as error:
            if error.code != 308:
                raise
            return self._received_offset(error.headers, size), None

    def _upload(self, path, parent, existing=None):
        self.check_cancelled()
        path = Path(path)
        size = path.stat().st_size
        mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        metadata = {'name': path.name, 'parents': [parent]} if existing is None else {'name': path.name}
        url = UPLOAD_API + ('/' + urllib.parse.quote(existing['id']) if existing else '')
        url += '?uploadType=resumable&fields=id,name,md5Checksum,size'
        method = 'PATCH' if existing else 'POST'
        _, headers, _ = _request(url, self.access_token(), method,
            json.dumps(metadata, ensure_ascii=False).encode('utf-8'),
            {'Content-Type': 'application/json; charset=utf-8', 'X-Upload-Content-Type': mime,
             'X-Upload-Content-Length': str(size)})
        location = headers.get('Location')
        if not location or not location.startswith('https://'):
            raise RuntimeError('Google Drive ไม่ส่ง URL สำหรับอัปโหลด')
        with path.open('rb') as stream:
            if size == 0:
                _, _, raw = _request(location, self.access_token(), 'PUT', b'',
                    {'Content-Type': mime, 'Content-Length': '0'})
                return json.loads(raw)
            offset = 0
            while offset < size:
                self.check_cancelled()
                stream.seek(offset)
                block = stream.read(min(CHUNK, size - offset))
                if not block:
                    raise IOError('อ่านข้อมูลไฟล์ระหว่างอัปโหลดไม่ครบ')
                chunk_headers = {'Content-Type': mime,
                    'Content-Range': f'bytes {offset}-{offset + len(block) - 1}/{size}'}
                for attempt in range(4):
                    self.check_cancelled()
                    request = urllib.request.Request(location, data=block, method='PUT',
                        headers={'Authorization': 'Bearer ' + self.access_token()} | chunk_headers)
                    try:
                        with urllib.request.urlopen(request, timeout=120) as response:
                            if response.status not in (200, 201):
                                raise IOError('Google Drive คืนผลอัปโหลดไม่ถูกต้อง')
                            return json.loads(response.read())
                    except urllib.error.HTTPError as error:
                        if error.code == 308:
                            new_offset = self._received_offset(error.headers, size)
                            # A 308 with an invalid forward acknowledgement must
                            # never cause a loop or treat missing bytes as sent.
                            if new_offset > offset + len(block):
                                raise IOError('Google Drive ยืนยันจำนวนไบต์เกินที่ส่ง')
                            if new_offset > offset:
                                offset = new_offset
                                break
                        elif error.code not in (429, 500, 502, 503, 504):
                            raise RuntimeError(f'อัปโหลด {path.name} ไม่สำเร็จ: HTTP {error.code}') from error
                    except (TimeoutError, OSError):
                        pass  # Connection uncertain: query acknowledged offset.
                    if attempt == 3:
                        raise RuntimeError(f'อัปโหลด {path.name} ไม่สำเร็จหลังลองซ้ำ')
                    time.sleep(2 ** attempt)
                    try:
                        new_offset, finished = self._upload_status(location, size)
                    except urllib.error.HTTPError as error:
                        if error.code not in (429, 500, 502, 503, 504):
                            raise RuntimeError(f'ตรวจสถานะอัปโหลด {path.name} ไม่สำเร็จ: HTTP {error.code}') from error
                        continue
                    except (TimeoutError, OSError):
                        continue
                    if finished is not None:
                        return finished
                    if new_offset > offset + len(block):
                        raise IOError('Google Drive ยืนยันจำนวนไบต์เกินที่ส่ง')
                    if new_offset > offset:
                        offset = new_offset
                        break
                else:
                    raise RuntimeError(f'อัปโหลด {path.name} ไม่สำเร็จ')
            # The last 308 may acknowledge all bytes but lose the final reply.
            # Ask the server for the final object rather than blindly advancing.
            position, completed = self._upload_status(location, size)
            if completed is not None:
                return completed
            raise RuntimeError(f'Google Drive ยังไม่ยืนยันไฟล์ {path.name} ที่ส่งครบ')

    def upload_visible_files(self, source_files, snapshot_id, progress=None, *, proofs=None):
        """Upload only catalog-visible media, directly from original paths.

        This avoids a second, giant temporary Songs copy on the local disk.
        Remote files not in the new manifest are retained, never auto-deleted.
        """
        songs_folder = self.folder(snapshot_id, 'Songs')['id']
        folder_cache = {'': songs_folder}
        listing_cache = {}
        for relative, source in sorted(source_files.items()):
            self.check_cancelled()
            components = relative.replace('\\','/').split('/')
            if not components or any(c in ('','.','..') for c in components):
                raise ValueError('เส้นทางเพลงใน Manifest ไม่ถูกต้อง')
            path = Path(source)
            if not path.is_file() or path.is_symlink():
                raise ValueError('ไฟล์เพลงหายหรือเป็นลิงก์: ' + str(path))
            for depth in range(1, len(components)):
                folder_key = '/'.join(components[:depth])
                if folder_key not in folder_cache:
                    parent_key = '/'.join(components[:depth-1])
                    folder_cache[folder_key] = self.folder(folder_cache[parent_key],components[depth-1])['id']
            parent_key = '/'.join(components[:-1])
            target = folder_cache[parent_key]
            if target not in listing_cache:
                listing_cache[target] = {f['name']:f for f in self.children(target)}
            existing = listing_cache[target].get(components[-1])
            if existing and existing['mimeType'] == FOLDER_MIME:
                raise ValueError('ชื่อไฟล์และโฟลเดอร์ชนกันบน Google Drive')
            if proofs is not None:
                # The staging pass already hashed this exact source file. Reuse
                # that proof to avoid another full disk read; verification after
                # upload still re-hashes the source and checks Drive's checksum.
                expected = proofs.get(relative)
                if not isinstance(expected, dict) or not isinstance(expected.get('md5'), str):
                    raise ValueError('ไม่มีค่า MD5 สำหรับไฟล์เพลงในแผนซิงก์: '+relative)
                md5_digest = expected['md5']
            else:
                md5 = hashlib.md5()
                with path.open('rb') as inp:
                    for block in iter(lambda: inp.read(1024*1024), b''):
                        self.check_cancelled(); md5.update(block)
                md5_digest = md5.hexdigest()
            if not existing or existing.get('md5Checksum') != md5_digest:
                result = self._upload(path, target, existing)
                # Our content name may differ from the source on rare aliases;
                # the default planner normally preserves the basename.
                if path.name != components[-1]:
                    self.json(API + '/' + urllib.parse.quote(result['id']), 'PATCH',
                              {'name':components[-1]})
            if progress:
                progress(relative)

    def verify_visible_files(self, source_files, proofs, snapshot_id):
        """Verify remote file metadata against locally hashed media proofs."""
        root=self.folder(snapshot_id,'Songs')['id']
        cache={'':root};children_cache={}
        for relative in sorted(source_files):
            if relative not in proofs:
                raise RuntimeError('ไฟล์ในแผนอัปโหลดไม่มีหลักฐาน SHA-256: '+relative)
            components=relative.split('/')
            if any(not c or c in ('.','..') for c in components):
                raise ValueError('ชื่อไฟล์ใน Manifest ไม่ปลอดภัย')
            for depth in range(1,len(components)):
                prefix='/'.join(components[:depth]);parent='/'.join(components[:depth-1])
                if prefix not in cache:
                    options=[x for x in self.children(cache[parent],components[depth-1]) if x['mimeType']==FOLDER_MIME]
                    if len(options)!=1:
                        raise RuntimeError('ไม่พบโฟลเดอร์เพลงบน Google Drive: '+prefix)
                    cache[prefix]=options[0]['id']
            folder=cache['/'.join(components[:-1])]
            if folder not in children_cache:
                children_cache[folder]=self.children(folder)
            candidates=[x for x in children_cache[folder] if x['name']==components[-1] and x['mimeType']!=FOLDER_MIME]
            if len(candidates)!=1:
                raise RuntimeError('ไฟล์เพลงบน Drive หายหรือชื่อซ้ำ: '+relative)
            item=candidates[0]; expected=proofs[relative]
            if item.get('md5Checksum')!=expected['md5']:
                raise RuntimeError('ไฟล์บน Drive มี MD5 ไม่ตรงกับต้นทาง: '+relative)
            if item.get('size') is not None and int(item['size'])!=expected['size']:
                raise RuntimeError('ขนาดไฟล์บน Drive ไม่ตรง: '+relative)
            # The original source cannot change between upload and publication.
            from .cloud_sync import _media_proof
            if _media_proof(source_files[relative])!=expected:
                raise RuntimeError('ต้นทางเปลี่ยนขณะซิงก์เพลง: '+relative)
        return len(source_files)

    def upload_tree(self, local, remote, progress=None):
        """Upsert by name and checksum. Publish web-manifest.json last."""
        local = Path(local)
        children = {item['name']: item for item in self.children(remote)}
        files = sorted(local.iterdir(), key=lambda p: (p.name == 'web-manifest.json', p.name.casefold()))
        for path in files:
            self.check_cancelled()
            if path.is_dir():
                item = children.get(path.name)
                if item and item['mimeType'] != FOLDER_MIME:
                    raise RuntimeError('ชื่อไฟล์และโฟลเดอร์ชนกันใน Drive: ' + path.name)
                folder = item or self.folder(remote, path.name)
                self.upload_tree(path, folder['id'], progress)
            elif path.is_file():
                item = children.get(path.name)
                if item and item['mimeType'] == FOLDER_MIME:
                    raise RuntimeError('ชื่อไฟล์และโฟลเดอร์ชนกันใน Drive: ' + path.name)
                checksum = hashlib.md5()
                with path.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        self.check_cancelled()
                        checksum.update(chunk)
                if path.name == 'web-manifest.json' or not item or item.get('md5Checksum') != checksum.hexdigest():
                    self._upload(path, remote, item)
                if progress:
                    progress(path.name)


def sync_library(drive, data_dir, email, song_roots, fx_root, mode, existing=None, progress=None, *, upload_progress=None):
    """Stage a consistent SQLite backup locally, then upload it to the chosen Drive snapshot."""
    with tempfile.TemporaryDirectory(prefix='xstage-drive-') as temporary:
        def staging_progress(label, count):
            drive.check_cancelled()
            if progress:
                progress(f'{label}: {count:,}')
        source_files = {}
        snapshot = create_snapshot(data_dir, Path(temporary), email, song_roots, fx_root,
                                   staging_progress, stage_media=False,
                                   media_files_out=source_files)
        root = drive.folder('root', ROOT_NAME)
        users = drive.folder(root['id'], 'users')
        account = drive.folder(users['id'], _safe_user_id(email))
        if mode == 'update' and existing:
            remote = existing
        elif mode == 'new':
            remote = drive.folder(account['id'], snapshot.name)
        else:
            raise ValueError('โหมดการซิงค์ไม่ถูกต้อง')
        total = 0
        if upload_progress:
            for path in snapshot.rglob('*'):
                drive.check_cancelled()
                total += path.is_file()
            total += len(source_files)
            upload_progress('', 0, total)
        done = 0

        def file_done(name):
            nonlocal done
            done += 1
            if progress:
                progress(name)
            if upload_progress:
                upload_progress(name, done, total)

        # Media are pushed before publishing the web manifest, so a partially
        # uploaded snapshot is never advertised as a complete song listing.
        proofs=json.loads((snapshot/'web-manifest.json').read_text(encoding='utf-8'))['files']
        drive.upload_visible_files(source_files, remote['id'], file_done, proofs=proofs)
        drive.verify_visible_files(source_files, proofs, remote['id'])
        # Publish metadata only after remote media checks are complete.
        drive.upload_tree(snapshot, remote['id'], file_done)
        if progress:
            progress('กำลังตรวจสอบชุดข้อมูลบน Google Drive…')
        verified = next((item for item in drive.inspect(email)['snapshots']
                         if item['id'] == remote['id']), None)
        if verified is None or verified['missing']:
            raise RuntimeError('ตรวจสอบชุดข้อมูลบน Google Drive หลังอัปโหลดไม่ผ่าน: '
                               + ', '.join(verified['missing'] if verified else ['ไม่พบชุดข้อมูล']))
        return {'root_id': root['id'], 'snapshot_id': remote['id'], 'name': remote['name']}
