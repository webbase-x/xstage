"""Experimental BASSMIDI decode -> native FIFO -> BASSASIO output.

Explicit opt-in only. The producer renders PCM on a worker thread; the ASIO
callback remains native and never invokes Python. Not a verified release path.
"""
import threading

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
            try:
                self.close()
            except Exception:
                pass
            raise

    def _produce(self):
        pending = b''
        try:
            while not self._stop.is_set():
                bridge = self.output.bridge
                # Only the ASIO native callback consumes data. Maintain a
                # bounded lead and never discard a partially accepted render.
                buffered = bridge.buffered_frames()
                if buffered >= self._target:
                    self._stop.wait(.002)
                    continue
                if not pending:
                    pcm = self.synth.render(min(self._chunk, self._target - buffered))
                    if len(pcm) % 8:
                        raise OSError('BASSMIDI ส่ง PCM ที่ไม่ตรงขนาดเฟรม Stereo Float32')
                    pending = pcm
                if not pending:
                    self._stop.wait(.002)
                    continue
                accepted = self.output.push(pending)
                frames = len(pending) // 8
                if type(accepted) is not int or not 0 <= accepted <= frames:
                    raise OSError('ASIO PCM bridge คืนจำนวนเฟรมที่ไม่ถูกต้อง')
                pending = pending[accepted * 8:]
                if pending or accepted == 0:
                    self._stop.wait(.002)
        except Exception as exc:
            self._error = exc
            self._stop.set()

    def send(self, data):
        if self._error:
            raise OSError('ASIO PCM producer หยุดทำงาน') from self._error
        return self.synth.send(data)

    def reset(self):
        # Reset MIDI state; do not clear the SPSC FIFO from a third thread.
        # Previously rendered audio may remain for up to the configured lead.
        if self._error:
            raise OSError('ASIO PCM producer หยุดทำงาน') from self._error
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
            if self._worker.ident is not None:
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
