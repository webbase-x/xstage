"""Run the complete build gate and preserve every traceback in a UTF-8 log."""
from pathlib import Path
import platform
import json
from datetime import datetime, timezone
import sys
import unittest
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Always prefer the tests directory for top-level unittest imports; legacy
# extracted patches can otherwise shadow test_*.py modules at source root.
sys.path.insert(0, str(ROOT / 'tests'))


class Tee:
    def __init__(self, terminal, log):
        self.terminal, self.log = terminal, log
    def write(self, text):
        self.log.write(text)
        self.log.flush()
        try:
            self.terminal.write(text)
        except UnicodeEncodeError:
            encoding = getattr(self.terminal, 'encoding', None) or 'ascii'
            self.terminal.write(text.encode(encoding, 'backslashreplace').decode(encoding))
    def flush(self):
        self.log.flush()
        self.terminal.flush()


def summarize(result, *, fatal=None):
    """Machine-readable diagnostic; does not change the release gate decision."""
    def entries(items):
        return [{'test': test.id() if hasattr(test, 'id') else str(test),
                 'traceback': traceback_text[-10000:]}
                for test, traceback_text in items]
    payload = {
        'schema': 1,
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'platform': platform.platform(),
        'python': sys.version.split()[0],
        'tests_run': result.testsRun if result is not None else 0,
        'failures': entries(result.failures) if result is not None else [],
        'errors': entries(result.errors) if result is not None else [],
        'skipped_count': len(result.skipped) if result is not None else 0,
        'skipped': [{'test': test.id() if hasattr(test, 'id') else str(test),
                     'reason': reason} for test, reason in (result.skipped if result is not None else [])],
        'fatal': fatal,
        'pass': bool(result is not None and result.wasSuccessful() and fatal is None),
    }
    return payload


def save_summary(result, *, fatal=None):
    path = ROOT / 'build-tests-summary.json'
    payload = summarize(result, fatal=fatal)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return payload


def main():
    summary_path = ROOT / 'build-tests-summary.json'
    if summary_path.exists():
        summary_path.unlink()   # never display the prior build's result
    with (ROOT/'build-tests.log').open('w', encoding='utf-8') as log:
        stream = Tee(sys.stderr, log)
        stream.write(f'Python: {sys.version}\nPlatform: {platform.platform()}\nSource: {ROOT}\n\n')
        stream.write('DISCOVER BEGIN\n')
        try:
            suite = unittest.defaultTestLoader.discover(str(ROOT/'tests'))
            stream.write(f'DISCOVER COMPLETE: {suite.countTestCases()} tests\n')
            result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
            payload = save_summary(result)
            if not payload['pass']:
                stream.write('\nFAILED TEST IDS (for Windows diagnostics):\n')
                for detail in payload['failures'] + payload['errors']:
                    stream.write('  - ' + detail['test'] + '\n')
            stream.write(f"SUMMARY: tests={payload['tests_run']} failures={len(payload['failures'])} errors={len(payload['errors'])} skipped={payload['skipped_count']}\n")
            stream.write('SUMMARY FILE: ' + str(summary_path) + '\n')
            stream.write('BUILD TEST RESULT: ' + ('PASS' if payload['pass'] else 'FAIL') + '\n')
            return 0 if payload['pass'] else 1
        except BaseException:
            detail = traceback.format_exc()
            save_summary(None, fatal=detail)
            stream.write('BUILD TEST ERROR BEFORE COMPLETION:\n' + detail + '\n')
            stream.write('SUMMARY FILE: ' + str(summary_path) + '\n')
            return 1


if __name__ == '__main__':
    raise SystemExit(main())
