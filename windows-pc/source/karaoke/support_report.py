"""Local diagnostics; never labels unperformed manual checks as passed."""
import platform
from datetime import datetime,timezone
from pathlib import Path
from .library import read_json,write_json
from . import __version__
MANUAL={
 'continuous':'เล่นต่อเนื่องพร้อม EQ / รีโมท / บันทึกเสียง',
 'song_eq':'เปลี่ยนเพลงและเรียก EQ ประจำเพลง / Crossfade',
 'display':'หน้าต่าง EQ / Mixer / บันทึกเสียง / รีโมท ที่ 125–200%',
 'install':'ติดตั้งเครื่องใหม่และอัปเดตโดยข้อมูลเดิมยังอยู่'}

def manual_results(value):
    result={}
    for name in MANUAL:
        entry=value.get(name,{}) if isinstance(value,dict) else {}
        state=entry.get('status','ยังไม่ทดสอบ') if isinstance(entry,dict) else 'ยังไม่ทดสอบ'
        if state not in ('ยังไม่ทดสอบ','ผ่าน','พบปัญหา'):state='ยังไม่ทดสอบ'
        result[name]={'status':state,'note':str(entry.get('note',''))[:2000] if isinstance(entry,dict) else '', 'source':'user-reported'}
    return result

def collect(home,data):
    from .dependency_check import inspect
    report={'schema':1,'version':__version__,'created_utc':datetime.now(timezone.utc).isoformat(),
      'system':platform.platform(),'machine':platform.machine(),'dependencies':inspect(home),
      'manual_checks':manual_results(read_json(Path(data)/'manual-checks.json',{})),
      'audio_test':'not performed by this report','privacy':'Local report only. May contain device names and installation paths; no settings, passwords, remote PIN or song catalog included.'}
    try:
        from .windows_audio import audio_context
        with audio_context() as sc:
            default=sc.default_speaker()
            report['output_devices']=[{'name':s.name,'default':bool(default and s.id==default.id)} for s in sc.all_speakers()]
    except Exception as error:report['output_devices_error']=str(error)
    report['repair']=read_json(Path(data)/'repair-status.json',{'status':'not run'})
    return report

def run(home,data,path):
    write_json(Path(path),collect(home,data));return 0
