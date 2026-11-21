"""Hardware-independent P2 stereo bus gain, pan, mute, solo and peak meters.

Pure PCM processor: callers decide where to attach it to an audio backend.
No device access and no changes to legacy stereo playback.
"""
from array import array
from dataclasses import dataclass
import math
import sys


@dataclass(frozen=True)
class BusStrip:
    gain: float = 1.0
    pan: float = 0.0
    mute: bool = False
    solo: bool = False

    def __post_init__(self):
        if type(self.gain) not in (int, float) or not math.isfinite(self.gain) or not 0 <= self.gain <= 2:
            raise ValueError("Bus gain must be finite and between 0 and 2")
        if type(self.pan) not in (int, float) or not math.isfinite(self.pan) or not -1 <= self.pan <= 1:
            raise ValueError("Bus pan must be between -1 and 1")
        if type(self.mute) is not bool or type(self.solo) is not bool:
            raise ValueError("Mute and solo must be boolean")


class VirtualBusMixer:
    """Process independent stereo float32 little-endian PCM blocks per bus."""

    def __init__(self, bus_count, *, ceiling=0.98):
        if type(bus_count) is not int or bus_count not in (2, 4, 8, 16):
            raise ValueError("Unsupported bus count")
        if type(ceiling) not in (int, float) or not math.isfinite(ceiling) or not 0 < ceiling <= 1:
            raise ValueError("Invalid peak ceiling")
        self.strips = {i: BusStrip() for i in range(bus_count)}
        self.ceiling = float(ceiling)
        self.meters = {i: (0., 0.) for i in range(bus_count)}

    def configure(self, bus, *, gain=1., pan=0., mute=False, solo=False):
        if type(bus) is not int or bus not in self.strips:
            raise ValueError("Unknown bus")
        self.strips[bus] = BusStrip(gain, pan, mute, solo)

    def process(self, bus, pcm):
        if type(bus) is not int or bus not in self.strips:
            raise ValueError("Unknown bus")
        if not isinstance(pcm, bytes) or len(pcm) % 8:
            raise ValueError("Expected interleaved stereo float32 PCM")
        if not pcm:
            self.meters[bus] = (0., 0.)
            return b""
        values = array("f")
        values.frombytes(pcm)
        if sys.byteorder != "little":
            values.byteswap()
        strip = self.strips[bus]
        audible = not strip.mute and (not any(s.solo for s in self.strips.values()) or strip.solo)
        left_gain = strip.gain * min(1., 1. - strip.pan) if audible else 0.
        right_gain = strip.gain * min(1., 1. + strip.pan) if audible else 0.
        left_peak = right_peak = 0.
        for i in range(0, len(values), 2):
            left = values[i] if math.isfinite(values[i]) else 0.
            right = values[i + 1] if math.isfinite(values[i + 1]) else 0.
            left = max(-self.ceiling, min(self.ceiling, left * left_gain))
            right = max(-self.ceiling, min(self.ceiling, right * right_gain))
            values[i], values[i + 1] = left, right
            left_peak = max(left_peak, abs(left))
            right_peak = max(right_peak, abs(right))
        self.meters[bus] = (left_peak, right_peak)
        if sys.byteorder != "little":
            values.byteswap()
        return values.tobytes()
