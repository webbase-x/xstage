"""One application process per resolved Data directory."""
import os
from pathlib import Path

class DataDirectoryLock:
    def __init__(self, directory):
        self.path = Path(directory).resolve() / '.xstage-instance.lock'
        self.file = None
    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open('a+b')
        try:
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b'0'); stream.flush()
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            stream.close()
            raise RuntimeError(f'Data directory already in use or cannot be locked: {self.path.parent}') from error
        self.file = stream
        return self
    def close(self):
        if self.file is not None:
            self.file.close(); self.file = None
