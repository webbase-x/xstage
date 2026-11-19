"""Windows-native Song Studio Pro desktop shell.

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
        raise ValueError("Song Studio Pro ต้องเปิด UI จาก localhost ของตัวเองเท่านั้น")
    return address.port


def set_windows_identity():
    if os.name!="nt":
        return
    import ctypes
    set_id=ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
    set_id.argtypes=[ctypes.c_wchar_p]
    set_id.restype=ctypes.c_long
    result=set_id("XStage.SongStudio.Pro")
    if result<0:
        raise OSError(result,"Cannot set Windows taskbar identity")



def _apply_taskbar_icon(window,icon_path):
    """Set both Windows taskbar (small) and Alt-Tab (large) icon handles.

    Qt/QIcon generally sets these itself, but some PyInstaller/QtWebEngine
    builds otherwise display a Qt/Python generic taskbar icon. Handles live
    until the window closes and are never installed globally.
    """
    if os.name!="nt" or not Path(icon_path).is_file():
        return []
    import ctypes
    from ctypes import wintypes
    user32=ctypes.WinDLL("user32",use_last_error=True)
    user32.LoadImageW.argtypes=(wintypes.HINSTANCE,wintypes.LPCWSTR,
                                wintypes.UINT,ctypes.c_int,ctypes.c_int,wintypes.UINT)
    user32.LoadImageW.restype=wintypes.HANDLE
    user32.SendMessageW.argtypes=(wintypes.HWND,wintypes.UINT,
                                  wintypes.WPARAM,wintypes.LPARAM)
    user32.SendMessageW.restype=wintypes.LPARAM
    user32.GetSystemMetrics.argtypes=(ctypes.c_int,)
    user32.GetSystemMetrics.restype=ctypes.c_int
    IMAGE_ICON=1
    LR_LOADFROMFILE=0x10
    WM_SETICON=0x80
    ICON_SMALL=0
    ICON_BIG=1
    hwnd=int(window.winId())
    handles=[]
    for icon_type,metric_x,metric_y in ((ICON_SMALL,49,50),(ICON_BIG,11,12)):
        width=user32.GetSystemMetrics(metric_x)
        height=user32.GetSystemMetrics(metric_y)
        handle=user32.LoadImageW(None,str(icon_path),IMAGE_ICON,
                                 width,height,LR_LOADFROMFILE)
        if handle:
            user32.SendMessageW(hwnd,WM_SETICON,icon_type,int(handle))
            handles.append(handle)
    return handles

def _destroy_taskbar_icons(handles):
    if not handles or os.name!="nt":
        return
    import ctypes
    user32=ctypes.WinDLL("user32")
    user32.DestroyIcon.argtypes=(ctypes.c_void_p,)
    for handle in handles:
        user32.DestroyIcon(handle)

def run_desktop(server,url,workspace,icon_path,state=None):
    port=validate_local(url)
    set_windows_identity()
    from PySide6.QtCore import QUrl, QTimer
    from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QShortcut
    from PySide6.QtWidgets import QApplication,QMainWindow,QMessageBox
    from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile
    from PySide6.QtWebEngineWidgets import QWebEngineView

    app=QApplication.instance() or QApplication([])
    app.setApplicationName("X-Stage Song Studio Pro")
    app.setOrganizationName("X-Stage")
    preferred=Path(icon_path)
    fallback=Path(__file__).resolve().parent/"web"/"icon.svg"
    icon_file=preferred if preferred.is_file() else fallback
    icon=QIcon(str(icon_file)) if icon_file.is_file() else QIcon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    storage=Path(workspace)/"QT"
    storage.mkdir(parents=True,exist_ok=True)
    profile=QWebEngineProfile("XStageSongStudioPro",app)
    profile.setPersistentStoragePath(str(storage/"Storage"))
    profile.setCachePath(str(storage/"Cache"))
    # Always load the packaged JS/CSS from the current EXE. Old cached assets
    # can otherwise make the UI appear while button handlers come from an
    # earlier build.
    profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache)

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
        def javaScriptConsoleMessage(self,level,message,line,source):
            if state is not None:
                state.diagnostic("web.console",
                    level=str(level),message=str(message)[:1600],
                    line=int(line),source=str(source)[:500])

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("X-Stage Song Studio Pro · Windows")
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
                ("Ctrl+Shift+L",self.open_log),
            ):
                shortcut=QShortcut(QKeySequence(key),self)
                shortcut.activated.connect(callback)
                self.shortcuts.append(shortcut)
        def change_zoom(self,step):
            self.web.setZoomFactor(
                max(0.90,min(1.80,round(self.web.zoomFactor()+step,2))))

        def open_log(self):
            if state is None:return
            try:
                state.log_path.touch(exist_ok=True)
                __import__("subprocess").Popen(["notepad.exe",str(state.log_path)],creationflags=getattr(__import__("subprocess"),"CREATE_NO_WINDOW",0),close_fds=True)
                state.diagnostic("log.opened",source="desktop-shortcut")
            except Exception as exc:
                state.diagnostic("log.open.error",source="desktop-shortcut",
                                 error=str(exc)[:1000])

        def closeEvent(self,event):
            event.accept()
            app.quit()

    window=None
    worker=None
    native_icons=[]
    try:
        # Build the native window first, but do NOT load localhost yet.
        window=MainWindow()

        # state.native_picker is registered by app.py with the Windows-native
        # FolderBrowserDialog/OpenFileDialog backend. Do not overwrite it with
        # a Qt picker here.

        # Start the loopback engine before QWebEngineView requests localhost.
        worker=Thread(target=server.serve_forever,
                      kwargs={"poll_interval":0.2},
                      daemon=True,name="studio-pro-local-engine")
        worker.start()

        # Record WebView lifecycle so a visible-but-dead UI can be diagnosed.
        window.web.loadStarted.connect(
            lambda:state.diagnostic("web.load.started",url=url) if state is not None else None)
        window.web.loadProgress.connect(
            lambda value:state.diagnostic("web.load.progress",value=int(value))
            if state is not None and int(value) in (25,50,75,100) else None)
        def on_load_finished(ok):
            if state is not None:
                state.diagnostic("web.load.finished",ok=bool(ok),url=url)
            if not ok:
                if state is not None:
                    state.diagnostic("web.core.check",bound=False,reason="load-failed")
                QMessageBox.warning(
                    window,"X-Stage Song Studio Pro",
                    "โหลดหน้าต่างโปรแกรมไม่สำเร็จ\n"
                    "กด Ctrl+Shift+L เพื่อเปิด Log วิเคราะห์")
                return
            def core_checked(bound):
                healthy=bool(bound)
                if state is not None:
                    state.diagnostic("web.core.check",bound=healthy)
                if not healthy:
                    QMessageBox.warning(
                        window,"X-Stage Song Studio Pro",
                        "หน้าโปรแกรมแสดงผลแล้ว แต่ JavaScript Core ยังไม่พร้อม\n"
                        "กด Ctrl+Shift+L เพื่อเปิด Log วิเคราะห์")
            QTimer.singleShot(
                1200,
                lambda:window.web.page().runJavaScript(
                    "Boolean(globalThis.__XSTAGE_CORE_BOUND__)",core_checked))
        window.web.loadFinished.connect(on_load_finished)
        try:
            window.web.renderProcessTerminated.connect(
                lambda status,code:state.diagnostic(
                    "web.render.terminated",status=str(status),code=int(code))
                if state is not None else None)
        except AttributeError:
            pass

        # Only now expose the UI: /api/session and /api/pick are both ready.
        if state is not None:
            state.diagnostic("web.load.request",url=url,
                             picker_ready=bool(state.native_picker))
        window.web.load(QUrl(url))

        # The update helper waits for this process to exit before replacing the
        # managed EXE. Finish/cancel the active SQLite job first, then quit Qt.
        exit_timer=QTimer(window)
        if state is not None:
            exit_timer.timeout.connect(lambda:app.quit() if state.ready_to_exit() else None)
            exit_timer.start(250)

        window.showMaximized()
        # Handle becomes available only after the native top-level HWND
        # exists; explicitly assign its taskbar and Alt-Tab images.
        native_icons=_apply_taskbar_icon(window,icon_file)
        return app.exec()
    finally:
        if state is not None:
            state.native_picker=None
        _destroy_taskbar_icons(native_icons)
        server.shutdown()
        if worker is not None:
            worker.join(timeout=5)


def run_browser_host(server,url,workspace,icon_path,state=None):
    """Run only the local engine host; open the UI in Windows' default browser.

    No QWebEngineView is created.  The process stays available from the Windows
    notification area so localhost APIs, import jobs, updates and diagnostics
    continue to work while the browser tab is open.
    """
    set_windows_identity()
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QAction,QIcon
    from PySide6.QtWidgets import QApplication,QMenu,QSystemTrayIcon

    app=QApplication.instance() or QApplication([])
    app.setApplicationName("X-Stage Song Studio Pro")
    app.setOrganizationName("X-Stage")
    app.setQuitOnLastWindowClosed(False)

    preferred=Path(icon_path)
    fallback=Path(__file__).resolve().parent/"web"/"icon.svg"
    icon_file=preferred if preferred.is_file() else fallback
    icon=QIcon(str(icon_file)) if icon_file.is_file() else QIcon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    worker=Thread(target=server.serve_forever,
                  kwargs={"poll_interval":0.2},
                  daemon=True,name="studio-pro-local-engine")
    worker.start()
    if state is not None:
        state.diagnostic("engine.started",port=server.server_port,
                         ui="windows-default-browser")

    tray=QSystemTrayIcon(icon,app)
    tray.setToolTip("X-Stage Song Studio Pro · Local Engine")
    menu=QMenu()
    open_action=QAction("เปิด X-Stage Song Studio Pro",menu)
    log_action=QAction("เปิด Log วิเคราะห์",menu)
    exit_action=QAction("ปิดโปรแกรม",menu)
    menu.addAction(open_action)
    menu.addAction(log_action)
    menu.addSeparator()
    menu.addAction(exit_action)
    tray.setContextMenu(menu)

    def open_ui():
        if state is not None: state.diagnostic("ui.open.request")
        os.startfile(url)

    def open_log():
        if state is None:return
        try:
            state.log_path.touch(exist_ok=True)
            os.startfile(str(state.log_path))
            state.diagnostic("log.opened",source="tray")
        except Exception as exc:
            state.diagnostic("log.open.error",error=str(exc)[:1000])

    open_action.triggered.connect(open_ui)
    log_action.triggered.connect(open_log)
    tray.activated.connect(
        lambda reason:open_ui() if reason==QSystemTrayIcon.ActivationReason.DoubleClick else None)

    def request_exit():
        if state is not None:
            state.diagnostic("app.exit.request",source="tray")
        app.quit()
    exit_action.triggered.connect(request_exit)

    exit_timer=QTimer()
    if state is not None:
        exit_timer.timeout.connect(
            lambda:app.quit() if state.ready_to_exit() else None)
        exit_timer.start(250)

    tray.show()
    QTimer.singleShot(100,open_ui)
    try:
        return app.exec()
    finally:
        tray.hide()
        if state is not None:
            state.diagnostic("engine.stopping")
        server.shutdown()
        worker.join(timeout=5)
