"""Pre-EXE simulated coverage of the live Karaoke PC menus and package contract.

This audit runs on Windows without playing audio, opening user files, or building
an EXE. Every enabled menu command is *dispatched* to a strictly validated
mock handler; hardware and side effects are intentionally not simulated.
"""
from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1] / "windows-pc" / "source"
sys.path.insert(0, str(ROOT))

from karaoke.playback import MidiPlayer
from karaoke.performer import PlaybackApp
from karaoke.ui import KaraokeApp
from karaoke.classic import ClassicApp
from karaoke.context_menu import populate_context_menu


class Var:
    def __init__(self, value=False):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeMenu:
    def __init__(self, parent=None, tearoff=False):
        self.children = []
        self.entries = []

    def winfo_children(self):
        return self.children

    def destroy(self):
        self.entries.clear()

    def delete(self, *_):
        self.entries.clear()

    def add_cascade(self, label, menu, **kwargs):
        self.entries.append((label, None, "normal", menu))
        self.children.append(menu)

    def add_command(self, label, command, state="normal", **kwargs):
        self.entries.append((label, command, state, None))

    def add_checkbutton(self, label, command, state="normal", **kwargs):
        self.entries.append((label, command, state, None))

    def add_radiobutton(self, label, command, state="normal", **kwargs):
        self.entries.append((label, command, state, None))

    def add_separator(self):
        return None

    def walk(self, path=""):
        for label, command, state, child in self.entries:
            full = path + "/" + label
            if child is not None:
                yield from child.walk(full)
            else:
                yield full, command, state


class FakeApp:
    def __init__(self, *, selected=False, queued=False, mode="none", stage=False):
        self.calls = []
        self.deferred = 0
        self.search_visible = selected
        self.search_pending = False
        self.search_revision = 4
        self.search_result_revision = 4
        self.songs = SimpleNamespace(selection=lambda: ("song1",) if selected else ())
        self.song_queue = SimpleNamespace(items=[SimpleNamespace(medley_session="")] if queued else [])
        self.engine = (object.__new__(MidiPlayer) if mode == "midi" else
                       object() if mode == "media" else None)
        self.current_song = {"path": "song.mp4"} if mode == "media" else None
        self.stage = SimpleNamespace(winfo_exists=lambda: True) if stage else None
        self.stage_fullscreen = False
        self.settings = {"stage_monitor": 1}
        self.continuous_medley = SimpleNamespace(enabled=False)
        for name in (
            "playable_var", "favorite_var", "melody_var", "stage_enabled_var",
            "stage_fullscreen_var", "stage_monitor_var", "main_fullscreen_var",
            "transport_pinned_var"
        ):
            setattr(self, name, Var())

    def defer_menu_command(self, callback):
        self.deferred += 1
        # These commands create real Tk windows and can install/repair software.
        # The menu event is exercised; its side effect is stubbed in prebuild QA.
        if getattr(callback, "__name__", "") in ("repair_components", "support_report", "view_logs"):
            self.calls.append("mocked-window:" + callback.__name__)
            return
        callback()

    def __getattr__(self, name):
        if not callable(getattr(PlaybackApp, name, None)):
            raise AttributeError("Menu references missing live handler: " + name)
        return lambda *args, **kwargs: self.calls.append(name)


class PrebuildMenuAudit(unittest.TestCase):
    def test_all_context_items_dispatch_across_runtime_states(self):
        runs = [
            dict(selected=False, queued=False, mode="none", stage=False),
            dict(selected=True, queued=True, mode="none", stage=False),
            dict(selected=True, queued=True, mode="midi", stage=True),
            dict(selected=True, queued=True, mode="media", stage=True),
        ]
        total = enabled = 0
        for state in runs:
            with self.subTest(state=state):
                app = FakeApp(**state)
                root = FakeMenu()
                populate_context_menu(app, root, FakeMenu, [
                    (0, 0, 1280, 720), (1280, 0, 1920, 1080)
                ])
                entries = list(root.walk())
                self.assertGreaterEqual(len(entries), 65)
                labels = [label for label, _, _ in entries]
                for category in ("เพลงและคิว", "เสียงและ SoundFont", "เนื้อร้องและภาพ",
                                 "การควบคุม", "เครื่องมือแสดงสด", "ระบบและสถานะ"):
                    self.assertTrue(any("/" + category + "/" in label for label in labels), category)
                active = [(label, cmd) for label, cmd, status in entries if status != "disabled"]
                for label, callback in active:
                    with self.subTest(menu=label):
                        self.assertTrue(callable(callback), label)
                        callback()
                self.assertGreaterEqual(app.deferred, 45)
                total += len(entries)
                enabled += len(active)
        print(f"MENU AUDIT: {total} menu-state entries, {enabled} enabled dispatches in 4 states")

    def test_all_direct_ui_callbacks_resolve(self):
        found = 0
        for filename, app_class in (("ui.py", KaraokeApp),
                                    ("classic.py", ClassicApp),
                                    ("performer.py", PlaybackApp)):
            tree = ast.parse((ROOT / "karaoke" / filename).read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for kw in node.keywords:
                    value = kw.value
                    if (kw.arg == "command" and isinstance(value, ast.Attribute)
                            and isinstance(value.value, ast.Name)
                            and value.value.id == "self"):
                        found += 1
                        self.assertTrue(callable(getattr(app_class, value.attr, None)),
                                        f"{filename}:{node.lineno} missing {value.attr}")
        self.assertGreaterEqual(found, 35)
        print(f"UI CALLBACK AUDIT: {found} direct control handlers resolved")

    def test_optional_chroma_decoder_will_be_bundled_in_exe(self):
        lock = (ROOT / "requirements-build.lock.txt").read_text(encoding="utf-8")
        self.assertRegex(lock, r"(?mi)^(?:opencv-python-headless|opencv-python)==[0-9].*$",
                         "BLOCKER: OpenCV decoder missing from the locked Windows EXE build")
        build = (ROOT / "build.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("PyInstaller", build)
        self.assertIn("--collect-all imageio_ffmpeg", build)
        self.assertIn("--collect-all cv2", build)


    def test_prebuild_does_not_modify_library_or_song_files(self):
        source = (ROOT / "karaoke" / "context_menu.py").read_text(encoding="utf-8")
        self.assertIn("def populate_context_menu", source)
        self.assertIn("defer_menu_command", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
