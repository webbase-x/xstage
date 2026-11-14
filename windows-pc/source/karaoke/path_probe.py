"""Cancellable background path checks for slow external/network drives."""
from pathlib import Path
import threading

class PathProbe:
    def __init__(self, paths, callback=None):
        self.paths=[Path(p) for p in paths]; self.callback=callback; self.cancelled=threading.Event(); self.thread=None
    def start(self):
        if self.thread and self.thread.is_alive(): raise RuntimeError('path probe already running')
        self.thread=threading.Thread(target=self._run,name='path-probe',daemon=False); self.thread.start(); return self
    def cancel(self): self.cancelled.set()
    def join(self, timeout=None):
        if self.thread: self.thread.join(timeout)
        return not self.thread or not self.thread.is_alive()
    def _run(self):
        result=[]
        for path in self.paths:
            if self.cancelled.is_set(): break
            try: result.append({'path':str(path),'exists':path.is_file(),'error':None})
            except OSError as error: result.append({'path':str(path),'exists':False,'error':f'{type(error).__name__}: {error}'})
        if self.callback and not self.cancelled.is_set(): self.callback(result)