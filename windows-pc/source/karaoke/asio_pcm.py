"""Bounded stereo float PCM bridge for an eventual BASSASIO callback.

The native ASIO callback must not call BASSMIDI or Python code. This module
prepares validated PCM frames and deterministic underrun silence; an ASIO
native output host is required before real-time playback is supported.
"""
import ctypes
import threading
from collections import deque

FRAME_BYTES = 8  # interleaved stereo, float32


class AsioPcmQueue:
    def __init__(self, capacity_frames=48000):
        if type(capacity_frames) is not int or capacity_frames <= 0:
            raise ValueError('ความจุบัฟเฟอร์ ASIO ไม่ถูกต้อง')
        self.capacity_frames = capacity_frames
        self._chunks = deque()
        self._size = 0
        self._lock = threading.Lock()
        self.dropped_frames = 0
        self.underrun_frames = 0

    def push(self, pcm):
        data = bytes(pcm)
        if len(data) % FRAME_BYTES:
            raise ValueError('PCM ต้องเป็น stereo float32 แบบ interleaved')
        capacity = self.capacity_frames * FRAME_BYTES
        if len(data) > capacity:
            self.dropped_frames += (len(data) - capacity) // FRAME_BYTES
            data = data[-capacity:]
        with self._lock:
            while self._size + len(data) > capacity and self._chunks:
                oldest = self._chunks.popleft()
                self._size -= len(oldest)
                self.dropped_frames += len(oldest) // FRAME_BYTES
            if data:
                self._chunks.append(data)
                self._size += len(data)

    def pop(self, frames):
        if type(frames) is not int or frames < 0:
            raise ValueError('จำนวนเฟรม PCM ไม่ถูกต้อง')
        needed = frames * FRAME_BYTES
        parts = []
        with self._lock:
            while needed and self._chunks:
                chunk = self._chunks.popleft()
                take = min(len(chunk), needed)
                parts.append(chunk[:take])
                self._size -= take
                needed -= take
                if take < len(chunk):
                    self._chunks.appendleft(chunk[take:])
            if needed:
                self.underrun_frames += needed // FRAME_BYTES
        return b''.join(parts) + bytes(needed)

    def clear(self):
        with self._lock:
            self._chunks.clear()
            self._size = 0

    @property
    def buffered_frames(self):
        with self._lock:
            return self._size // FRAME_BYTES


def copy_pcm_to_buffer(queue, buffer, frames):
    """Fill a preallocated native stereo buffer, including underrun silence."""
    if not isinstance(queue, AsioPcmQueue):
        raise TypeError('ต้องระบุบัฟเฟอร์ PCM')
    if type(frames) is not int or frames < 0:
        raise ValueError('จำนวนเฟรม PCM ไม่ถูกต้อง')
    pcm = queue.pop(frames)
    if pcm:
        ctypes.memmove(buffer, pcm, len(pcm))
    return len(pcm)
