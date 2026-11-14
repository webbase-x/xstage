"""Equalizer APO integration: endpoint-scoped config, never loopback replay."""
import math
import os
import re
import tempfile
from pathlib import Path
from .eq_model import validate

GUID=re.compile(r'\{[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\}')
MARKER=b'# X-STAGE SYSTEM EQ BEGIN'

def endpoint_guid(value):
    matches=GUID.findall(str(value))
    if len(matches)!=1:raise ValueError('กรุณาเลือกอุปกรณ์เสียง Windows ที่ถูกต้อง')
    return matches[0].lower()

def installation():
    if os.name!='nt':raise OSError('EQ เสียงรวมใช้ได้บน Windows')
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\EqualizerAPO',0,winreg.KEY_READ|winreg.KEY_WOW64_64KEY) as key:
        path=Path(winreg.QueryValueEx(key,'ConfigPath')[0])
    if not (path/'config.txt').is_file():raise OSError('ไม่พบ config.txt ของ Equalizer APO')
    return path

def endpoints():
    from .windows_audio import audio_context
    with audio_context() as sc:return [(str(s.id),s.name) for s in sc.all_speakers()]

def render(state,device):
    state=validate(state);guid=endpoint_guid(device)
    lines=['# Managed by X-Stage. Change through X-Stage EQ.',f'Device: {guid}','Stage: post-mix','Channel: all']
    if state['bypass']:lines.append('# BYPASS: no X-Stage processing')
    else:
        lines.append(f"Preamp: {state['preamp_db']:.8g} dB")
        for b in state['bands']:
            if not b['enabled']:continue
            kind=b['kind'];q=b['q'];gain=b['gain_db']
            code={'bell':'PK','low_cut':'HPQ','high_cut':'LPQ','notch':'NO','low_shelf':'LSC','high_shelf':'HSC'}[kind]
            if 'shelf' in kind:
                A=10**(gain/40);q=1/math.sqrt((A+1/A)*(1/b['slope']-1)+2)
            line=f"Filter: ON {code} Fc {b['frequency']:.8g} Hz"
            if kind in ('bell','low_shelf','high_shelf'):line+=f' Gain {gain:.8g} dB'
            lines.append(line+f' Q {q:.10g}')
        lines.append(f"Preamp: {state['output_db']:.8g} dB")
    lines+=['Device: all','Channel: all','Stage: post-mix capture','']
    return '\n'.join(lines).encode('utf-8')

def target(config):return Path(config)/'XStage'/'xstage-eq.txt'

def linked(config):
    data=(Path(config)/'config.txt').read_bytes()
    return MARKER in data and b'Include: XStage/xstage-eq.txt' in data

def atomic_write(path,data):
    path=Path(path);temp=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.xstage-',delete=False) as out:
            temp=Path(out.name);out.write(data);out.flush();os.fsync(out.fileno())
        os.replace(temp,path)
    finally:
        if temp is not None and temp.exists():temp.unlink()

def write(state,device,config=None):
    data=render(state,device);config=Path(config) if config is not None else installation()
    if not linked(config):raise OSError('ยังไม่ได้เชื่อม X-Stage • เปิดแท็บ Windows แล้วกดเชื่อมต่อครั้งแรก')
    path=target(config)
    if not path.is_file():raise OSError('ไฟล์เชื่อมต่อ EQ หาย กรุณาตั้งค่าใหม่')
    old=path.read_bytes();atomic_write(path,data);return path,old

def open_selector():
    import sys
    from .external_program import launch
    root=installation().parent
    home=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
    script=home/'tools'/'Open-APO-Device.ps1'
    if not script.is_file():raise OSError('Missing Open-APO-Device.ps1')
    for name in ('DeviceSelector.exe','Configurator.exe'):
        exe=root/name
        if exe.is_file():
            return launch(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',script,'-Program',exe],root,hidden=True)
    raise OSError('Equalizer APO Device Selector is missing')


def setup(app):
    import subprocess
    path=Path(app.home)/'tools'/'Setup-System-EQ.ps1'
    if not path.is_file():raise OSError('ชุดติดตั้งไม่ครบ: ไม่พบ Setup-System-EQ.ps1')
    from .external_program import launch
    return launch(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(path)],path.parent)
