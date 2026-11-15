"""Pure, testable progress state for the Windows X-Stage Online sync dialog.

A worker can be legitimately busy in a Google browser login, a slow soundfont
preflight or a network call without emitting progress. Keep the user informed
about the current phase and elapsed time, without inventing completed work.
"""
from __future__ import annotations

import time


class OnlineSyncFeedback:
    STEPS = 5

    def __init__(self, now=None):
        timestamp = time.monotonic() if now is None else float(now)
        self.step = 1
        self.name = 'ตรวจฐานข้อมูลเพลง'
        self.started = timestamp
        self.last_signal = timestamp
        self.done = 0
        self.total = 0
        self.unit = 'เพลง'

    @property
    def header(self):
        return f'ขั้นตอนที่ {self.step}/{self.STEPS} • {self.name}'

    def begin(self, step, name, *, now=None):
        if step not in range(1, self.STEPS + 1):
            raise ValueError('ขั้นตอนซิงค์ไม่ถูกต้อง')
        timestamp = time.monotonic() if now is None else float(now)
        self.step = step
        self.unit = 'เพลง'
        self.name = str(name)
        self.started = timestamp
        self.last_signal = timestamp
        self.done = 0
        self.total = 0

    def signal(self, done=0, total=0, *, now=None):
        timestamp = time.monotonic() if now is None else float(now)
        done, total = max(0, int(done)), max(0, int(total))
        if (done, total) != (self.done, self.total):
            self.last_signal = timestamp
        self.done, self.total = min(done, total) if total else done, total

    def activity(self, *, now=None):
        """A real worker message is progress even if its total is unknown.

        Never call this from an idle UI timer: that would hide a stuck request.
        """
        self.last_signal = time.monotonic() if now is None else float(now)

    def indicator(self, *, now=None):
        timestamp = time.monotonic() if now is None else float(now)
        elapsed = max(0, int(timestamp - self.started))
        pulse = ('●○○', '○●○', '○○●')[elapsed % 3]
        if self.total:
            unit = 'แถวฐานเพลง' if self.step == 1 or self.unit == 'แถวฐานเพลง' else 'เพลง'
            prefix = f'{self.done:,} / {self.total:,} {unit} • {100 * self.done / self.total:.1f}%'
        else:
            prefix = 'กำลังทำงาน' if self.step != 3 else 'รอการอนุญาตจาก Google ในเบราว์เซอร์'
        text = f'{prefix} • {elapsed} วินาที • {pulse}'
        if timestamp - self.last_signal >= 30:
            text += (' • ยังไม่ได้รับความคืบหน้าใหม่จากงานจริง'
                     ' (Google Drive/ดิสก์อาจตอบช้า ตรวจอินเทอร์เน็ต หรือกดหยุด)')
        return text
