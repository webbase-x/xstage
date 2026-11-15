"""Read-only detection of cleanup journals left by an interrupted process."""
from contextlib import closing
import json
import sqlite3
from pathlib import Path

UNRESOLVED = frozenset(('backed_up','files_deleted','partial'))

def find_pending(report_root):
    root=Path(report_root)
    if not root.is_dir(): return []
    found=[]
    for folder in sorted(root.glob('Cleanup-*')):
        journal=folder/'execution.sqlite3'; summary_file=folder/'summary.json'
        if not journal.is_file() or not summary_file.is_file(): continue
        try:
            summary=json.loads(summary_file.read_text(encoding='utf-8'))
            with closing(sqlite3.connect(journal.resolve().as_uri()+'?mode=ro',uri=True)) as db:
                states={state:int(count) for state,count in db.execute('SELECT state,COUNT(*) FROM actions GROUP BY state')}
        except (OSError,ValueError,sqlite3.Error):
            continue
        unresolved={state:count for state,count in states.items() if state in UNRESOLVED and count}
        if unresolved:
            found.append({'folder':str(folder.resolve()),'summary':summary,'states':states,'unresolved':unresolved,'recovery_required':True})
    return found