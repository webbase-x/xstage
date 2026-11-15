"""Measured, conservative one-bar progress for X-Stage Online's three-page UI.

The underlying pipeline is unchanged. The UI only estimates time from completed
song work; it never treats a phase message or a Google quota refresh as progress.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import math


def readable_duration(seconds):
    """Friendly Thai duration; never display a spurious sub-minute ETA."""
    if not math.isfinite(seconds) or seconds < 0:
        return 'ยังประเมินไม่ได้'
    minutes = max(1, math.ceil(seconds / 60))
    if minutes >= 1440:
        days, remainder = divmod(minutes, 1440)
        hours = math.ceil(remainder / 60)
        return f'{days} วัน' + (f' {hours} ชม.' if hours else '')
    hours, remainder = divmod(minutes, 60)
    return f'{hours} ชม. {remainder} นาที' if hours else f'{remainder} นาที'


class OverallSyncEstimate:
    """One measured percentage; 100% is reserved for confirmed success.

    0..95% is the completed-song part of the pipeline. The final 5% is
    reserved for catalog publication and any integrity verification. Where a
    verifier reports its own count, it contributes at most 4% (95..99%).
    The reservation is a presentation convention, not a claimed time weight.
    """

    def __init__(self):
        self._running = False
        self.percent = 0.0
        self._start_song = None
        self._song_first = 0
        self._start_verify = None
        self._verify_first = 0

    def observe(self, *, running, completed, step, done=0, total=0,
                unit='เพลง', message='', now, wall_clock=None):
        if wall_clock is None:
            wall_clock = datetime.now().astimezone()
        if running and not self._running:
            self.percent = 0.0
            self._start_song = None
            self._song_first = 0
            self._start_verify = None
            self._verify_first = 0
        self._running = running
        if not running:
            if completed:
                self.percent = 100.0
                return self.percent, 'เสร็จสมบูรณ์แล้ว'
            return self.percent, 'ยังไม่เริ่มงานหรือหยุดซิงค์แล้ว'

        step = int(step or 0)
        done, total = max(0, int(done)), max(0, int(total))
        if step < 4:
            return self.percent, 'กำลังเตรียมงาน • จะประเมินเวลาเมื่อเริ่มประมวลผลเพลง'

        if step == 4:
            # A database row preflight can have a known 100% but it is not
            # completed song work. Keep the displayed sync bar unchanged.
            if 'แถวฐานเพลง' in unit or 'แถวฐานเพลง' in message or not total:
                return self.percent, 'กำลังตรวจข้อมูล • ยังประเมินเวลาจบไม่ได้'
            self.percent = max(self.percent, min(95.0, 95.0 * min(done, total) / total))
            if self._start_song is None:
                self._start_song = float(now)
                self._song_first = done
            gained = max(0, done - self._song_first)
            elapsed = max(0., float(now) - self._start_song)
            # Avoid a misleading ETA based on one quick/skipped song. The
            # estimate is recalculated from actual completion events.
            if gained < 3 or elapsed < 8:
                return self.percent, 'กำลังวัดความเร็วจริงเพื่อประเมินเวลาเสร็จ'
            rate = gained / elapsed
            if not math.isfinite(rate) or rate <= 0:
                return self.percent, 'ยังประเมินเวลาไม่ได้'
            remaining = max(0, total-done) / rate
            if not remaining:
                return self.percent, 'ประมวลผลเพลงครบ • รอเผยแพร่และตรวจฐานเว็บ'
            return self.percent, self._eta_text(remaining, wall_clock,
                ' • เวลาตรวจฐานเว็บอาจเพิ่มขึ้น')

        self.percent = max(self.percent, 95.0)
        # In phase 5, only an explicit verifier count is a real fraction of
        # integrity work. A generic completed count of total/total is not.
        verifying = message.startswith('ตรวจความครบของเพลงเว็บ:')
        if verifying and total:
            self.percent = max(self.percent, min(99.0, 95.0 + 4.0 * min(done,total)/total))
            if self._start_verify is None:
                self._start_verify = float(now)
                self._verify_first = done
            gained = max(0, done-self._verify_first)
            elapsed = max(0.,float(now)-self._start_verify)
            if gained >= 3 and elapsed >= 8 and done < total:
                remaining = (total-done) * elapsed / gained
                return self.percent, self._eta_text(remaining,wall_clock,
                    ' • หลังตรวจครบอาจมีขั้นตอนปิดงาน')
        return self.percent, 'กำลังเผยแพร่/ตรวจสอบฐานเว็บ • เวลาขึ้นอยู่กับ Google Drive'

    @staticmethod
    def _eta_text(remaining, wall_clock, suffix):
        if not math.isfinite(remaining) or remaining < 0:
            return 'ยังประเมินเวลาจบไม่ได้'
        # Local clock is used only to show the approximate finish time.
        finish = wall_clock + timedelta(seconds=remaining)
        return (f'คาดว่าเสร็จราว {finish:%H:%M} น. '
                f'(อีกประมาณ {readable_duration(remaining)}){suffix}')
