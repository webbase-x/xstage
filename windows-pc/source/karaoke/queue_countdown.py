"""Non-blocking, occurrence-specific countdown for the first idle queue item."""
import math
import time


class FirstQueueCountdown:
    def __init__(self):
        self.head = self.blocked = None
        self.deadline = None

    def cancel(self, head=None):
        self.blocked = head
        self.head = self.deadline = None

    def update(self, head, occupied, now):
        if head is None:
            self.cancel()
            return 0, False
        if occupied:
            self.head = self.deadline = None
            return 0, False
        if head is self.blocked:
            return 0, False
        if head is not self.head:
            self.head, self.deadline = head, now + 5
        remaining = max(0, math.ceil(self.deadline-now))
        if remaining == 0:
            self.cancel(head)  # A playback failure must not retry every frame.
            return 0, True
        return remaining, False


def cancel_countdown(app):
    countdown = app.__dict__.get('_first_queue_countdown')
    if countdown is not None:
        items = app.song_queue.items
        countdown.cancel(items[0] if items else None)
    app.__dict__['_queue_countdown_seconds'] = 0


def tick_countdown(app):
    countdown = app.__dict__.get('_first_queue_countdown')
    if countdown is None:
        countdown = app.__dict__['_first_queue_countdown'] = FirstQueueCountdown()
    items = app.song_queue.items
    seconds, due = countdown.update(items[0] if items else None,
        app.engine is not None or app.current_song is not None, time.monotonic())
    previous = app.__dict__.get('_queue_countdown_seconds', 0)
    app.__dict__['_queue_countdown_seconds'] = seconds
    if seconds and seconds != previous:
        app.status_var.set(f'เริ่มเพลงแรกใน {seconds} วินาที • กดหยุดเพื่อยกเลิก')
    if due:
        app.next_song()
