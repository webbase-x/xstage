"""Reliable Windows Song Studio PC entrypoint with persistent crash logs.

Runs the existing Engine in the main thread, which Qt requires. All errors
remain available even when pythonw.exe has no console attached.
"""
from __future__ import annotations

import faulthandler
import os
from pathlib import Path
import runpy
import sys
import traceback

ROOT = Path(__file__).resolve().parent


def main():
    error_log = ROOT / "engine-startup-error.log"
    output_log = ROOT / "engine-startup-output.log"
    # Never include the local API auth fragment or OAuth tokens in logs.
    with error_log.open("w", encoding="utf-8", buffering=1) as err, \
            output_log.open("w", encoding="utf-8", buffering=1) as out:
        sys.stderr = err
        sys.stdout = out
        faulthandler.enable(file=err, all_threads=True)
        try:
            os.chdir(ROOT)
            runpy.run_path(str(ROOT / "engine.py"), run_name="__main__")
        except BaseException:
            traceback.print_exc(file=err)
            return 1
        finally:
            faulthandler.disable()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
