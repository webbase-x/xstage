"""Opt-in multi-device MIDI synthesizer.

One BASSMIDI synthesizer per logical bus. Each can select a native BASS
device; without an explicit device map all buses use the default output.
Existing single-synth playback remains the application default.
"""
from .audio_bus import MidiBusDispatcher, PerformanceBusPlan
from .bass import BassSynth


class MultiBusSynth:
    def __init__(self, native, *, plan: PerformanceBusPlan, devices=None,
                 settings=None, bindings=None, synth_factory=BassSynth):
        if not isinstance(plan, PerformanceBusPlan):
            raise ValueError('แผนเส้นทางเสียงไม่ถูกต้อง')
        count = plan.channels.bus_count
        if devices is None:
            devices = {}
        if not isinstance(devices, dict) or any(
                type(bus) is not int or bus not in range(count) or
                type(device) is not int or device < 0
                for bus, device in devices.items()):
            raise ValueError('หมายเลขอุปกรณ์เสียงสำหรับบัสไม่ถูกต้อง')
        self.plan = plan
        self.synths = {}
        self.dispatcher = None
        try:
            for bus in range(count):
                options = dict(settings=settings, device_id=devices.get(bus))
                if bindings is not None:
                    options['bindings'] = bindings
                self.synths[bus] = synth_factory(native, **options)
            self.dispatcher = MidiBusDispatcher(
                plan, {bus: synth.send for bus, synth in self.synths.items()})
        except BaseException:
            try:
                self.close()
            except Exception:
                pass
            raise

    def send(self, data):
        return self.dispatcher.dispatch(bytes(data))

    def reset(self):
        first = None
        for synth in self.synths.values():
            try:
                synth.reset()
            except Exception as exc:
                if first is None:
                    first = exc
        if first is not None:
            raise first

    def close(self):
        first = None
        for bus, synth in tuple(self.synths.items()):
            try:
                synth.close()
            except Exception as exc:
                if first is None:
                    first = exc
            finally:
                self.synths.pop(bus, None)
        if first is not None:
            raise first
