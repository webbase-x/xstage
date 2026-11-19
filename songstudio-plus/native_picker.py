"""Qt native file/folder chooser for Song Studio Pro.

HTTP API handlers run on worker threads, while Qt widgets MUST be created and
shown on the GUI thread. Requests are queued through QObject Signal/Slot,
and only UTF-16/Unicode paths returned by QFileDialog are exposed to the UI.
"""
from __future__ import annotations
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QFileDialog


class NativeFilePicker(QObject):
    requested=Signal(object)

    def __init__(self,parent):
        super().__init__(parent)
        self.parent_window=parent
        self.last_directory=None
        self.requested.connect(self._on_request,Qt.ConnectionType.QueuedConnection)

    @Slot(object)
    def _on_request(self,message):
        try:
            kind=message["kind"]
            current=message.get("current") or ""
            initial=Path(current).expanduser() if current else None
            if initial and initial.is_file():
                initial=initial.parent
            if not initial or not initial.is_dir():
                initial=self.last_directory
            if not initial or not initial.is_dir():
                initial=Path.home()
            if kind=="folder":
                chosen=QFileDialog.getExistingDirectory(
                    self.parent_window,"เลือกโฟลเดอร์เพลงต้นฉบับ",
                    str(initial),QFileDialog.Option.ShowDirsOnly)
            elif kind=="lrc":
                chosen,_=QFileDialog.getOpenFileName(
                    self.parent_window,"เลือกไฟล์เนื้อร้อง .LRC",
                    str(initial),"ไฟล์เนื้อร้อง LRC (*.lrc);;ไฟล์ทั้งหมด (*)")
            else:
                raise ValueError("ประเภทการเลือกไม่ถูกต้อง")
            if chosen:
                selected=Path(chosen)
                self.last_directory=selected if selected.is_dir() else selected.parent
            message["result"]={"path":str(chosen or ""),
                               "cancelled":not bool(chosen)}
        except Exception as exc:
            message["error"]=str(exc) or type(exc).__name__
        finally:
            message["done"].set()

    def pick(self,kind,current=""):
        if kind not in ("folder","lrc"):
            raise ValueError("ประเภทการเลือกไม่ถูกต้อง")
        request={"kind":kind,"current":str(current or ""),"done":Event()}
        self.requested.emit(request)
        if not request["done"].wait(300):
            raise TimeoutError("หน้าต่างเลือกโฟลเดอร์ไม่ตอบสนอง กรุณาลองใหม่")
        if "error" in request:
            raise RuntimeError("เลือกไฟล์หรือโฟลเดอร์ไม่สำเร็จ: "+request["error"])
        return request["result"]
