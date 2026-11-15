"""Local-only crash, callback and UI-stall diagnostics; no network transport."""
import faulthandler
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import sys
import threading
import time
import uuid


class CategoryFilter(logging.Filter):
    def filter(self, record):
        module=record.module.lower()
        message=record.getMessage()
        if module in ('audio_dialog','preset_browser','font_mapping') or 'soundfont' in module or message.startswith('SOUNDFONT_'): category='SOUNDFONT'
        elif 'eq' in module or 'equalizer' in module: category='EQ'
        elif 'remote' in module or 'wifi' in module: category='REMOTE'
        elif 'record' in module: category='RECORDING'
        elif module in ('playback','pcm_player','medley','medley_decks','queue_countdown') or message.startswith(('Playback transition','Cannot load song','Queue ')): category='PLAYER'
        elif 'audio' in module or 'bass' in module: category='AUDIO'
        else: category='SYSTEM'
        record.category=category
        return True


class SessionFilter(logging.Filter):
    def __init__(self, session):
        super().__init__()
        self.session = session
    def filter(self, record):
        record.session = self.session
        return True


class Diagnostics:
    def __init__(self, directory, timeout=15):
        self.directory = Path(directory)
        self.session = uuid.uuid4().hex[:12]
        self.timeout = timeout
        self.last_beat = time.monotonic()
        self.stalled = False
        self.dumps = 0
        self.stop = threading.Event()
        self.errors = queue.Queue(maxsize=10)
        self.handler = self.native = None
        self._closed = False
        self._fault_enabled = False
        self._root_level_changed = False
        self.old_sys = sys.excepthook
        self.old_thread = threading.excepthook
        self.old_level = logging.getLogger().level
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.handler = RotatingFileHandler(self.directory/'XStageKaraoke.log', maxBytes=5*1024*1024,
                                              backupCount=3, encoding='utf-8')
            self.handler.addFilter(CategoryFilter())
            self.handler.addFilter(SessionFilter(self.session))
            self.handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s [%(category)s] [session=%(session)s] [%(threadName)s] %(message)s'))
            old = sorted(self.directory.glob('XStageKaraoke-native-*.log'), key=lambda p: p.stat().st_mtime)
            for path in old[:-9]:
                try: path.unlink()
                except OSError: pass
            self.native = (self.directory/f'XStageKaraoke-native-{self.session}.log').open('a', encoding='utf-8')
            # Do not replace a native fault handler already owned by the host.
            if not faulthandler.is_enabled():
                faulthandler.enable(file=self.native, all_threads=True)
                self._fault_enabled = True
            root = logging.getLogger()
            root.addHandler(self.handler)
            if root.level > logging.INFO:
                root.setLevel(logging.INFO)
                self._root_level_changed = True
            sys.excepthook = self.exception
            threading.excepthook = self.thread_exception
            from . import __version__
            logging.info('SESSION_START id=%s version=%s python=%s platform=%s',
                         self.session, __version__, sys.version.split()[0], sys.platform)
        except BaseException:
            self._closed = True
            self.stop.set()
            self._release_resources()
            raise

    def _release_resources(self):
        errors = []
        def attempt(action):
            try: action()
            except BaseException as error: errors.append(error)
        if sys.excepthook == self.exception:
            sys.excepthook = self.old_sys
        if threading.excepthook == self.thread_exception:
            threading.excepthook = self.old_thread
        root = logging.getLogger()
        if self.handler is not None:
            attempt(lambda: root.removeHandler(self.handler))
        if self._root_level_changed and root.level == logging.INFO:
            attempt(lambda: root.setLevel(self.old_level))
        self._root_level_changed = False
        if self._fault_enabled:
            attempt(faulthandler.disable)
            self._fault_enabled = False
        if self.native is not None:
            attempt(self.native.close)
        if self.handler is not None:
            attempt(self.handler.close)
        return errors

    def exception(self, kind, value, tb):
        logging.error('UNHANDLED session=%s', self.session, exc_info=(kind, value, tb))

    def thread_exception(self, args):
        self.exception(args.exc_type, args.exc_value, args.exc_traceback)
        try: self.errors.put_nowait('งานเบื้องหลังเกิดข้อผิดพลาด')
        except queue.Full: pass

    def callback_exception(self, kind, value, tb):
        self.exception(kind, value, tb)
        try: self.errors.put_nowait('คำสั่งบนหน้าจอทำงานไม่สำเร็จ')
        except queue.Full: pass

    def check_stall(self, now=None):
        age = (time.monotonic() if now is None else now) - self.last_beat
        if age > self.timeout and not self.stalled:
            self.stalled = True
            logging.error('UI_STALL session=%s heartbeat_age=%.1fs', self.session, age)
            if self.dumps < 3:
                self.dumps += 1
                faulthandler.dump_traceback(file=self.native, all_threads=True)
                self.native.flush()
        elif age <= self.timeout and self.stalled:
            self.stalled = False
            logging.info('UI_RECOVERED session=%s', self.session)

    def attach(self, app):
        self.app = app
        app._diagnostics = self
        self.after_id = None
        def beat():
            if self.stop.is_set(): return
            self.last_beat = time.monotonic()
            try:
                message = self.errors.get_nowait()
            except queue.Empty:
                message = None
            self.after_id = app.after(1000, beat)
            if message:
                from tkinter import messagebox
                parent = app.grab_current() or app
                if not parent.winfo_viewable():
                    parent.grab_release()
                    parent = app
                messagebox.showerror('X-Stage • บันทึกข้อผิดพลาดแล้ว',
                    f'{message}\nไฟล์รายงาน: {self.directory}\nSession: {self.session}', parent=parent)
        beat()
        def watch():
            while not self.stop.wait(2): self.check_stall()
        self.watcher = threading.Thread(target=watch, name='ui-watchdog', daemon=True)
        self.watcher.start()

    def close(self):
        if self._closed: return
        self._closed = True
        self.stop.set()
        errors = []
        try:
            if hasattr(self, 'watcher'): self.watcher.join(timeout=3)
            if hasattr(self, 'after_id') and self.after_id:
                try: self.app.after_cancel(self.after_id)
                except Exception: pass
            logging.info('SESSION_END id=%s', self.session)
        except BaseException as error:
            errors.append(error)
        finally:
            errors.extend(self._release_resources())
        if errors: raise errors[0]


def log_base(data):
    import hashlib
    if not os.environ.get('LOCALAPPDATA'):return Path(data)/'Logs'
    key=hashlib.sha256(str(Path(data).resolve()).casefold().encode('utf-8')).hexdigest()[:16]
    return Path(os.environ['LOCALAPPDATA'])/'XStageKaraoke'/'Logs'/key


def start(data):
    try:return Diagnostics(log_base(data))
    except OSError:return Diagnostics(Path(data)/'Logs')
