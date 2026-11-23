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
        # Explicitly resettable post-limiter peak holds for live diagnostics.
        self.peak_holds = {i: (0., 0.) for i in range(bus_count)}
        # Retain pre-limiter overload peaks across blocks until explicit reset.
        self.pre_limit_peak_holds = {i: (0., 0.) for i in range(bus_count)}

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

    def configure_many(self, changes):
        """Atomically apply partial strip changes from a mixer UI or scene.

        All bus IDs, field names and values are validated before any strip is
        changed. Diagnostics and existing audio routing are not reset.
        """
        if type(changes) is not dict:
            raise ValueError("Invalid mixer changes")
        candidate = self.strips.copy()
        allowed = {"gain", "pan", "mute", "solo"}
        for bus, fields in changes.items():
            if type(bus) is not int or bus not in candidate:
                raise ValueError("Unknown bus")
            if type(fields) is not dict or not fields or not set(fields) <= allowed:
                raise ValueError("Invalid mixer strip changes")
            current = candidate[bus]
            values = {name: getattr(current, name) for name in allowed}
            values.update(fields)
            candidate[bus] = BusStrip(**values)
        self.strips = candidate

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

    def diagnostics_snapshot(self):
        """Return detached per-bus diagnostics for UI polling and QA.

        Diagnostics are deliberately excluded from persistent mixer presets.
        Callers may mutate the returned dictionaries without changing meters.
        """
        return {
            "meters": self.meters.copy(),
            "rms_meters": self.rms_meters.copy(),
            "pre_limit_peaks": self.pre_limit_peaks.copy(),
            "peak_holds": self.peak_holds.copy(),
            "pre_limit_peak_holds": self.pre_limit_peak_holds.copy(),
            "clipped_samples": self.clipped_samples.copy(),
            "total_clipped_samples": self.total_clipped_samples.copy(),
        }

    def levels_dbfs_snapshot(self, *, floor_db=-120.0):
        """Detached dBFS peak/RMS values for readable mixer meters.

        Silence is represented by the finite floor, keeping the result safe
        for JSON and GUI renderers. This is diagnostic only, not a gain stage.
        """
        if type(floor_db) not in (int, float) or not math.isfinite(floor_db) or not -300 <= floor_db <= 0:
            raise ValueError("Invalid dBFS floor")
        floor = float(floor_db)

        def dbfs(value):
            if not math.isfinite(value) or value <= 0:
                return floor
            return max(floor, 20.0 * math.log10(value))

        return {
            "peak_dbfs": {bus: tuple(dbfs(v) for v in pair)
                          for bus, pair in self.meters.items()},
            "rms_dbfs": {bus: tuple(dbfs(v) for v in pair)
                         for bus, pair in self.rms_meters.items()},
            "peak_hold_dbfs": {bus: tuple(dbfs(v) for v in pair)
                               for bus, pair in self.peak_holds.items()},
            "pre_limit_peak_dbfs": {bus: tuple(dbfs(v) for v in pair)
                                    for bus, pair in self.pre_limit_peaks.items()},
            "pre_limit_peak_hold_dbfs": {bus: tuple(dbfs(v) for v in pair)
                                         for bus, pair in self.pre_limit_peak_holds.items()},
        }

    def reset_clipping_totals(self, bus=None):
        """Clear lifetime clipping diagnostics without changing audio or presets."""
        if bus is None:
            for index in self.total_clipped_samples:
                self.total_clipped_samples[index] = 0
            return
        if type(bus) is not int or bus not in self.strips:
            raise ValueError("Unknown bus")
        self.total_clipped_samples[bus] = 0

    def reset_peak_holds(self, bus=None):
        """Clear peak holds without changing audio, strips or clipping totals."""
        if bus is None:
            for index in self.peak_holds:
                self.peak_holds[index] = (0., 0.)
                self.pre_limit_peak_holds[index] = (0., 0.)
            return
        if type(bus) is not int or bus not in self.strips:
            raise ValueError("Unknown bus")
        self.peak_holds[bus] = (0., 0.)
        self.pre_limit_peak_holds[bus] = (0., 0.)

    def reset_diagnostics(self, bus=None):
        """Clear meter history at an explicit song/session boundary.

        Does not change routing, strip controls, limiter settings or presets.
        Validation happens before any diagnostic state is changed.
        """
        if bus is not None and (type(bus) is not int or bus not in self.strips):
            raise ValueError("Unknown bus")
        targets = self.strips if bus is None else (bus,)
        for index in targets:
            self.meters[index] = (0., 0.)
            self.rms_meters[index] = (0., 0.)
            self.pre_limit_peaks[index] = (0., 0.)
            self.peak_holds[index] = (0., 0.)
            self.pre_limit_peak_holds[index] = (0., 0.)
            self.clipped_samples[index] = 0
            self.total_clipped_samples[index] = 0

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
            # Finite float32 input can overflow during gain multiplication.
            # Saturate safely before assigning to the float32 output array.
            if not math.isfinite(left):
                left = math.copysign(self.ceiling, left)
            if not math.isfinite(right):
                right = math.copysign(self.ceiling, right)
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
        held_left, held_right = self.peak_holds[bus]
        self.peak_holds[bus] = (max(held_left, left_peak), max(held_right, right_peak))
        frame_count = len(values) // 2
        self.rms_meters[bus] = (math.sqrt(left_energy / frame_count),
                                math.sqrt(right_energy / frame_count))
        self.clipped_samples[bus] = clipped
        self.total_clipped_samples[bus] += clipped
        self.pre_limit_peaks[bus] = (pre_left_peak, pre_right_peak)
        held_pre_left, held_pre_right = self.pre_limit_peak_holds[bus]
        self.pre_limit_peak_holds[bus] = (max(held_pre_left, pre_left_peak),
                                          max(held_pre_right, pre_right_peak))
        if sys.byteorder != "little":
            values.byteswap()
        return values.tobytes()
