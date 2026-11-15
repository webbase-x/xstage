"""Accumulate high-resolution wheel deltas; five percent per standard notch."""
import math


def wheel_change(remainder, delta=0, button=None):
    if button in (4, 5):
        return 0, 5 if button == 4 else -5
    total = remainder + float(delta or 0)
    steps = math.trunc(total / 120)
    return total - steps * 120, steps * 5
