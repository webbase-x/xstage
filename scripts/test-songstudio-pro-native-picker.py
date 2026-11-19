"""Windows native picker smoke test: queued Qt GUI-thread dialogs and Thai paths.

Run with QT_QPA_PLATFORM=offscreen so CI does not require an interactive
desktop. Actual Windows picker visuals still need a human test on a real PC.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"songstudio-plus"))

from PySide6.QtWidgets import QApplication,QFileDialog,QWidget
from native_picker import NativeFilePicker

qt=QApplication.instance() or QApplication([])
window=QWidget()
picker=NativeFilePicker(window)
gui_thread=threading.get_ident()

def call_in_worker(kind,current):
    result={}
    def run():
        try: result["value"]=picker.pick(kind,current)
        except Exception as error:result["error"]=str(error)
    thread=threading.Thread(target=run,name="http-worker")
    thread.start()
    limit=time.monotonic()+8
    while thread.is_alive() and time.monotonic()<limit:
        qt.processEvents()
        time.sleep(.008)
    assert not thread.is_alive(),"native picker signal did not return to worker"
    assert "error" not in result,result
    return result["value"]

with tempfile.TemporaryDirectory() as base:
    folder=Path(base)/"ชื่อไทย และ Unicode"
    folder.mkdir()
    lyric=folder/"เนื้อร้องภาษาไทย.lrc"
    lyric.write_text("lyrics",encoding="utf-8")
    called=[]
    def accept_folder(dialog):
        called.append(("folder",threading.get_ident(),dialog.directory().absolutePath()))
        assert dialog.fileMode()==QFileDialog.FileMode.Directory
        return QFileDialog.DialogCode.Accepted
    def accept_file(dialog):
        called.append(("lrc",threading.get_ident(),dialog.directory().absolutePath()))
        assert dialog.fileMode()==QFileDialog.FileMode.ExistingFile
        return QFileDialog.DialogCode.Accepted
    with patch.object(QFileDialog,"exec",new=accept_folder),\
         patch.object(QFileDialog,"selectedFiles",autospec=True,return_value=[str(folder)]):
        selected=call_in_worker("folder",str(folder))
        assert selected=={"path":str(folder),"cancelled":False},selected
    with patch.object(QFileDialog,"exec",new=accept_file),\
         patch.object(QFileDialog,"selectedFiles",autospec=True,return_value=[str(lyric)]):
        selection=call_in_worker("lrc",str(folder))
        assert selection=={"path":str(lyric),"cancelled":False},selection
    assert [call[0] for call in called]==["folder","lrc"]
    assert all(call[1]==gui_thread for call in called), "Qt dialogs must run on GUI thread"
    with patch.object(QFileDialog,"exec",autospec=True,return_value=QFileDialog.DialogCode.Rejected):
        cancelled=call_in_worker("folder",str(folder))
        assert cancelled["cancelled"] and not cancelled["path"]
    try:picker.pick("invalid")
    except ValueError:pass
    else:raise AssertionError("bad picker kind must fail before emitting")
print("PASS: Qt folder and LRC picker signals execute on GUI thread; Unicode paths and cancel are preserved")
