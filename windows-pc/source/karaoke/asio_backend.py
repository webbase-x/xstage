"""Explicit ASIO preference with safe BASS fallback at initialization.

Experimental ASIO is never selected by default. Failures are surfaced through
an optional diagnostic callback; no silent claim of ASIO playback.
"""
import logging

from .bass import BassSynth


def create_midi_output(native, settings, *, notify=None,
                       bass_factory=BassSynth, asio_factory=None):
    settings = settings or {}
    config = settings.get('asio_output')
    if not isinstance(config, dict) or config.get('enabled') is not True:
        return bass_factory(native, settings=settings)
    if asio_factory is None:
        from .asio_midi_output import AsioMidiOutput
        asio_factory = AsioMidiOutput
    try:
        device = config.get('device')
        channel = config.get('channel', 0)
        if type(device) is not int or device < 0:
            raise ValueError('ต้องเลือก ASIO device ID')
        if type(channel) is not int or channel < 0 or channel % 2:
            raise ValueError('ASIO channel ต้องเป็นเลขคู่')
        from .asio_failover import FailoverMidiOutput
        primary = asio_factory(native, device=device, channel=channel, settings=settings)
        return FailoverMidiOutput(
            primary, lambda: bass_factory(native, settings=settings), notify=notify)
    except Exception as exc:
        if notify is not None:
            try:
                notify('ASIO เริ่มทำงานไม่สำเร็จ ใช้ BASS แทน: ' + str(exc))
            except Exception:
                # The audio fallback succeeded; a failed UI callback is not a
                # playback error. Keep a concise diagnostic without a traceback
                # that CI would misinterpret as an unhandled exception.
                logging.warning('Unable to surface ASIO startup fallback notice')
        return bass_factory(native, settings=settings)
