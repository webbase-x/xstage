"""Installer preflight; checks imports and native ABI without playing audio."""
import ctypes
import importlib
import json
import os
from pathlib import Path
import struct
import sys

NATIVE={'bass.dll':'BASS_GetVersion','bassmidi.dll':'BASS_MIDI_GetVersion','bass_fx.dll':'BASS_FX_GetVersion'}
MODULES=('tkinter','PIL.Image','PIL.ImageTk','numpy','qrcode','soundcard','_cffi_backend')

def inspect(home, importer=importlib.import_module):
    report={'ok':False,'platform':sys.platform,'python':sys.version.split()[0], 'bits':struct.calcsize('P')*8,'checks':[],'notes':[
        'Checks library loading only; microphone permission, firewall, audio drivers and SoundFont content are separate.',
        'Video formats depend on Windows media components/codecs. This is not a playback certification.'
    ]}
    def check(name,fn):
        try:
            value=fn();report['checks'].append({'name':name,'ok':True,'detail':str(value or 'ready')})
        except Exception as exc:report['checks'].append({'name':name,'ok':False,'detail':str(exc)})
    def platform_check():
        if sys.platform!='win32' or struct.calcsize('P')!=8:raise OSError('Windows x64 required')
    check('Windows x64',platform_check)
    for name in MODULES:check(name,lambda name=name:importer(name))
    native=Path(home)/'native'/'x64'
    from .bass import BassSynth
    for name in NATIVE:check(name+' PE',lambda name=name:BassSynth.validate_dll(native/name))
    if sys.platform=='win32' and struct.calcsize('P')==8:
        def load_native():
            with os.add_dll_directory(str(native)):
                # Hold BASS until both dependent libraries have loaded.
                loaded=[]
                for name,export in NATIVE.items():
                    dll=ctypes.WinDLL(str(native/name));loaded.append(dll)
                    fn=getattr(dll,export);fn.restype=ctypes.c_uint32;fn.argtypes=[]
                    version=fn()
                    if version>>16!=0x204:raise OSError(name+': requires BASS 2.4 API')
                return 'BASS/BASSMIDI/BASS FX 2.4 x64 loaded'
        check('Native load/API',load_native)
    report['ok']=all(item['ok'] for item in report['checks'])
    return report

def run(home,path=None):
    path=Path(path) if path else Path(home)/'dependency-report.json'
    report=inspect(home)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['ok'] else 1
