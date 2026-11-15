"""Bounded latest-request metadata worker; never calls Tk from a worker."""
import logging
from pathlib import Path
import threading
from .soundfont import inspect_font


def inspect_metadata(path):
    path = Path(path)
    path.stat()
    return inspect_font(path)


class MetadataLoader:
    def __init__(self, inspect=inspect_metadata):
        self.inspect = inspect
        self.condition = threading.Condition()
        self.pending = None
        self.result = None
        self.generation = 0
        self.closed = False
        self.thread = None

    def submit(self, path):
        with self.condition:
            if self.closed:
                raise RuntimeError('Metadata loader closed')
            self.generation += 1
            self.pending = (self.generation, path)
            self.result = None
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, name='soundfont-metadata', daemon=True)
                self.thread.start()
            self.condition.notify()
            return self.generation

    def cancel(self):
        with self.condition:
            self.generation += 1
            self.pending = self.result = None
            self.condition.notify()
            return self.generation

    def close(self, timeout=2.0):
        """Stop the worker and wait briefly so file handles are released."""
        with self.condition:
            self.closed = True
            self.pending = self.result = None
            self.condition.notify()
        thread = self.thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, float(timeout)))
            if thread.is_alive():
                logging.error('SOUNDFONT_METADATA_CLOSE_TIMEOUT alive=%s', thread.name)
                return False
        return True

    def take(self):
        with self.condition:
            result, self.result = self.result, None
            return result

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self.pending is not None)
                if self.closed:
                    return
                token, path = self.pending
                self.pending = None
            try:
                logging.info('SOUNDFONT_METADATA_BEGIN request=%s', token)
                info, error = self.inspect(path), None
            except Exception as failure:
                info, error = None, failure
                logging.exception('SOUNDFONT_METADATA_FAILED request=%s', token)
            with self.condition:
                if self.closed:
                    return
                if token == self.generation:
                    self.result = (token, path, info, error)
                    logging.info('SOUNDFONT_METADATA_END request=%s ok=%s', token, error is None)
                else:
                    logging.info('SOUNDFONT_METADATA_DISCARDED request=%s', token)
