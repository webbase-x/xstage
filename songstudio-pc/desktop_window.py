"""Embedded Qt desktop window for X-Stage Song Studio PC Ready.

The existing localhost API and all audio/AI operations stay inside engine.py.
This module never launches Edge or the user's default browser for the main UI.
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

APP_USER_MODEL_ID = "XStage.SongStudio.PC"


def configure_windows_taskbar() -> None:
    """Identify the actual GUI process, not its Python runtime, to Explorer."""
    if os.name != "nt":
        return
    import ctypes
    set_app_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
    set_app_id.argtypes = [ctypes.c_wchar_p]
    set_app_id.restype = ctypes.c_long
    result = set_app_id(APP_USER_MODEL_ID)
    if result < 0:
        raise OSError(result, "Cannot set Song Studio Windows taskbar identity")


def validate_local_ui_url(url: str) -> int:
    """Only load our own loopback server; refuse remote app origins."""
    parts = urlsplit(url)
    if parts.scheme != "http" or parts.hostname != "127.0.0.1" or not parts.port or parts.username or parts.password:
        raise ValueError("Song Studio UI must use the local loopback server")
    return parts.port


def run_desktop(server, url: str, data_directory: Path, icon: Path) -> None:
    """Run Qt on the main thread and the existing HTTP server on a worker."""
    ui_port = validate_local_ui_url(url)
    # Must run in pythonw.exe before Qt creates any native windows.
    configure_windows_taskbar()
    from PySide6.QtCore import QUrl, Qt
    from PySide6.QtGui import QDesktopServices, QIcon
    from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
    from PySide6.QtWebEngineWidgets import QWebEngineView


    # QtWebEngine is embedded in the app, not the user's Edge profile.
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("X-Stage Song Studio PC")
    app.setOrganizationName("X-Stage")
    app_icon = QIcon(str(icon)) if icon.is_file() else QIcon()
    if app_icon.isNull():
        app_icon = QIcon(str(icon.with_name("app-icon-512.png")))
    app.setWindowIcon(app_icon)
    profile = QWebEngineProfile("SongStudio", app)
    profile.setPersistentStoragePath(str(data_directory / "qt-webengine" / "storage"))
    profile.setCachePath(str(data_directory / "qt-webengine" / "cache"))

    class LocalPage(QWebEnginePage):
        def acceptNavigationRequest(self, target, navigation_type, is_main_frame):
            if not is_main_frame:
                return True
            target_url = target.toString()
            # Never allow arbitrary remote navigation to replace the app UI.
            parts = urlsplit(target_url)
            if (parts.scheme == "http" and parts.hostname == "127.0.0.1"
                    and parts.port == ui_port):
                return True
            if parts.scheme in ("https", "http") and parts.hostname:
                QDesktopServices.openUrl(target)
            return False

        def createWindow(self, window_type):
            # Third-party sign-in must occur in a separate system browser.
            return None

    class Window(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowIcon(app_icon)
            from engine import STATUS_VERSION, STATUS_BUILD
            self.setWindowTitle(f"X-Stage Song Studio PC v{STATUS_VERSION} · Build {STATUS_BUILD}")
            self.resize(1440, 900)
            self.view = QWebEngineView(self)
            self.page = LocalPage(profile, self.view)
            self.view.setPage(self.page)
            self.setCentralWidget(self.view)
            self.view.load(QUrl(url))

        def closeEvent(self, event):
            event.accept()
            app.quit()

    window = Window()
    window.showMaximized()
    # Avoid blocking the UI: server handles conversions in its own threads.
    from threading import Thread
    worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.25},
                    daemon=True, name="songstudio-local-server")
    worker.start()
    try:
        app.exec()
    finally:
        server.shutdown()
        worker.join(timeout=5)
