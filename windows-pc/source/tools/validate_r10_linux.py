"""Linux/Xvfb development validation for R10 (PowerShell tests remain Windows-only)."""
import json
import os
import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def flatten(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from flatten(t)
        else:
            yield t

if __name__ == '__main__':
    discovered = list(flatten(unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_*.py')))
    excluded = [t for t in discovered if os.name != 'nt' and 'test_validation072.BuildPython072Tests.' in t.id()]
    selected = [t for t in discovered if t not in excluded]
    print('Environment:', sys.platform, 'Discovered:', len(discovered),
          'Executed:', len(selected), 'Unavailable Windows PowerShell tests:', len(excluded), flush=True)
    result = unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(selected))
    report = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'platform': sys.platform,
        'discovered': len(discovered),
        'executed': result.testsRun,
        'excluded_windows_powershell': [t.id() for t in excluded],
        'skipped': len(result.skipped),
        'failures': len(result.failures),
        'errors': len(result.errors),
        'passed_without_skip': result.testsRun-len(result.skipped)-len(result.failures)-len(result.errors),
        'success': result.wasSuccessful(),
        'caveat': 'Windows EXE/Google Drive real integration require a Windows machine and explicit account authorization.'
    }
    (ROOT / 'QA_R10_LINUX.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('\nR10 VALIDATION REPORT:', json.dumps(report,ensure_ascii=False),flush=True)
    sys.exit(0 if result.wasSuccessful() else 1)
