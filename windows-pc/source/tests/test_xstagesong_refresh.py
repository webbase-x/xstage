"""An explicitly selected Song Studio PC folder refreshes on catalog generation."""
import tempfile
import unittest
from pathlib import Path
from types import MethodType

from karaoke.classic import ClassicApp


class WatchedApp:
    closing = False
    scanning = False

    def __init__(self, selected):
        self.settings = {"xstagesong_pc_folder": selected}
        self._pc_last_attempt = None
        self.imported = []
        self.scheduled = []
        self._watch_songstudio_pc_catalog = MethodType(
            ClassicApp._watch_songstudio_pc_catalog, self)

    def after(self, delay, callback):
        self.scheduled.append((delay, callback))
        return len(self.scheduled)

    def _start_songstudio_pc_import(self, root):
        self.imported.append(str(root))


class PCRefreshTests(unittest.TestCase):
    def test_requires_operator_selected_folder(self):
        app = WatchedApp("")
        app._watch_songstudio_pc_catalog()
        self.assertEqual(app.imported, [])
        self.assertEqual(app.scheduled[-1][0], 12000)

    def test_refresh_only_when_current_pointer_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "XStageSong"
            folder = root / "LYRICS"
            folder.mkdir(parents=True)
            pointer = folder / "current.json"
            pointer.write_text('{"generation":"first"}', encoding="utf-8")
            app = WatchedApp(str(root))
            app._watch_songstudio_pc_catalog()
            self.assertEqual(app.imported, [str(root)])
            app._watch_songstudio_pc_catalog()
            self.assertEqual(len(app.imported), 1)
            app.scanning = True
            pointer.write_text('{"generation":"second","songCount":2}', encoding="utf-8")
            app._watch_songstudio_pc_catalog()
            self.assertEqual(len(app.imported), 1)
            app.scanning = False
            app._watch_songstudio_pc_catalog()
            self.assertEqual(len(app.imported), 2)
            app._watch_songstudio_pc_catalog()
            self.assertEqual(len(app.imported), 2)


if __name__ == "__main__":
    unittest.main()
