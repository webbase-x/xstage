"""Isolated native Win32 GUI regression runner, before building an EXE.

It reuses the established Windows GUI test classes from build-windows-pc.yml.
Each test executes in its own process so dialogs cannot contaminate later tests.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tkinter as tk
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "windows-pc" / "source"
TESTS = SOURCE / "tests"
CLASSES = (
    "test_auditfix073.DetailGui073Tests",
    "test_eq_interaction.RackIntegrationTests",
    "test_history070.HistoryRecoveryGuiTests",
    "test_quality090.QualityGuiTests",
    "test_recovery_ui060.RecoveryUiTests",
    "test_song_workspace79.WorkspaceGuiTests",
    "test_soundfont80.SoundfontGui80Tests",
    "test_soundfont81.SoundfontGui81Tests",
)
RETIRED = {"test_quality090.QualityGuiTests.test_scan_review_cancel_delete_and_restore"}


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item.id()


def main():
    if sys.platform != "win32":
        raise RuntimeError("Native GUI gate requires Windows")
    window = tk.Tk()
    try:
        window.geometry("320x200")
        window.update()
        if window.tk.call("tk", "windowingsystem") != "win32" or not window.winfo_ismapped():
            raise RuntimeError("Cannot map a native Win32 Tk window")
    finally:
        window.destroy()

    sys.path[:0] = [str(TESTS), str(SOURCE)]
    tests = []
    for name in CLASSES:
        tests.extend(flatten(unittest.defaultTestLoader.loadTestsFromName(name)))
    env = dict(os.environ, DISPLAY="xstage-native-win32-test-opt-in",
               PYTHONPATH=os.pathsep.join([str(TESTS), str(SOURCE)]),
               PYTHONUTF8="1", PYTHONIOENCODING="utf-8:backslashreplace")
    summary = {"passed": [], "failed": [], "skipped_retired": []}
    for name in tests:
        if name in RETIRED:
            summary["skipped_retired"].append(name)
            continue
        print("GUI TEST:", name, flush=True)
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "unittest", "-v", name], cwd=SOURCE,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=90, env=env,
            )
            print(proc.stdout[-3000:] + proc.stderr[-3000:], flush=True)
            if proc.returncode == 0 and "OK (skipped=" not in (proc.stdout + proc.stderr) and "Ran 0 tests" not in (proc.stdout + proc.stderr):
                summary["passed"].append(name)
            else:
                summary["failed"].append({"name": name, "reason": "exit " + str(proc.returncode)})
        except subprocess.TimeoutExpired:
            summary["failed"].append({"name": name, "reason": "timeout >90s"})
    output = ROOT / "prebuild-gui-results.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("GUI SUMMARY:", len(summary["passed"]), "passed;", len(summary["failed"]),
          "failed;", len(summary["skipped_retired"]), "retired", flush=True)
    if summary["failed"] or len(summary["passed"]) < 15:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
