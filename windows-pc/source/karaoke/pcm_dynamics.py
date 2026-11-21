"""Optional post-render stereo float32 PCM peak safety limiter.

A bounded block-peak limiter for the experimental ASIO producer, not a
true-peak / LUFS mastering engine. No processing happens in the ASIO callback.
Disabled by default so existing SoundFont tone is unchanged.
"""
from array import array
import math
import sys


class StereoPeakLimiter:
    def __init__(self, ceiling=0.98, release_step=0.02):
        if not isinstance(ceiling, (int, float)) or not math.isfinite(ceiling) or not 0 < ceiling < 1:
            raise ValueError('Limiter ceiling ต้องอยู่ระหว่าง 0 และ 1')
        if not isinstance(release_step, (int, float)) or not 0 < release_step <= 1:
            raise ValueError('Limiter release ไม่ถูกต้อง')
        self.ceiling = float(ceiling)
        self.release_step = float(release_step)
        self.gain = 1.
        self.input_peak = 0.
        self.output_peak = 0.
        self.reduced_blocks = 0

    def process(self, pcm):
        if not pcm:
            return b''
        if len(pcm) % 8:
            raise ValueError('Limiter ต้องใช้ PCM Stereo float32')
        values = array('f')
        values.frombytes(pcm)
        if sys.byteorder != 'little':
            values.byteswap()
        for i, value in enumerate(values):
            if not math.isfinite(value):
                values[i] = 0.
        peak = max(abs(value) for value in values)
        self.input_peak = peak
        maximum = 1. if peak <= self.ceiling else self.ceiling / peak
        if maximum < self.gain:
            self.gain = maximum
        else:
            self.gain = min(maximum, self.gain + self.release_step)
        if self.gain < 1.:
            self.reduced_blocks += 1
        out_peak = 0.
        for i, value in enumerate(values):
            bounded = max(-self.ceiling, min(self.ceiling, value * self.gain))
            values[i] = bounded
            out_peak = max(out_peak, abs(bounded))
        self.output_peak = out_peak
        if sys.byteorder != 'little':
            values.byteswap()
        return values.tobytes()
