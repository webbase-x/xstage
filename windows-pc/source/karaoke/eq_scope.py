"""Disable only X-Stage's owned APO filters before enabling in-app EQ."""
from .eq_model import flat

def suspend_windows_eq(settings):
    if settings.get('eq_scope')!='windows':return None
    from . import system_eq
    try:config=system_eq.installation()
    except FileNotFoundError:
        # APO was uninstalled; no endpoint processing to disable.
        return None
    if not system_eq.linked(config):return None
    device=settings.get('system_eq_device')
    if not device:raise ValueError('ไม่พบอุปกรณ์ EQ Windows เดิม กรุณาปิด EQ เดิมก่อนเปลี่ยนโหมด')
    state=flat();state['bypass']=True
    return system_eq.write(state,device,config)
