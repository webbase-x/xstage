"""Popular medley hits from a durable playback ledger (v0.9.38)."""
from .play_stats import history_hits

POPULAR_PERIODS = {'all': None, '7': 7, '30': 30, '90': 90}
COUNTED_STATUSES = frozenset(('completed', 'medley'))
