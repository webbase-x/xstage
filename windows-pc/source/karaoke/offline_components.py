"""Validate the offline component and its accompanying source/license files."""
import hashlib
import json
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def validate_component(root):
    root = Path(root).resolve()
    manifest = root / 'EqualizerAPO' / 'component.json'
    if not manifest.is_file():
        raise OSError('ยังไม่มีแพ็ก Equalizer APO ออฟไลน์ที่ครบทั้งตัวติดตั้ง ซอร์ส และใบอนุญาต')
    data = json.loads(manifest.read_text(encoding='utf-8-sig'))
    if data.get('name') != 'Equalizer APO' or data.get('version') != '1.4.2' or data.get('architecture') != 'x64':
        raise ValueError('แพ็ก Equalizer APO ไม่ตรงกับรุ่นที่รองรับ')
    expected = ('EqualizerAPO-x64-1.4.2.exe', 'EqualizerAPO-src-1.4.2.zip', 'COPYING.txt')
    for name in expected:
        file = manifest.parent / name
        if file.is_symlink() or not file.is_file() or sha256(file) != data.get('sha256', {}).get(name):
            raise ValueError('แพ็กออฟไลน์ไม่ครบหรือไฟล์เปลี่ยนไป: ' + name)
    return manifest.parent / expected[0]
