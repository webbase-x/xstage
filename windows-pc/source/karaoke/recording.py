"""Native waveIn PCM recording. Input is explicitly selected by the operator."""
from __future__ import annotations
import ctypes
import logging
import os
import threading
import wave
from pathlib import Path


class WaveRecorder:
    @staticmethod
    def devices():
        if os.name != 'nt':
            return []
        from ctypes import wintypes as w
        class Caps(ctypes.Structure):
            _fields_ = [('mid',w.WORD),('pid',w.WORD),('version',w.DWORD),('name',w.WCHAR*32),('formats',w.DWORD),('channels',w.WORD),('reserved',w.WORD)]
        dll = ctypes.WinDLL('winmm')
        dll.waveInGetDevCapsW.argtypes = [ctypes.c_size_t, ctypes.POINTER(Caps), w.UINT]
        result = []
        for index in range(dll.waveInGetNumDevs()):
            caps = Caps()
            if not dll.waveInGetDevCapsW(index, ctypes.byref(caps), ctypes.sizeof(caps)):
                result.append((index, caps.name))
        return result

    def __init__(self, file: Path, device=0, sample_rate=48000):
        from .playback import WavePlayer
        structures = WavePlayer()
        self.Format, self.Header = structures.Format, structures.Header
        from ctypes import wintypes as w
        self.dll = ctypes.WinDLL('winmm')
        self.dll.waveInOpen.argtypes = [ctypes.POINTER(ctypes.c_void_p), w.UINT, ctypes.POINTER(self.Format), ctypes.c_size_t, ctypes.c_size_t, w.DWORD]
        for name in ('waveInPrepareHeader','waveInUnprepareHeader','waveInAddBuffer'):
            getattr(self.dll,name).argtypes = [ctypes.c_void_p, ctypes.POINTER(self.Header), w.UINT]
        for name in ('waveInStart','waveInStop','waveInReset','waveInClose'):
            getattr(self.dll,name).argtypes = [ctypes.c_void_p]
        self.path, self.device, self.rate = Path(file), device, sample_rate
        self.handle = ctypes.c_void_p()
        self.buffers, self.headers = [], []
        self.writer = None
        self.thread = None
        self.quit = threading.Event()
        self.error = None

    def check(self, result):
        if result:
            raise OSError(f'บันทึกเสียงไม่สำเร็จ รหัส waveIn {result}')

    def start(self):
        if self.handle.value:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.writer = wave.open(str(self.path), 'wb')
        self.writer.setnchannels(1)
        self.writer.setsampwidth(2)
        self.writer.setframerate(self.rate)
        try:
            fmt = self.Format(1, 1, self.rate, self.rate*2, 2, 16, 0)
            self.check(self.dll.waveInOpen(ctypes.byref(self.handle), self.device, ctypes.byref(fmt), 0, 0, 0))
            for _ in range(4):
                buffer = ctypes.create_string_buffer(8192)
                header = self.Header()
                header.data = ctypes.addressof(buffer)
                header.length = len(buffer)
                self.buffers.append(buffer)
                self.headers.append(header)
                self.check(self.dll.waveInPrepareHeader(self.handle, ctypes.byref(header), ctypes.sizeof(header)))
                self.check(self.dll.waveInAddBuffer(self.handle, ctypes.byref(header), ctypes.sizeof(header)))
            self.check(self.dll.waveInStart(self.handle))
            self.thread = threading.Thread(target=self.run, name='wave-recorder', daemon=True)
            self.thread.start()
            logging.info("RECORDING_STARTED device=%s rate=%s", self.device, self.rate)
        except Exception:
            logging.exception("RECORDING_START_FAILED")
            self.stop()
            raise

    def run(self):
        try:
            while True:
                for header in self.headers:
                    if header.flags & 1:
                        if header.recorded:
                            self.writer.writeframesraw(ctypes.string_at(header.data, header.recorded))
                            header.recorded = 0
                        if not self.quit.is_set():
                            self.check(self.dll.waveInAddBuffer(self.handle, ctypes.byref(header), ctypes.sizeof(header)))
                if self.quit.is_set():
                    break
                self.quit.wait(.01)
        except Exception as error:
            self.error = error
            logging.exception("RECORDING_WRITE_FAILED")

    def stop(self):
        if self.handle.value:
            self.dll.waveInStop(self.handle)
            self.dll.waveInReset(self.handle)
        self.quit.set()
        if self.thread:
            self.thread.join(timeout=3)
            if self.thread.is_alive():
                self.error = RuntimeError('หยุดบันทึกเสียงไม่ทันกำหนด')
                logging.error('RECORDING_STOP_TIMEOUT')
                return
        if self.handle.value:
            for header in self.headers:
                self.dll.waveInUnprepareHeader(self.handle, ctypes.byref(header), ctypes.sizeof(header))
            self.dll.waveInClose(self.handle)
            self.handle = ctypes.c_void_p()
        if self.writer:
            self.writer.close()
            self.writer = None
            logging.info("RECORDING_STOPPED")
