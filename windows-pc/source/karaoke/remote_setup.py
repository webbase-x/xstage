"""Sequential setup rules shared by the desktop wizard and regression tests."""


def network_actions(status, ready, repairing=False):
    if ready or repairing or status == 'checking':
        return dict(permission=False, connect=False, refresh=False)
    return dict(permission=status=='denied',
                connect=status in ('disconnected','no_adapter','service_off','no_ip'),
                refresh=status not in ('unsupported',))


def validate_setup(ready, repairing, port, limit):
    if repairing:
        raise ValueError('กรุณารอชุดจัดการสิทธิ์ทำงานเสร็จก่อน')
    if not ready:
        raise ValueError('กรุณาเชื่อมต่อ Wi-Fi และเปิดสิทธิ์ให้ตรวจพบชื่อเครือข่ายและ IP ก่อน')
    try:
        port, limit = int(port), int(limit)
    except (ValueError, TypeError):
        raise ValueError('พอร์ตและจำนวนเพลงรอต้องเป็นตัวเลข') from None
    if not 1024 <= port <= 65535:
        raise ValueError('พอร์ตต้องอยู่ระหว่าง 1024–65535')
    if not 1 <= limit <= 20:
        raise ValueError('จำนวนเพลงรอต้องอยู่ระหว่าง 1–20')
    return port, limit


class RemoteSetup:
    def __init__(self, running=False):
        self.step = 2 if running else 0

    def next(self, ready, repairing=False):
        if repairing or not ready:
            self.step = 0
            return False
        if self.step == 0:
            self.step = 1
            return True
        return False  # Only a successful server start completes step 2.

    def started(self):
        self.step = 2

    def back(self):
        self.step = max(0, self.step - 1)

    def network_changed(self, ready, running):
        if not ready and not running:
            self.step = 0

    def stopped(self):
        self.step = 0
