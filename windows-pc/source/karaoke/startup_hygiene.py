"""Conservative startup cleanup for abandoned temporary recovery files.

Files are moved to a quarantine folder, never deleted, so interrupted recovery
artifacts remain available for inspection.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import uuid

_PATTERNS=('*.restore.tmp','*.restore-tmp','*.sqlite3.tmp')

def quarantine_stale(data, age_seconds=86400):
    data=Path(data).resolve(); now=datetime.now(timezone.utc); moved=[]
    quarantine=data/'recovery-quarantine'
    cutoff=now-timedelta(seconds=max(0,int(age_seconds)))
    for pattern in _PATTERNS:
        for item in data.glob(pattern):
            try:
                stamp=datetime.fromtimestamp(item.stat().st_mtime,timezone.utc)
                if stamp >= cutoff or item.is_symlink(): continue
                quarantine.mkdir(exist_ok=True)
                target=quarantine/(item.name+'.'+uuid.uuid4().hex)
                shutil.move(str(item),str(target)); moved.append({'source':str(item),'quarantine':str(target)})
            except OSError:
                continue
    return moved