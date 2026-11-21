"""Best-effort live ASIO -> BASSMIDI fallback, never selected by default.

The MIDI scheduler owns all calls to this adapter. On failure the ASIO output
is stopped first; the BASS output then receives a compact snapshot of current
controllers, programs, pitch bends and sounding notes. Active note attacks may
restart on failover; uninterrupted hardware audio is not guaranteed.
"""
import logging


class FailoverMidiOutput:
    def __init__(self, primary, fallback_factory, *, notify=None):
        self.primary = primary
        self.active = primary
        self.fallback_factory = fallback_factory
        self.notify = notify
        self.reason = ''
        self._state = {}
        self._notes = {}
        self._fx = {}
        self._closed = False

    def _remember(self, data):
        if not data:
            return
        code = data[0]
        if not 0x80 <= code <= 0xef:
            return
        channel = code & 15
        kind = code & 0xf0
        if kind in (0x80, 0x90) and len(data) >= 3:
            key = (channel, data[1])
            if kind == 0x80 or data[2] == 0:
                self._notes.pop(key, None)
            else:
                self._notes[key] = bytes(data)
        elif kind == 0xb0 and len(data) >= 3:
            control = data[1]
            if control in (120, 123):
                for key in [item for item in self._notes if item[0] == channel]:
                    self._notes.pop(key, None)
            if control == 121:
                for key in [item for item in self._state if item[0] == channel and item[1] == 0xb0]:
                    self._state.pop(key, None)
            else:
                self._state[(channel, kind, control)] = bytes(data)
        elif kind in (0xc0, 0xd0, 0xe0):
            self._state[(channel, kind, -1)] = bytes(data)

    def _recover(self, error):
        if self.active is not self.primary:
            raise error
        # Do not create BASS while an ASIO driver still owns the output.
        # If ASIO cannot free its callback, stop rather than risk a use-after-free.
        self.primary.close()
        replacement = self.fallback_factory()
        try:
            for message in self._state.values():
                replacement.send(message)
            for message in self._notes.values():
                replacement.send(message)
            for (method, key), (args, kwargs) in self._fx.items():
                getattr(replacement, method)(*args, **kwargs)
        except Exception:
            replacement.close()
            raise
        self.active = replacement
        self.reason = 'ASIO หยุดทำงาน เปลี่ยนเป็น BASS: ' + str(error)
        logging.warning('%s', self.reason)
        if self.notify is not None:
            try:
                self.notify(self.reason)
            except Exception:
                logging.exception('Unable to surface ASIO fallback notice')

    def poll(self):
        if self.active is self.primary:
            check = getattr(self.primary, 'check_health', None)
            if check is not None:
                try:
                    check()
                except (OSError, RuntimeError) as exc:
                    self._recover(exc)

    def send(self, data):
        self._remember(data)
        if self.active is self.primary:
            try:
                self.poll()
                # poll may already have switched and replayed this event.
                if self.active is not self.primary:
                    return
                self.primary.send(data)
                return
            except (OSError, RuntimeError) as exc:
                if self.active is self.primary:
                    self._recover(exc)
                    return
                raise
        self.active.send(data)

    def reset(self):
        self._state.clear()
        self._notes.clear()
        if self.active is self.primary:
            try:
                self.primary.reset()
                return
            except (OSError, RuntimeError) as exc:
                self._recover(exc)
                return
        self.active.reset()

    def _effect(self, method, key, *args, **kwargs):
        self._fx[(method, key)] = (args, dict(kwargs))
        if self.active is self.primary:
            try:
                self.poll()
                if self.active is not self.primary:
                    return
                getattr(self.primary, method)(*args, **kwargs)
                return
            except (OSError, RuntimeError) as exc:
                if self.active is self.primary:
                    self._recover(exc)
                    return
                raise
        getattr(self.active, method)(*args, **kwargs)

    def set_channel_tone(self, channel, *args, **kwargs):
        return self._effect('set_channel_tone', channel, channel, *args, **kwargs)

    def set_drum_tone(self, note, *args, **kwargs):
        return self._effect('set_drum_tone', note, note, *args, **kwargs)

    def set_channel_eq(self, channel, *args, **kwargs):
        return self._effect('set_channel_eq', channel, channel, *args, **kwargs)

    def close(self):
        if self._closed:
            return
        self.active.close()
        self._closed = True
