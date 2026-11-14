"""Explicit recovery of settings/queue/history from an operator-selected JSON copy."""
import logging
import os
from pathlib import Path
import tempfile
from .library import (JsonRecoveryError, SongQueue, parse_json, preserve_json,
                      read_json, validate_queue)


def validate_document(name, value):
    if name == 'settings.json':
        from .settings_schema import validate_settings
        validate_settings(value)
    elif name == 'queue.json':
        validate_queue(value)
    elif name == 'history.json':
        from .performance_features import validate_history
        validate_history(value)
    else:
        raise ValueError('หน้าจอนี้กู้คืนเฉพาะ settings.json, queue.json และ history.json')
    return value


def inspect_candidate(target, candidate):
    target, candidate = Path(target), Path(candidate)
    if target.resolve() == candidate.resolve():
        raise ValueError('เลือกไฟล์สำรองคนละไฟล์กับไฟล์ที่มีปัญหา')
    raw = candidate.read_bytes()
    value = parse_json(raw.decode('utf-8'))
    validate_document(target.name, value)
    return raw, value


_UNSET = object()


def target_revision(path):
    import hashlib
    try:return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except FileNotFoundError:return None


def restore_json(target, candidate, expected=None, expected_target=_UNSET):
    target, candidate = Path(target), Path(candidate)
    if target.is_symlink():
        raise ValueError('ไม่กู้คืนทับ symbolic link')
    raw, value = inspect_candidate(target, candidate)
    if expected is not None and raw != expected:
        raise ValueError('ไฟล์สำรองเปลี่ยนหลังแสดงตัวอย่าง กรุณาเลือกใหม่')
    revision = target_revision(target)
    if expected_target is not _UNSET and revision != expected_target:
        raise ValueError('ไฟล์ปลายทางเปลี่ยนระหว่างยืนยัน กรุณาตรวจสอบและเลือกใหม่')
    backup = preserve_json(target) if target.exists() else None
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=target.name + '.',
                                         suffix='.restore.tmp', delete=False) as output:
            temp = Path(output.name)
            output.write(raw); output.flush(); os.fsync(output.fileno())
        if target_revision(target) != revision:
            raise ValueError('ไฟล์ปลายทางเปลี่ยนระหว่างกู้คืน ไม่ได้แทนที่ไฟล์')
        temp.replace(target)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    logging.info('JSON_RECOVERY_COMPLETE document=%s', target.name)
    return backup


def preflight(data, prompt=None):
    """Run before constructing the player; keep the Data lock held throughout."""
    data = Path(data)
    if prompt is None:
        prompt = prompt_recovery
    while True:
        try:
            read_json(data / 'settings.json', {})
            SongQueue(data / 'queue.json')
            return True
        except JsonRecoveryError as error:
            logging.error('JSON_RECOVERY_REQUIRED document=%s', error.path.name)
            if not prompt(error):
                return False


def prompt_recovery(error, parent=None):
    return prompt_restore(error.path, str(error), parent=parent)


def prompt_restore(target, description, parent=None):
    import tkinter as tk
    from tkinter import filedialog, messagebox
    target = Path(target)
    owned_root = parent is None
    root = tk.Tk() if owned_root else parent
    if owned_root:root.withdraw()
    try:
        cancel_text = 'กดยกเลิกเพื่อปิดโปรแกรม' if owned_root else 'กดยกเลิกเพื่อกลับหน้าหลัก'
        if not messagebox.askyesno('กู้คืนข้อมูลจากไฟล์สำรอง',
                f'{description}\n\nเลือกไฟล์สำรอง JSON เพื่อกู้คืนหรือไม่?\n'
                f'ระบบจะตรวจไฟล์และสำรองของเดิมก่อนแทนที่ {cancel_text}', parent=root):
            return False
        while True:
            candidate = filedialog.askopenfilename(parent=root, title='เลือกไฟล์สำรองที่ถูกต้อง',
                filetypes=[('JSON และไฟล์สำรอง', '*.json *.bak'), ('ทุกไฟล์', '*.*')])
            if not candidate:return False
            try:
                raw, value = inspect_candidate(target, candidate)
                revision = target_revision(target)
                detail = f'{len(value):,} รายการ' if isinstance(value, list) else f'{len(value):,} ค่าตั้งต้น'
                if target.name == 'history.json':
                    detail += ' • หน้าประวัติแสดง 500 รายการล่าสุด ไม่เปลี่ยนคิวหรือเพลงที่เล่นอยู่'
                if not messagebox.askyesno('ยืนยันกู้คืน',
                    f'ไฟล์: {candidate}\nตรวจรูปแบบผ่าน: {detail}\n'
                    f'แทนที่: {target}\nไฟล์เดิมจะมีสำเนาเก็บไว้\nยืนยันกู้คืนหรือไม่?', parent=root):
                    return False
                backup = restore_json(target, candidate, expected=raw, expected_target=revision)
                messagebox.showinfo('กู้คืนสำเร็จ', f'กู้คืนแล้ว\nสำเนาเดิม: {backup or "ไม่มีไฟล์เดิม"}', parent=root)
                return True
            except (OSError, ValueError, UnicodeError) as failure:
                logging.exception('JSON_RECOVERY_FAILED document=%s', target.name)
                messagebox.showerror('ยังไม่กู้คืน', str(failure), parent=root)
    finally:
        if owned_root:root.destroy()
