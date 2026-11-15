"""Opt-in Windows output loopback; bounded memory, no disk recordings."""
import base64
from collections import deque
import threading
import time


def capture_output(stop, publish):
    import sys
    if sys.platform != 'win32':
        raise OSError('เสียงมือถือรองรับเครื่องหลัก Windows เท่านั้น')
    import numpy as np
    from .windows_audio import audio_context
    with audio_context() as sc:
        speaker = sc.default_speaker()
        if speaker is None:
            raise OSError('ไม่พบลำโพงเริ่มต้นของ Windows')
        source = sc.get_microphone(id=speaker.id, include_loopback=True)
        if not source.isloopback:
            raise OSError('ไม่พบอุปกรณ์รับเสียงลำโพงแบบ loopback')
        with source.recorder(samplerate=24000, channels=2, blocksize=4800) as recorder:
            while not stop.is_set():
                frames = recorder.record(numframes=4800)
                pcm = (np.clip(np.nan_to_num(frames), -1, 1) * 32767).astype('<i2').tobytes()
                if not stop.is_set(): publish(pcm)



class RemoteAudio:
    def __init__(self, capture=capture_output):
        self.capture = capture
        self.lock = threading.RLock()
        self.enabled = False
        self.frames = deque(maxlen=5)
        self.sequence = 0
        self.generation = 0
        self.error = ''
        self.thread = None
        self.stop_event = threading.Event()
        self.last_reader = 0

    def configure(self, enabled):
        with self.lock:
            enabled = bool(enabled)
            if enabled == self.enabled: return
            self.enabled = enabled
            self.generation += 1
            self.frames.clear()
            self.error = ''
            self.stop_event.set()

    def _publish(self, generation, pcm):
        with self.lock:
            if not self.enabled or generation != self.generation: return
            if time.monotonic()-self.last_reader > 3:
                self.stop_event.set()
                self.frames.clear()
                return
            self.sequence += 1
            self.frames.append((self.sequence, time.monotonic(), base64.b64encode(pcm).decode('ascii')))

    def _run(self, generation, stop):
        try:
            self.capture(stop, lambda pcm:self._publish(generation, pcm))
        except Exception as error:
            with self.lock:
                if generation == self.generation: self.error = str(error)

    def read(self, after=0):
        with self.lock:
            if not self.enabled: raise PermissionError('เครื่องหลักไม่อนุญาตเสียงมือถือ')
            self.last_reader = time.monotonic()
            if not self.error and (self.thread is None or not self.thread.is_alive()):
                self.frames.clear()
                self.stop_event = threading.Event()
                self.thread = threading.Thread(target=self._run,args=(self.generation,self.stop_event),daemon=True,name='remote-output-audio')
                self.thread.start()
            frames = [dict(seq=seq,pcm=pcm) for seq,stamp,pcm in self.frames
                      if seq > after and time.monotonic()-stamp < 1][-3:]
            return dict(rate=24000,channels=2,frames=frames,error=self.error)

    def close(self):
        self.configure(False)
