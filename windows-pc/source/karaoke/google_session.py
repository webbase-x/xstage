"""Per-Windows-user Google Drive OAuth session persistence for the desktop app.

Only an offline refresh token is persisted, encrypted with Windows DPAPI.
The Desktop OAuth Client JSON stays in the user's Data folder, never in releases.
No music, catalog, access tokens or credentials are sent to the website.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import tempfile
import time
import urllib.parse

SESSION_FILE = 'xstage-google-session.dpapi'
HEADER = b'XSTAGE-DPAPI-1\n'


def _protect(data: bytes, *, decrypt=False) -> bytes:
    if os.name != 'nt':
        raise RuntimeError('การจดจำล็อกอินแบบเข้ารหัสรองรับ Windows เท่านั้น')
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_byte))]
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    protect = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    protect.argtypes = ([ctypes.POINTER(DATA_BLOB), ctypes.c_void_p,
                         ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
                         wintypes.DWORD, ctypes.POINTER(DATA_BLOB)] if decrypt else
                        [ctypes.POINTER(DATA_BLOB), ctypes.c_wchar_p,
                         ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
                         wintypes.DWORD, ctypes.POINTER(DATA_BLOB)])
    protect.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(data)
    incoming = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    output = DATA_BLOB()
    # 0x1: CRYPTPROTECT_UI_FORBIDDEN; no Windows UI from background workers.
    if not protect(ctypes.byref(incoming), None, None, None, None, 0x1, ctypes.byref(output)):
        raise OSError(ctypes.get_last_error(), 'Windows DPAPI ป้องกัน/ถอดรหัสเซสชันไม่สำเร็จ')
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))


def session_path(data_dir):
    return Path(data_dir) / SESSION_FILE


def has_saved_session(data_dir):
    return session_path(data_dir).is_file()


def save_session(data_dir, client_id, email, refresh_token):
    if not refresh_token:
        return False
    record = {'v':1, 'client_id':str(client_id), 'email':str(email),
              'refresh_token':str(refresh_token)}
    protected = HEADER + _protect(json.dumps(record, ensure_ascii=False).encode('utf-8'))
    target=session_path(data_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name=tempfile.mkstemp(prefix='.xstage-session-',dir=str(target.parent))
    try:
        with os.fdopen(fd,'wb') as output:
            output.write(protected)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name,target)
    finally:
        if os.path.exists(name):os.unlink(name)
    return True


def forget_session(data_dir):
    session_path(data_dir).unlink(missing_ok=True)


def load_session(data_dir):
    source=session_path(data_dir)
    if not source.is_file():return None
    raw=source.read_bytes()
    if not raw.startswith(HEADER):raise ValueError('ไฟล์เซสชัน Google ไม่รองรับหรือเสียหาย')
    record=json.loads(_protect(raw[len(HEADER):],decrypt=True).decode('utf-8'))
    if record.get('v')!=1 or not record.get('refresh_token') or not record.get('client_id'):
        raise ValueError('ข้อมูลเซสชัน Google ไม่ครบถ้วน')
    return record


def restore_session(home,data_dir,cancel=None):
    """Return (access_token, email, refresh_token, monotonic_expiry), or None."""
    record=load_session(data_dir)
    if not record:return None
    if cancel is not None and cancel.is_set():raise RuntimeError('ยกเลิก Google Login')
    from .google_drive_sync import load_client, _request
    client_id,client_secret=load_client(home,data_dir)
    if client_id != record['client_id']:
        raise RuntimeError('OAuth Client ไม่ตรงกับบัญชีที่จดจำ กรุณาเข้าสู่ระบบ Google ใหม่')
    fields={'client_id':client_id,'grant_type':'refresh_token','refresh_token':record['refresh_token']}
    if client_secret:fields['client_secret']=client_secret
    try:
        _,_,raw=_request('https://oauth2.googleapis.com/token', method='POST',
          body=urllib.parse.urlencode(fields).encode('ascii'),
          headers={'Content-Type':'application/x-www-form-urlencoded'},timeout=25)
    except RuntimeError as e:
        # Explicit Google revocation invalidates this stored session; do not remove for network errors.
        if 'invalid_grant' in str(e):forget_session(data_dir)
        raise
    value=json.loads(raw)
    token=value['access_token']
    if cancel is not None and cancel.is_set():raise RuntimeError('ยกเลิก Google Login')
    _,_,profile_raw=_request('https://openidconnect.googleapis.com/v1/userinfo',token,timeout=25)
    profile=json.loads(profile_raw)
    if not profile.get('email_verified') or not profile.get('email'):
        raise RuntimeError('Google ไม่ยืนยันอีเมลบัญชีนี้')
    if str(profile['email']).casefold()!=str(record['email']).casefold():
        forget_session(data_dir)
        raise RuntimeError('บัญชี Google เปลี่ยนแปลง กรุณาเข้าสู่ระบบใหม่')
    return token,profile['email'],record['refresh_token'],time.monotonic()+int(value.get('expires_in',3600))
