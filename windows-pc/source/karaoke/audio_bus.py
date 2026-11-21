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
