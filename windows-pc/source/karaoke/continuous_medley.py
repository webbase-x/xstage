"""Bounded, non-blocking continuous random medley grouped by indexed song rhythm.

The catalog's *rhythm* field is the only category source. Unclassified songs
remain in their own category; the program never guesses genres from titles.
"""
from __future__ import annotations

import logging
import random
import threading
from dataclasses import dataclass, field

from .random_medley import build_preview, read_rhythms

BATCH_SIZE = 6
REFILL_AT = 2


def next_category(categories, position, rng=None):
    """Cycle across the detected categories, changing order each pass."""
    rng = rng if rng is not None else random
    if not categories:
        return None, 0
    if position >= len(categories):
        rng.shuffle(categories)
        position = 0
    item = categories[position]
    return item, position + 1


@dataclass
class ContinuousMedley:
    generation: int = 0
    enabled: bool = False
    loading: bool = False
    categories: list = field(default_factory=list)
    position: int = 0
    recent_ids: set = field(default_factory=set)
    session_ids: set = field(default_factory=set)

    def stop(self, app):
        self.generation += 1
        self.enabled = False
        self.loading = False
        self.categories.clear()
        self.recent_ids.clear()
        self.position = 0
        sessions = tuple(self.session_ids)
        self.session_ids.clear()
        for session in sessions:
            app.song_queue.cancel_medley(session)
        if sessions:
            app.refresh_queue()
        return len(sessions)

    def start(self, app):
        self.stop(app)
        self.enabled = True
        self.fill(app)

    def fill(self, app):
        if not self.enabled or self.loading or len(app.song_queue.items) > REFILL_AT:
            return
        self.loading = True
        generation = self.generation
        # Tk widgets and queue mutations are touched only on the UI thread.
        excluded = {item.song_id for item in app.song_queue.items}
        if app.current_item:
            excluded.add(app.current_item.song_id)
        excluded.update(self.recent_ids)
        library_path = app.library.path

        def work():
            result = None
            chosen = None
            error = None
            try:
                rng = random.Random()
                categories = list(self.categories) if self.categories else list(read_rhythms(library_path))
                if not self.categories:
                    rng.shuffle(categories)
                position = self.position
                # The next batch uses one detected category; categories rotate
                # so every available rhythm gets an opportunity to play.
                for attempt in range(max(1, len(categories))):
                    chosen, position = next_category(categories, position, rng)
                    if chosen is None:
                        break
                    result = build_preview(library_path, 'rhythm', BATCH_SIZE,
                                           rhythm=chosen[0], excluded_ids=excluded, rng=rng)
                    if result.rows:
                        break
                else:
                    result = None
                if not result or not result.rows:
                    # The library can be smaller than the recent-play window.
                    # Repeating from the catalog is preferable to stopping.
                    excluded = {item.song_id for item in app.song_queue.items}
                    if app.current_item:
                        excluded.add(app.current_item.song_id)
                    for _ in range(len(categories)):
                        chosen, position = next_category(categories, position, rng)
                        if chosen is None:
                            break
                        result = build_preview(library_path, 'rhythm', BATCH_SIZE,
                                               rhythm=chosen[0], excluded_ids=excluded, rng=rng)
                        if result.rows:
                            break
                def apply():
                    if generation != self.generation or not self.enabled:
                        return
                    self.loading = False
                    # Keep only sessions still waiting in the queue; this runs
                    # indefinitely without accumulating stale batch identifiers.
                    pending = {item.medley_session for item in app.song_queue.items if item.medley_session}
                    self.session_ids.intersection_update(pending)
                    self.categories = categories
                    self.position = position
                    if not result or not result.rows:
                        self.enabled = False
                        app.status_var.set('สุ่มเมดเลย์หยุด: ไม่พบเพลงที่เปิดได้ในคลัง')
                        return
                    items = [candidate.item for candidate in result.rows]
                    before = {item.medley_session for item in app.song_queue.items if item.medley_session}
                    count = app.enqueue_random_medley(items)
                    if count:
                        after = {item.medley_session for item in app.song_queue.items if item.medley_session}
                        self.session_ids.update(after - before)
                        self.recent_ids.update(item.song_id for item in items)
                        # Bound memory even when running for many days.
                        if len(self.recent_ids) > 2000:
                            self.recent_ids = set(item.song_id for item in items)
                        label = chosen[1] or 'ยังไม่จัดประเภท'
                        app.status_var.set(f'เมดเลย์ต่อเนื่อง · {label} · เพิ่ม {count} เพลง')
                        if app.engine is None and app.current_song is None:
                            app.next_song()
                    else:
                        # No automatic spin loop if queue or catalog changed.
                        app.status_var.set('เมดเลย์ต่อเนื่อง: เพิ่มเพลงไม่ได้ กรุณาตรวจคลังเพลง')
                        self.enabled = False
                app.after(0, apply)
            except Exception as exc:
                error = exc
                logging.exception('Continuous medley refill failed')
                def fail():
                    if generation != self.generation:
                        return
                    self.loading = False
                    self.enabled = False
                    app.status_var.set('เมดเลย์ต่อเนื่องหยุด: ' + str(error))
                app.after(0, fail)
        threading.Thread(target=work, daemon=True, name='XStageContinuousMedley').start()
