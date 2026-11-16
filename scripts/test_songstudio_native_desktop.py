"""Regression checks for Song Studio PC's embedded native desktop."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "songstudio_desktop_window", ROOT / "songstudio-pc" / "desktop_window.py")
desktop = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(desktop)


class NativeDesktopContractTests(unittest.TestCase):
    def test_only_loopback_web_ui_is_allowed(self):
        self.assertEqual(desktop.validate_local_ui_url(
            "http://127.0.0.1:34567/#auth=token"), 34567)
        for bad in (
            "https://chatgpt.com/auth/login",
            "https://webbase-x.github.io/xstage/studio",
            "http://localhost:34567/",
            "http://127.0.0.1/",
            "http://evil.test:34567/",
            "file:///C:/index.html",
            "http://user:pass@127.0.0.1:1234/",
        ):
            with self.subTest(url=bad), self.assertRaises(ValueError):
                desktop.validate_local_ui_url(bad)

    def test_pc_ready_uses_embedded_qt_and_not_edge(self):
        source = (ROOT / "songstudio-pc" / "engine.py").read_text(encoding="utf-8")
        self.assertIn("if READY_BUNDLE:", source)
        self.assertIn("from desktop_window import run_desktop", source)
        self.assertIn("run_desktop(server, url, DATA,", source)
        self.assertNotIn('"--app=" + url', source)

    def test_bootstrap_restores_app_import_path_in_embedded_python(self):
        # Python's embeddable _pth excludes the application directory.
        # Running engine.py via runpy needs an explicit local import path.
        bootstrap = (ROOT / "songstudio-pc" / "desktop_bootstrap.py").read_text(
            encoding="utf-8")
        self.assertIn("sys.path.insert(0, root_path)", bootstrap)
        self.assertIn('runpy.run_path(str(ROOT / "engine.py")', bootstrap)

    def test_offline_build_contains_qt_runtime(self):
        builder = (ROOT / "scripts" / "build_songstudio_ready.ps1").read_text(
            encoding="utf-8")
        self.assertIn('PySide6==6.9.3', builder)
        self.assertIn("qt-site", builder)
        self.assertIn("desktop_window.py", builder)


if __name__ == "__main__":
    unittest.main()
