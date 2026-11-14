"""Fixed-memory reservoir for catalog candidates; no full-table Python list."""
from .library import SearchCancelled

def reservoir(rows, capacity, rng, accept=lambda row: True, cancelled=lambda: False):
    if capacity < 1:
        raise ValueError('capacity must be positive')
    selected = []
    matched = 0
    for row in rows:
        if cancelled():
            raise SearchCancelled()
        if not accept(row):
            continue
        matched += 1
        if len(selected) < capacity:
            selected.append(row)
        else:
            index = rng.randrange(matched)
            if index < capacity:
                selected[index] = row
    return selected, matched
