"""Five-row search pagination state; owned exclusively by the UI thread."""


class SearchPaging:
    SIZE = 5

    def __init__(self):
        self.reset(-1)

    def reset(self, revision):
        self.revision = revision
        self.offset = 0
        self.more = True
        self.inflight = 0
        self.advance = None

    def request(self, revision):
        if revision != self.revision or not self.more or self.inflight is not None:
            return None
        self.inflight = self.offset
        return self.offset

    def accept(self, revision, offset, count, more):
        if revision != self.revision or offset != self.inflight or offset != self.offset:
            return False
        self.offset += count
        self.more = bool(more and count)
        self.inflight = None
        return True

    def failed(self, revision, offset):
        if revision == self.revision and offset == self.inflight:
            self.inflight = None
            self.advance = None
