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
        # Post-fader RMS levels, independent of peak meters and preset state.
        self.rms_meters = {i: (0., 0.) for i in range(bus_count)}
        # Per-block samples exceeding the output ceiling, for clipping QA.
        self.clipped_samples = {i: 0 for i in range(bus_count)}
        # Lifetime diagnostics: unlike per-block counters, these survive silence.
        self.total_clipped_samples = {i: 0 for i in range(bus_count)}
        # Input to the safety limiter, after fader/pan/mute, before clipping.
        self.pre_limit_peaks = {i: (0., 0.) for i in range(bus_count)}

    def configure(self, bus, *, gain=None, pan=None, mute=None, solo=None):
        if type(bus) is not int or bus not in self.strips:
            raise ValueError("Unknown bus")
        # A single UI control must not silently reset the other strip controls.
        current = self.strips[bus]
        self.strips[bus] = BusStrip(
            current.gain if gain is None else gain,
            current.pan if pan is None else pan,
            current.mute if mute is None else mute,
            current.solo if solo is None else solo,
        )

    def snapshot(self):
        """Return a JSON-serializable, independent preset of every bus strip."""
        return {
            "version": 1,
            "bus_count": len(self.strips),
            "strips": [
                {"gain": strip.gain, "pan": strip.pan,
                 "mute": strip.mute, "solo": strip.solo}
                for strip in self.strips.values()
            ],
        }

    def apply_snapshot(self, preset):
        """Validate the complete preset before changing any live mixer state.

        Reject missing/extra buses and unexpected fields rather than applying a
        partially corrupted preset during a performance.
        """
        if type(preset) is not dict or set(preset) != {"version", "bus_count", "strips"}:
            raise ValueError("Invalid mixer preset")
        if type(preset["version"]) is not int or preset["version"] != 1:
            raise ValueError("Unsupported mixer preset version")
        if type(preset["bus_count"]) is not int or preset["bus_count"] != len(self.strips):
            raise ValueError("Mixer preset bus count mismatch")
        rows = preset["strips"]
        if type(rows) is not list or len(rows) != len(self.strips):
            raise ValueError("Mixer preset strips mismatch")
        candidate = {}
        for bus, row in enumerate(rows):
            if type(row) is not dict or set(row) != {"gain", "pan", "mute", "solo"}:
                raise ValueError("Invalid mixer preset strip")
            candidate[bus] = BusStrip(**row)
        self.strips = candidate

    def reset_clipping_totals(self, bus=None):
        """Clear lifetime clipping diagnostics without changing audio or presets."""
        if bus is None:
            for index in self.total_clipped_samples:
                self.total_clipped_samples[index] = 0
            return
        if type(bus) is not int or bus not in self.strips:
            raise ValueError("Unknown bus")
        self.total_clipped_samples[bus] = 0

    def process(self, bus, pcm):
        if type(bus) is not int or bus not in self.strips:
            raise ValueError("Unknown bus")
        if not isinstance(pcm, bytes) or len(pcm) % 8:
            raise ValueError("Expected interleaved stereo float32 PCM")
        if not pcm:
            self.meters[bus] = (0., 0.)
            self.rms_meters[bus] = (0., 0.)
            self.clipped_samples[bus] = 0
            self.pre_limit_peaks[bus] = (0., 0.)
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
        clipped = 0
        pre_left_peak = pre_right_peak = 0.
        left_energy = right_energy = 0.
        for i in range(0, len(values), 2):
            left = values[i] if math.isfinite(values[i]) else 0.
            right = values[i + 1] if math.isfinite(values[i + 1]) else 0.
            left *= left_gain
            right *= right_gain
            pre_left_peak = max(pre_left_peak, abs(left))
            pre_right_peak = max(pre_right_peak, abs(right))
            clipped += int(abs(left) > self.ceiling) + int(abs(right) > self.ceiling)
            left = max(-self.ceiling, min(self.ceiling, left))
            right = max(-self.ceiling, min(self.ceiling, right))
            values[i], values[i + 1] = left, right
            left_energy += left * left
            right_energy += right * right
            left_peak = max(left_peak, abs(left))
            right_peak = max(right_peak, abs(right))
        self.meters[bus] = (left_peak, right_peak)
        frame_count = len(values) // 2
        self.rms_meters[bus] = (math.sqrt(left_energy / frame_count),
                                math.sqrt(right_energy / frame_count))
        self.clipped_samples[bus] = clipped
        self.total_clipped_samples[bus] += clipped
        self.pre_limit_peaks[bus] = (pre_left_peak, pre_right_peak)
        if sys.byteorder != "little":
            values.byteswap()
        return values.tobytes()
