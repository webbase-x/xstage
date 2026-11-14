"""Crash-safe local progress marker for the X-Stage Online conversion window.

This is deliberately *not* a cursor into a mutable song list. On restart the
current SQLite catalog is rescanned and verified; completed uploads can be
reused from web_drive's account-scoped verified journal. This marker only
restores the user's selection and tells them what was interrupted. No Google
credentials, audio, or song file contents are ever persisted here.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
import time
from datetime import datetime, timezone

FILE_NAME = 'online-sync-recovery.json'
MAX_SIZE = 64 * 1024
VALID_STATUSES = frozenset({'scanning', 'ready', 'running', 'cancelled', 'failed', 'completed'})


def _atomic_json(path: Path, value: dict) -> None:
    """Use fsync and same-directory replace so abrupt loss leaves old/new JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode('utf-8')
    if len(data) > MAX_SIZE:
        raise ValueError('บันทึกสถานะซิงค์มีขนาดเกินกำหนด')
    fd, temporary = tempfile.mkstemp(prefix='.xstage-web-resume-', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class OnlineSyncRecovery:
    def __init__(self, cache_dir):
        self.path = Path(cache_dir) / FILE_NAME
        self.lock = threading.RLock()
        self.last_write = 0.0
        self.last_persisted_done = 0
        self.state = self.load(self.path)

    @staticmethod
    def load(path):
        path = Path(path)
        try:
            if path.stat().st_size > MAX_SIZE:
                raise ValueError('ไฟล์กู้คืนใหญ่ผิดปกติ')
            raw = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(raw, dict) or raw.get('schema') != 1 or raw.get('status') not in VALID_STATUSES:
                raise ValueError('ไฟล์กู้คืนรุ่นนี้ไม่รองรับ')
            raw['done'] = max(0, int(raw.get('done', 0)))
            raw['total'] = max(0, int(raw.get('total', 0)))
            raw['step'] = max(1, min(5, int(raw.get('step', 1))))
            raw['song_types'] = sorted(set(raw.get('song_types', [])) & {'NCN', 'MIDI'})
            raw['font'] = str(raw.get('font') or '')[:1200]
            raw['message'] = str(raw.get('message') or '')[:180]
            return raw
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
            # Do not overwrite corrupt/unrecognized prior state by guessing;
            # users retain the old file for forensic troubleshooting.
            return None

    def _save(self, force=True):
        self.state['updated_at'] = datetime.now(timezone.utc).isoformat()
        current = time.monotonic()
        if force or current - self.last_write >= 1.5 or abs(self.state.get('done', 0)-self.last_persisted_done)>=25:
            _atomic_json(self.path, self.state)
            self.last_write = current
            self.last_persisted_done = self.state.get('done', 0)

    def begin(self, *, song_types, font='', total=0, stage='ตรวจ SoundFont'):
        with self.lock:
            self.state = {'schema': 1, 'status': 'running', 'step': 2,
                          'message': str(stage)[:180], 'song_types': sorted(set(song_types)&{'NCN','MIDI'}),
                          'font': str(font or '')[:1200], 'done': 0, 'total': max(0, int(total))}
            self._save()

    def scanning(self, *, done=0, total=0):
        with self.lock:
            # Do not replace a meaningful interrupted upload checkpoint just
            # because the window is rescanning the song database for its UI.
            if self.state and self.state.get('status') in {'running', 'failed', 'cancelled'}:
                return
            self.state = {'schema': 1, 'status': 'scanning', 'step': 1,
                          'message': 'กำลังตรวจเพลงในฐาน SQLite',
                          'song_types': ['MIDI','NCN'], 'font': '',
                          'done': max(0, int(done)), 'total': max(0, int(total))}
            self._save(force=False)

    def ready(self, *, total=0):
        with self.lock:
            if self.state and self.state.get('status') in {'running','failed','cancelled'}:
                return
            self.state = {'schema':1, 'status':'ready', 'step':1,
                          'message':'นับรายการใน SQLite แล้ว; จะตรวจไฟล์จริงเมื่อซิงค์',
                          'song_types':(self.state or {}).get('song_types',['MIDI','NCN']),
                          'font':(self.state or {}).get('font',''),
                          'done':max(0,int(total)), 'total':max(0,int(total))}
            self._save()

    def phase(self, step, message):
        with self.lock:
            if not self.state or self.state.get('status') != 'running':
                return
            self.state.update(step=max(1, min(5, int(step))), message=str(message)[:180])
            self._save()

    def progress(self, message, done=0, total=0):
        with self.lock:
            if not self.state or self.state.get('status') != 'running':
                return
            self.state.update(message=str(message)[:180],done=max(0,int(done)),total=max(0,int(total)))
            self._save(force=False)

    def finish(self, kind, message=''):
        if kind not in ('cancelled','failed','completed'):
            raise ValueError('สถานะการเสร็จงานไม่ถูกต้อง')
        with self.lock:
            if not self.state:
                return
            self.state.update(status=kind, message=str(message)[:180])
            self._save()

    def interrupted(self):
        return bool(self.state and self.state.get('status') in {'running','failed','cancelled','scanning'})

    def describe(self):
        if not self.state or not self.interrupted():
            return ''
        info=self.state
        label = {'running': 'พบงานที่หยุดไม่สมบูรณ์', 'failed':'พบงานที่เคยผิดพลาด',
                 'cancelled':'พบงานที่หยุดไว้','scanning':'พบงานตรวจรายการเพลงที่หยุดกลางคัน'}.get(info['status'])
        count=(f" • ครั้งก่อน {info.get('done',0):,}/{info.get('total',0):,} เพลง"
               if info.get('total') else '')
        return (label + count + (' • ระบบจะตรวจรายการเพลงจากฐาน SQLite ใหม่' if info['status']=='scanning' else ' • กด “ซิงค์ต่อจากครั้งก่อน” เพื่อสแกนยืนยันและข้ามไฟล์ที่อัปโหลดครบแล้ว'))

class VerifiedUploadJournal:
    """One durable SQLite row per verified upload (O(1) checkpoint writes).

    Scoped by Drive root ID; supports importing old single-JSON checkpoints.
    Called only on the sync worker thread, never from Tk's event loop.
    """
    def __init__(self, cache_dir, drive_root):
        import hashlib
        digest=hashlib.sha256(str(drive_root).encode('utf-8')).hexdigest()[:20]
        folder=Path(cache_dir)/'sync'
        self.path=folder/(digest+'.sqlite3')
        self.legacy_path=folder/(digest+'.json')
        self.connection=None

    def __enter__(self):
        import sqlite3
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection=sqlite3.connect(self.path, timeout=20)
        self.connection.execute('PRAGMA synchronous=FULL')
        self.connection.execute('PRAGMA journal_mode=DELETE')
        with self.connection:
            self.connection.execute('''CREATE TABLE IF NOT EXISTS uploaded (
                web_song_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                updated_at TEXT NOT NULL)''')
        # Compatibility: import only verified metadata entries; older journal
        # entries without a full row still reuse remote content via _place().
        if self.connection.execute('PRAGMA user_version').fetchone()[0] < 1:
            try:
                if self.legacy_path.is_file() and self.legacy_path.stat().st_size<=64*1024*1024:
                    previous=json.loads(self.legacy_path.read_text(encoding='utf-8'))
                    if isinstance(previous,dict):
                        with self.connection:
                            for key,value in previous.items():
                                if isinstance(key,str) and isinstance(value,dict) and isinstance(value.get('row'),dict):
                                    self.connection.execute('INSERT OR IGNORE INTO uploaded VALUES (?,?,?)',(
                                        key,json.dumps(value,ensure_ascii=False,separators=(',',':')),
                                        datetime.now(timezone.utc).isoformat()))
            except (OSError,ValueError,TypeError):
                pass  # Do not block recovery because of an old damaged JSON journal.
            with self.connection:
                self.connection.execute('PRAGMA user_version=1')
        return self

    def get(self, web_song_id):
        if self.connection is None:raise RuntimeError('Journal is closed')
        value=self.connection.execute('SELECT payload FROM uploaded WHERE web_song_id=?',(str(web_song_id),)).fetchone()
        if not value:return None
        try:
            parsed=json.loads(value[0])
            return parsed if isinstance(parsed,dict) else None
        except (ValueError,TypeError):
            return None

    def __setitem__(self, web_song_id, entry):
        if self.connection is None:raise RuntimeError('Journal is closed')
        if not isinstance(entry,dict) or entry.get('state')!='uploaded' or not isinstance(entry.get('row'),dict):
            raise ValueError('Only verified, complete uploads can be checkpointed')
        payload=json.dumps(entry,ensure_ascii=False,separators=(',',':'))
        with self.connection:
            self.connection.execute('''INSERT INTO uploaded(web_song_id,payload,updated_at)
                VALUES (?,?,?) ON CONFLICT(web_song_id) DO UPDATE SET
                payload=excluded.payload, updated_at=excluded.updated_at''',
                (str(web_song_id),payload,datetime.now(timezone.utc).isoformat()))

    def __exit__(self, *exc):
        if self.connection is not None:
            self.connection.close()
            self.connection=None
