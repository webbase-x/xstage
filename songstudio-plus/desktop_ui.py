"""Windows-native Song Studio Plus desktop shell.

Uses embedded Qt WebEngine: one real app window with taskbar icon, rather
than opening Edge/Chrome. The existing SQLite and loopback-only HTTP engine
continue to run in a worker thread. No browser extension or plugin needed.
"""
from __future__ import annotations

import os
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit


def validate_local(url):
    address=urlsplit(url)
    if (address.scheme!="http" or address.hostname!="127.0.0.1" or
            not address.port or address.username or address.password):
        raise ValueError("Song Studio Plus ต้องเปิด UI จาก localhost ของตัวเองเท่านั้น")
    return address.port


def set_windows_identity():
    if os.name!="nt":
        return
    import ctypes
    set_id=ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
    set_id.argtypes=[ctypes.c_wchar_p]
    set_id.restype=ctypes.c_long
    result=set_id("XStage.SongStudio.Plus")
    if result<0:
        raise OSError(result,"Cannot set Windows taskbar identity")


def run_desktop(server,url,workspace,icon_path):
    port=validate_local(url)
    set_windows_identity()
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QShortcut
    from PySide6.QtWidgets import QApplication,QMainWindow
    from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile
    from PySide6.QtWebEngineWidgets import QWebEngineView

    app=QApplication.instance() or QApplication([])
    app.setApplicationName("X-Stage Song Studio Plus")
    app.setOrganizationName("X-Stage")
    icon=QIcon(str(icon_path)) if Path(icon_path).is_file() else QIcon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    storage=Path(workspace)/"QT"
    storage.mkdir(parents=True,exist_ok=True)
    profile=QWebEngineProfile("XStageSongStudioPlus",app)
    profile.setPersistentStoragePath(str(storage/"Storage"))
    profile.setCachePath(str(storage/"Cache"))

    class RestrictedPage(QWebEnginePage):
        def acceptNavigationRequest(self,target,navigation_type,is_main_frame):
            if not is_main_frame:
                return True
            uri=urlsplit(target.toString())
            if uri.scheme=="http" and uri.hostname=="127.0.0.1" and uri.port==port:
                return True
            if uri.scheme in ("http","https") and uri.hostname:
                QDesktopServices.openUrl(target)
            return False
        def createWindow(self,window_type):
            return None

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("X-Stage Song Studio Plus · Windows")
            self.setWindowIcon(icon)
            self.resize(1360,850)
            self.setMinimumSize(930,620)
            self.web=QWebEngineView(self)
            self.page=RestrictedPage(profile,self.web)
            self.web.setPage(self.page)
            self.setCentralWidget(self.web)
            # Large Windows desktops (including 2K/4K monitors) otherwise
            # render the original 14px web UI too small. Users can override
            # the default with familiar Ctrl+Plus / Ctrl+Minus / Ctrl+0.
            self.default_zoom=1.20
            self.web.setZoomFactor(self.default_zoom)
            self.shortcuts=[]
            for key,callback in (
                ("Ctrl++",lambda:self.change_zoom(+0.10)),
                ("Ctrl+=",lambda:self.change_zoom(+0.10)),
                ("Ctrl+-",lambda:self.change_zoom(-0.10)),
                ("Ctrl+0",lambda:self.web.setZoomFactor(self.default_zoom)),
            ):
                shortcut=QShortcut(QKeySequence(key),self)
                shortcut.activated.connect(callback)
                self.shortcuts.append(shortcut)
            self.web.load(QUrl(url))

        def change_zoom(self,step):
            self.web.setZoomFactor(
                max(0.90,min(1.80,round(self.web.zoomFactor()+step,2))))

        def closeEvent(self,event):
            event.accept()
            app.quit()

    window=MainWindow()
    # Server is ready before the embedded view requests localhost.
    worker=Thread(target=server.serve_forever,
                  kwargs={"poll_interval":0.2},
                  daemon=True,name="studio-plus-local-engine")
    worker.start()
    try:
        window.showMaximized()
        return app.exec()
    finally:
        server.shutdown()
        worker.join(timeout=5)
