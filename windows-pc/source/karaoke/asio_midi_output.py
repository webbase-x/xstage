"""Experimental BASSMIDI decode -> native FIFO -> BASSASIO output.

Explicit opt-in only. The producer renders PCM on a worker thread; the ASIO
callback remains native and never invokes Python. Not a verified release path.
"""
import threading
import time

from .bass import BassSynth
from .asio_output import AsioOutput


class AsioMidiOutput:
    def __init__(self, native, *, device, channel=0, settings=None,
                 synth_factory=BassSynth, output_factory=AsioOutput,
                 chunk_frames=480, target_frames=4800):
        if type(chunk_frames) is not int or not 1 <= chunk_frames <= 4800:
            raise ValueError('ASIO chunk_frames ไม่ถูกต้อง')
        if type(target_frames) is not int or target_frames < chunk_frames:
            raise ValueError('ASIO target_frames ไม่ถูกต้อง')
        self.synth = None
        self.output = None
        self._stop = threading.Event()
        self._worker = None
        self._error = None
        self._chunk = chunk_frames
        self._target = target_frames
        try:
            self.synth = synth_factory(native, settings=settings, decode=True)
            self.output = output_factory(native, device=device, channel=channel)
            self._worker = threading.Thread(target=self._produce, name='asio-midi-producer',
                                            daemon=True)
            self._worker.start()
        except BaseException:
            self.close()
            raise

    def _produce(self):
        try:
            while not self._stop.is_set():
                bridge = self.output.bridge
                # Producer never calls the native callback. Maintain a bounded
                # lead rather than rendering unlimited MIDI ahead of the clock.
                if hasattr(bridge, 'buffered_frames'):
                    buffered = bridge.buffered_frames()
                else:
                    buffered = self._target  # no occupancy API: avoid busy spin
                if buffered >= self._target:
                    self._stop.wait(.002)
                    continue
                pcm = self.synth.render(self._chunk)
                if pcm:
                    accepted = self.output.push(pcm)
                    if accepted < len(pcm) // 8:
                        self._stop.wait(.002)
                else:
                    self._stop.wait(.002)
        except Exception as exc:
            self._error = exc
            self._stop.set()

    def send(self, data):
        if self._error:
            raise OSError('ASIO PCM producer หยุดทำงาน') from self._error
        return self.synth.send(data)

    def reset(self):
        return self.synth.reset()

    def set_channel_tone(self, *args, **kwargs):
        return self.synth.set_channel_tone(*args, **kwargs)

    def set_drum_tone(self, *args, **kwargs):
        return self.synth.set_drum_tone(*args, **kwargs)

    def set_channel_eq(self, *args, **kwargs):
        return self.synth.set_channel_eq(*args, **kwargs)

    def close(self):
        self._stop.set()
        if self._worker is not None:
            self._worker.join(timeout=3)
            if self._worker.is_alive():
                raise OSError('ASIO PCM producer ยังไม่หยุด: ไม่ปล่อยบัฟเฟอร์ที่กำลังใช้งาน')
            self._worker = None
        if self.output is not None:
            self.output.close()
            self.output = None
        if self.synth is not None:
            self.synth.close()
            self.synth = None
