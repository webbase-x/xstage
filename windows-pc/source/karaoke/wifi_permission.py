"""Explicit personal-PC repair launch. UAC is handled by the bundled script."""
from pathlib import Path
import os
import subprocess
import sys


def repair_script():
    root=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent.parent
    path=root/'tools'/'Repair-XStage-WiFi.ps1'
    if not path.is_file():raise FileNotFoundError('ไม่พบชุดเปิดสิทธิ์ Wi-Fi กรุณาติดตั้งโปรแกรมให้ครบชุด')
    return path


class PermissionRepair:
    def __init__(self):self.process=None
    @property
    def running(self):return self.process is not None and self.process.poll() is None
    def launch(self,restore=False):
        if self.running:return False
        if sys.platform!='win32':raise OSError('เปิดสิทธิ์ Wi-Fi ได้เฉพาะ Windows')
        exe=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32'/'WindowsPowerShell'/'v1.0'/'powershell.exe'
        command=[str(exe),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(repair_script()),'-NoPause']
        if restore:command.append('-RestoreLatest')
        self.process=subprocess.Popen(command,creationflags=getattr(subprocess,'CREATE_NEW_CONSOLE',0))
        return True
    def completed(self):
        if self.process is None:return None
        code=self.process.poll()
        if code is not None:self.process=None
        return code


def wifi_heading(state):
    if state.ssid:return state.ssid
    return {'checking':'กำลังตรวจสอบ Wi-Fi…','denied':'Windows ปิดสิทธิ์อ่านชื่อ Wi-Fi',
            'no_adapter':'ไม่พบอะแดปเตอร์ Wi-Fi','service_off':'บริการ Wi-Fi ยังไม่ทำงาน',
            'disconnected':'ยังไม่ได้เชื่อมต่อ Wi-Fi','no_ip':'Wi-Fi ยังไม่ได้รับ IP',
            'unsupported':'ตรวจอัตโนมัติได้บน Windows','error':'ตรวจข้อมูล Wi-Fi ไม่สำเร็จ'}.get(state.status,'กำลังตรวจสอบ Wi-Fi…')


class PendingRemoteStart:
    def __init__(self):self.requested=False
    def request(self):self.requested=True
    def cancel(self):self.requested=False
    def consume(self,ready):
        if not self.requested or not ready:return False
        self.requested=False
        return True
