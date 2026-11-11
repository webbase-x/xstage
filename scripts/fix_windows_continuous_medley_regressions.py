#!/usr/bin/env python3
"""Repair 10 Windows v1.0.76 continuous-medley regression errors after ZIP import.

Only the three precisely matched code regions are changed. Refuse unexpected
source versions rather than corrupting performer.py. Idempotent.
"""
from pathlib import Path
import sys

target = Path(__file__).resolve().parents[1] / "windows-pc/source/karaoke/performer.py"
if not target.is_file():
    raise SystemExit(f"Windows source not yet imported: {target}")
source = target.read_text(encoding="utf-8")
changes = [
    (
        """        if not hasattr(self, '_arrow_down'):
            from .continuous_medley import ContinuousMedley
        self.continuous_medley = ContinuousMedley()
        self._arrow_down, self._arrow_blocked = set(), set()
""",
        """        if not hasattr(self, '_arrow_down'):
            self._arrow_down, self._arrow_blocked = set(), set()
""",
    ),
    (
        """        if focused is None or focused.winfo_toplevel() not in (self, getattr(self, 'stage', None)):
            from .continuous_medley import ContinuousMedley
        self.continuous_medley = ContinuousMedley()
        self._arrow_down, self._arrow_blocked = set(), set()
""",
        """        if focused is None or focused.winfo_toplevel() not in (self, getattr(self, 'stage', None)):
            self._arrow_down, self._arrow_blocked = set(), set()
""",
    ),
    (
        """        self.continuous_medley.fill(self)
        from .transition_report import record""",
        """        continuous_medley = getattr(self, 'continuous_medley', None)
        if continuous_medley is not None and continuous_medley.enabled:
            continuous_medley.fill(self)
        from .transition_report import record""",
    ),
]
for before, after in changes:
    if before in source:
        if source.count(before) != 1:
            raise SystemExit("Ambiguous Windows source: repeated patch target")
        source = source.replace(before, after, 1)
    elif after not in source:
        raise SystemExit("Unexpected Windows source layout; refuse blind patch")
target.write_text(source, encoding="utf-8")
print("Windows continuous medley regression fixes verified:", target)
