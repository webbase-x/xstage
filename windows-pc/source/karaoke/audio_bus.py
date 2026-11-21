"""Pure routing model for future multi-output backends.

No native device is opened here; the existing stereo engine remains unchanged.
"""
from dataclasses import dataclass
from typing import Tuple

SUPPORTED_BUS_COUNTS = (2, 4, 8, 16)


@dataclass(frozen=True)
class AudioBusRoute:
    """A logical MIDI channel routed to one zero-based output bus."""

    midi_channel: int
    output_bus: int


@dataclass(frozen=True)
class AudioBusPlan:
    """Validated, immutable MIDI-to-output routing configuration."""

    bus_count: int
    routes: Tuple[AudioBusRoute, ...]

    def __post_init__(self):
        if type(self.bus_count) is not int or self.bus_count not in SUPPORTED_BUS_COUNTS:
            raise ValueError("จำนวนช่องเสียงต้องเป็น 2, 4, 8 หรือ 16")
        if len(self.routes) != 16:
            raise ValueError("ต้องกำหนดเส้นทาง MIDI ครบ 16 ช่อง")
        channels = set()
        for route in self.routes:
            if not isinstance(route, AudioBusRoute):
                raise ValueError("เส้นทางเสียงไม่ถูกต้อง")
            if (type(route.midi_channel) is not int or
                    not 0 <= route.midi_channel < 16 or
                    route.midi_channel in channels):
                raise ValueError("ช่อง MIDI ต้องไม่ซ้ำและอยู่ระหว่าง 0–15")
            if type(route.output_bus) is not int or not 0 <= route.output_bus < self.bus_count:
                raise ValueError("หมายเลขช่องเสียงปลายทางไม่ถูกต้อง")
            channels.add(route.midi_channel)

    def bus_for_channel(self, channel: int) -> int:
        if type(channel) is not int or not 0 <= channel < 16:
            raise ValueError("ช่อง MIDI ต้องอยู่ระหว่าง 0–15")
        return next(route.output_bus for route in self.routes if route.midi_channel == channel)


def stereo_plan() -> AudioBusPlan:
    """Backward-compatible default: all channels on the primary stereo bus."""
    return AudioBusPlan(2, tuple(AudioBusRoute(ch, 0) for ch in range(16)))


def plan_from_mapping(bus_count: int, mapping) -> AudioBusPlan:
    """Build a routing plan from channel->bus pairs without touching audio hardware."""
    if not isinstance(mapping, dict):
        raise ValueError("การกำหนดเส้นทางต้องเป็น dictionary")
    if set(mapping) != set(range(16)):
        raise ValueError("ต้องกำหนดเส้นทาง MIDI ครบ 16 ช่อง")
    return AudioBusPlan(bus_count, tuple(AudioBusRoute(ch, mapping[ch]) for ch in range(16)))


@dataclass(frozen=True)
class DrumKeyRoute:
    """Route a percussion note on MIDI channel 10 (zero-based channel 9)."""

    note: int
    output_bus: int


@dataclass(frozen=True)
class ResolvedAudioRoute:
    midi_channel: int
    output_bus: int
    drum_note: int = -1


@dataclass(frozen=True)
class PerformanceBusPlan:
    """Channel routes plus optional per-note percussion overrides."""

    channels: AudioBusPlan
    drum_keys: Tuple[DrumKeyRoute, ...] = ()

    def __post_init__(self):
        if not isinstance(self.channels, AudioBusPlan):
            raise ValueError("ต้องกำหนดแผนเส้นทางเสียง MIDI")
        seen = set()
        for route in self.drum_keys:
            if not isinstance(route, DrumKeyRoute):
                raise ValueError("เส้นทางเสียงกลองไม่ถูกต้อง")
            if (type(route.note) is not int or not 0 <= route.note <= 127
                    or route.note in seen):
                raise ValueError("หมายเลขโน้ตกลองไม่ถูกต้องหรือซ้ำกัน")
            if (type(route.output_bus) is not int
                    or not 0 <= route.output_bus < self.channels.bus_count):
                raise ValueError("ช่องเสียงกลองปลายทางไม่ถูกต้อง")
            seen.add(route.note)

    def resolve(self, channel: int, note: int = None) -> ResolvedAudioRoute:
        """Apply note overrides only to percussion, never melodic channels."""
        bus = self.channels.bus_for_channel(channel)
        if channel == 9 and note is not None:
            if type(note) is not int or not 0 <= note <= 127:
                raise ValueError("หมายเลขโน้ตกลองต้องอยู่ระหว่าง 0–127")
            for route in self.drum_keys:
                if route.note == note:
                    return ResolvedAudioRoute(channel, route.output_bus, note)
        return ResolvedAudioRoute(channel, bus, note if channel == 9 and note is not None else -1)


def performance_plan(bus_count: int = 2, channel_mapping=None, drum_mapping=None):
    """Create a safe routing snapshot; no live engine mutation or I/O."""
    if channel_mapping is None:
        channel_mapping = {ch: 0 for ch in range(16)}
    if drum_mapping is None:
        drum_mapping = {}
    if not isinstance(drum_mapping, dict):
        raise ValueError("การกำหนดเสียงกลองต้องเป็น dictionary")
    channels = plan_from_mapping(bus_count, channel_mapping)
    return PerformanceBusPlan(channels, tuple(
        DrumKeyRoute(note, bus) for note, bus in drum_mapping.items()
    ))
