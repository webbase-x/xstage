"""UI-thread request ledger: occurrence ownership, approval and retry safety."""
from pathlib import Path
from .library import QueueItem, song_supports_key

ACTIVE = {'pending', 'queued'}

class RequestBook:
    def __init__(self):
        self.records = {}
        # Remember recently pruned request IDs for safe retries after a lost response.
        self.retired = {}

    def prune(self):
        # Keep all pending/queued requests. Only terminal records may be evicted,
        # in original insertion order. This prevents a long show from filling up.
        if len(self.records) < 4800:
            return
        for rid, record in tuple(self.records.items()):
            if len(self.records) <= 3500:
                break
            if record['status'] not in ACTIVE and record['status'] != 'playing':
                self.retired[rid] = record['owner']
                del self.records[rid]
        if len(self.retired) > 5000:
            for rid in tuple(self.retired)[:len(self.retired)-4000]:
                del self.retired[rid]

    def sync(self, app):
        queued = {getattr(item, 'request_id', ''): i+1 for i,item in enumerate(app.song_queue.items)}
        keys = {getattr(item, 'request_id', ''): item.key for item in app.song_queue.items}
        current = getattr(getattr(app, 'current_item', None), 'request_id', '')
        for rid, record in self.records.items():
            record['position'] = queued.get(rid)
            if rid in keys: record['key'] = keys[rid]
            if rid == current:
                record['status'] = 'playing'
            elif rid in queued:
                record['status'] = 'queued'
            elif record['status'] in ('queued', 'playing'):
                record['status'] = 'ended'
        self.prune()

    def command(self, app, command, policy):
        self.sync(app)
        action = command['action']
        owner = command.get('_owner', 'local')
        operator = command.get('_role') == 'operator' or owner == 'local'
        rid = str(command.get('request_id', ''))
        if not rid or len(rid) > 100:
            raise ValueError('คำขอไม่มีหมายเลขอ้างอิง')
        if action == 'queue':
            old = self.records.get(rid)
            if old:
                if old['owner'] != owner: raise ValueError('หมายเลขคำขอนี้ถูกใช้แล้ว')
                return {'ok': True, 'duplicate': True, 'request_id': rid}
            if rid in self.retired:
                if self.retired[rid] != owner:
                    raise ValueError('หมายเลขคำขอนี้ถูกใช้แล้ว')
                return {'ok': True, 'duplicate': True, 'request_id': rid}
            if not policy['accepting']: raise ValueError('หยุดรับคำขอเพลงชั่วคราว')
            if len(self.records) >= 5000: raise ValueError('คำขอที่ยังรอดำเนินการเต็ม กรุณาติดต่อผู้ดูแล')
            if sum(r['owner']==owner and r['status'] in ACTIVE for r in self.records.values()) >= policy['limit']:
                raise ValueError('ครบจำนวนเพลงที่รอได้ต่อเครื่องแล้ว')
            song = app.library.get(int(command['song_id']))
            if not song or not song['playable'] or not Path(song['path']).is_file(): raise ValueError('เพลงยังไม่พร้อมเล่น')
            singer = str(command.get('singer', '')).strip()[:60]
            if not singer: raise ValueError('กรุณาใส่ชื่อผู้ร้อง')
            key = int(command.get('key', 0))
            if not -12 <= key <= 12: raise ValueError('คีย์ต้องอยู่ระหว่าง -12 ถึง +12')
            capable = song_supports_key(song)
            if key and not capable: raise ValueError('เพลงนี้ไม่รองรับปรับคีย์')
            record = dict(request_id=rid, owner=owner, song_id=song['id'], title=song['title'], singer=singer,
                          key=key, supports_key=capable, status='pending', position=None)
            self.records[rid] = record
            if not policy['approval'] or operator:
                try: self.enqueue(app, record)
                except Exception:
                    self.records.pop(rid, None)
                    raise
        else:
            record = self.records.get(rid)
            if not record: raise ValueError('ไม่พบคำขอ')
            if not operator and record['owner'] != owner: raise ValueError('แก้ไขได้เฉพาะคำขอของตัวเอง')
            if not operator and not policy['allow_edit']: raise ValueError('ผู้ดูแลปิดการแก้ไขคำขอ')
            if action in ('approve', 'reject'):
                if not operator: raise ValueError('เฉพาะผู้ดูแล')
                if record['status'] != 'pending': raise ValueError('คำขอนี้ดำเนินการแล้ว')
                if action == 'approve': self.enqueue(app, record)
                else: record['status'] = 'rejected'
            elif action in ('cancel_request', 'request_key'):
                if record['status'] not in ACTIVE: raise ValueError('เพลงเริ่มเล่นหรือสิ้นสุดแล้ว')
                index = next((i for i,x in enumerate(app.song_queue.items) if getattr(x,'request_id','') == rid), None)
                if action == 'cancel_request':
                    if index is not None: app.song_queue.pop(index)
                    record['status'] = 'cancelled'
                else:
                    key = int(command['key'])
                    if not -12 <= key <= 12 or not record['supports_key']: raise ValueError('เพลงนี้ไม่รองรับคีย์ที่เลือก')
                    if index is not None:
                        app.song_queue.items[index].key = key
                        app.song_queue.save()
                    record['key'] = key
            else: raise ValueError('คำสั่งไม่ถูกต้อง')
        app.refresh_queue()
        return {'ok': True, 'request_id': rid}

    @staticmethod
    def enqueue(app, record):
        song = app.library.get(record['song_id'])
        if not song or not Path(song['path']).is_file(): raise ValueError('ไม่พบไฟล์เพลงแล้ว')
        item = QueueItem(record['song_id'], record['singer'], record['key'], request_id=record['request_id'])
        try:
            app.song_queue.add(item)
        except Exception:
            app.song_queue.items[:] = [queued for queued in app.song_queue.items if queued is not item]
            raise
        record['status'] = 'queued'
