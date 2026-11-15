"""LAN-only mobile remote; short pairing codes exchange for private sessions."""
from __future__ import annotations
import json
import logging
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from .remote_page import PAGE
from .library import song_supports_key

class RemoteServer:
    def __init__(self, library, dispatch, snapshot, host='0.0.0.0', port=8080):
        self.library, self.dispatch, self.snapshot = library, dispatch, snapshot
        self.lock = threading.RLock()
        self.sessions, self.failures, self.rate = {}, {}, {}
        self.recent = {}
        self.command_lock = threading.Lock()
        self.generation = 0
        self.policy = dict(accepting=True, operator=False, approval=False, allow_edit=True, limit=3, audio=False, max_clients=10)
        from .remote_audio import RemoteAudio
        self.audio = RemoteAudio()
        self.rotate_codes()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def response(self, status, value, content_type='application/json; charset=utf-8'):
                data = value if isinstance(value, bytes) else value.encode('utf-8') if isinstance(value, str) else json.dumps(value, ensure_ascii=False).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; media-src 'none'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(data)
            def session(self):
                token = self.headers.get('Authorization','').removeprefix('Bearer ')
                with owner.lock:
                    owner.expire_sessions()
                    session = owner.sessions.get(token)
                    if session:
                        session['seen'] = time.monotonic()
                        return dict(session)
                return None
            def body(self):
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 4096: raise ValueError('คำสั่งใหญ่เกินกำหนด')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict): raise ValueError('คำสั่งไม่ถูกต้อง')
                return data
            def do_GET(self):
                try: self.get()
                except Exception:
                    logging.exception('REMOTE_GET failed')
                    self.response(503, {'error':'เครื่องเล่นยังไม่พร้อม'})
            def get(self):
                url = urlparse(self.path)
                if url.path == '/': return self.response(200, PAGE, 'text/html; charset=utf-8')
                if url.path == '/assets/mobile-logo.jpg':
                    from .remote_branding import mobile_logo
                    return self.response(200,mobile_logo(),'image/jpeg')
                session = self.session()
                if not session: return self.response(401, {'error':'กรุณาเชื่อมต่อด้วยรหัสใหม่'})
                operator = session['role']=='operator' and owner.policy['operator']
                if url.path == '/api/audio':
                    try:
                        after = int(parse_qs(url.query).get('after',['0'])[0])
                    except ValueError:
                        return self.response(400,{'error':'Invalid audio sequence'})
                    with owner.lock:
                        if self.headers.get('Authorization','').removeprefix('Bearer ') not in owner.sessions:
                            return self.response(401,{'error':'การเชื่อมต่อหมดสิทธิ์แล้ว'})
                        if not owner.policy.get('audio'):
                            return self.response(403,{'error':'เครื่องหลักไม่อนุญาตเสียงมือถือ'})
                        try: audio = owner.audio.read(after)
                        except PermissionError as error: return self.response(403,{'error':str(error)})
                        return self.response(200,audio)
                if url.path == '/api/state':
                    state = owner.snapshot()
                    records = state.pop('requests', [])
                    own = [{k:v for k,v in r.items() if k not in ('owner','song_id')} for r in records if r['owner']==session['owner']]
                    pending = [{k:v for k,v in r.items() if k not in ('owner','song_id')} for r in records if r['status']=='pending'] if operator else []
                    state.update(operator=operator, policy=dict(owner.policy), mine=own, pending=pending)
                    return self.response(200,state)
                if url.path == '/api/songs':
                    query = parse_qs(url.query).get('q',[''])[0][:200]
                    songs = owner.library.search(query,limit=60)
                    keys = ('id','code','title','artist','kind','format','playable')
                    return self.response(200,{'songs':[{**{k:row[k] for k in keys}, 'supports_key':song_supports_key(row)} for row in songs]})
                return self.response(404, {'error':'ไม่พบรายการ'})
            def do_POST(self):
                origin = self.headers.get('Origin')
                if origin and urlparse(origin).netloc != self.headers.get('Host'):
                    return self.response(403, {'error':'Origin ไม่ตรงกับเครื่องเล่น'})
                try:
                    path = urlparse(self.path).path
                    command = self.body()
                    if path == '/api/login':
                        now, ip = time.monotonic(), self.client_address[0]
                        code = str(command.get('code','')).replace(' ','')
                        with owner.lock:
                            attempts = [t for t in owner.failures.get(ip,[]) if now-t<60]
                            if len(attempts)>=5: return self.response(429,{'error':'รหัสผิดหลายครั้ง กรุณารอ 1 นาที'})
                            role = None
                            if code.isascii():
                                if secrets.compare_digest(code,owner.request_key): role='guest'
                                elif secrets.compare_digest(code,owner.operator_key) and owner.policy['operator']: role='operator'
                            if not role:
                                owner.failures[ip] = attempts+[now]
                                return self.response(401,{'error':'รหัสไม่ถูกต้อง หรือปิดสิทธิ์ควบคุมอยู่'})
                            owner.expire_sessions()
                            if len(owner.sessions)>=owner.policy['max_clients']: return self.response(503,{'error':'ผู้ใช้งานเต็ม กรุณารอสักครู่ กำลังลองเชื่อมต่อใหม่','full':True,'retry_after':5})
                            token = secrets.token_urlsafe(32)
                            owner.sessions[token] = dict(owner=secrets.token_hex(16), role=role, seen=now, active=now, latency_ms=0, generation=owner.generation)
                        return self.response(200, {'token':token})
                    session = self.session()
                    if not session: return self.response(401,{'error':'กรุณาเชื่อมต่อด้วยรหัสใหม่'})
                    if path == '/api/activity':
                        with owner.lock:
                            current=owner.sessions.get(self.headers.get('Authorization','').removeprefix('Bearer '))
                            if not current:return self.response(401,{'error':'การเชื่อมต่อหมดอายุ'})
                            if command.get('active') is True or command.get('live') is True:
                                current['active']=time.monotonic()
                            try: latency=float(command.get('latency_ms',0))
                            except (ValueError,TypeError):latency=0
                            if 0<latency<10000:current['latency_ms']=latency
                        return self.response(200,{'ok':True})
                    if path == '/api/logout':
                        with owner.lock: owner.sessions.pop(self.headers.get('Authorization','').removeprefix('Bearer '),None)
                        return self.response(200,{'ok':True})
                    if path != '/api/command': return self.response(404,{'error':'ไม่พบรายการ'})
                    action = command.get('action')
                    guest_actions = {'queue','cancel_request','request_key'}
                    operator_actions = {'approve','reject','play_pause','next','stop','key','speed','volume'}
                    if action not in guest_actions|operator_actions or (action in operator_actions and (session['role']!='operator' or not owner.policy['operator'])):
                        return self.response(403,{'error':'ไม่มีสิทธิ์ใช้คำสั่งนี้'})
                    now = time.monotonic()
                    with owner.lock:
                        current=owner.sessions.get(self.headers.get('Authorization','').removeprefix('Bearer '))
                        if current:current['active']=now
                        stamps = [t for t in owner.rate.get(session['owner'],[]) if now-t<10]
                        if len(stamps)>=20: return self.response(429,{'error':'ส่งคำสั่งถี่เกินไป กรุณารอสักครู่'})
                        owner.rate[session['owner']] = stamps+[now]
                    clean = {k:v for k,v in command.items() if not k.startswith('_')}
                    clean.update(_owner=session['owner'],_role=session['role'],_generation=session['generation'],_session=self.headers.get('Authorization','').removeprefix('Bearer '))
                    identity = str(command.get('request_id', ''))[:100]
                    cache_key = (session['owner'],identity)
                    with owner.command_lock:
                        if action == 'queue' and identity and cache_key in owner.recent:
                            return self.response(200,dict(owner.recent[cache_key],duplicate=True))
                        result = owner.dispatch(clean)
                        if action == 'queue' and identity and result.get('ok'):
                            owner.recent[cache_key] = dict(result)
                            # Do not retain every command response for the entire show.
                            if len(owner.recent)>2048:
                                for expired in tuple(owner.recent)[:512]:
                                    owner.recent.pop(expired,None)
                    return self.response(200 if result.get('ok') else 400,result)
                except (ValueError, TypeError, KeyError, OverflowError) as error: self.response(400,{'error':str(error)})
                except Exception:
                    logging.exception('REMOTE_POST failed')
                    self.response(503,{'error':'เครื่องเล่นยังไม่พร้อมรับคำสั่ง'})

        self.server = ThreadingHTTPServer((host,int(port)),Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True,name='karaoke-remote')

    def rotate_codes(self):
        with self.lock:
            previous = {getattr(self,'request_key',''),getattr(self,'operator_key','')}
            self.request_key = f'{secrets.randbelow(1000000):06d}'
            while self.request_key in previous: self.request_key=f'{secrets.randbelow(1000000):06d}'
            self.operator_key = f'{secrets.randbelow(1000000):06d}'
            while self.operator_key in previous|{self.request_key}: self.operator_key=f'{secrets.randbelow(1000000):06d}'
            self.sessions.clear()
            self.recent.clear()
            self.generation += 1

    def configure(self, **values):
        if 'max_clients' in values:
            values['max_clients']=max(1,min(100,int(values['max_clients'])))
        with self.lock:
            if self.policy['operator'] and values.get('operator') is False:
                self.sessions = {t:s for t,s in self.sessions.items() if s['role']!='operator'}
            self.policy.update(values)
            self.audio.configure(self.policy.get('audio',False))

    def expire_sessions(self):
        now=time.monotonic()
        with self.lock:
            # A live foreground client polls /api/state every ~500ms.  Its GET
            # heartbeat is not an input action, but must keep its session alive.
            # A backgrounded/lost client stops polling and expires normally.
            self.sessions={token:s for token,s in self.sessions.items()
                           if now-s.get('seen',0)<90 or now-s.get('active',s['seen'])<300}

    def capacity_stats(self):
        with self.lock:
            self.expire_sessions()
            latencies=[s.get('latency_ms',0) for s in self.sessions.values() if s.get('latency_ms',0)>0]
            return len(self.sessions),max(latencies,default=0)

    def connected_count(self):
        with self.lock: return sum(time.monotonic()-s['seen']<15 for s in self.sessions.values())
    def start(self): self.thread.start()
    def close(self):
        self.audio.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
